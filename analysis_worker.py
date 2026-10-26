import logging
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from auth import get_supabase_client
from model_inference import ModelConfigurationError, get_model_spec, model_cache

UPLOAD_BUCKET = "analysis-uploads"
logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_next_job() -> Optional[dict]:
    """Claim one queued job. The status predicate prevents double processing."""
    client = get_supabase_client()
    response = (
        client.table("analysis_jobs")
        .select("id, upload_id, user_id, crop_code, confidence_threshold")
        .eq("status", "queued")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not response.data:
        return None

    candidate = response.data[0]
    claimed = (
        client.table("analysis_jobs")
        .update({"status": "processing", "started_at": utc_now(), "error_message": None})
        .eq("id", candidate["id"])
        .eq("status", "queued")
        .execute()
    )
    return candidate if claimed.data else None


def is_cancel_requested(job_id: str) -> bool:
    response = (
        get_supabase_client()
        .table("analysis_jobs")
        .select("status")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    return bool(response.data and response.data[0]["status"] in {"cancel_requested", "cancelled"})


def mark_cancelled(job_id: str) -> None:
    client = get_supabase_client()
    client.table("analysis_detections").delete().eq("job_id", job_id).execute()
    client.table("analysis_jobs").update(
        {
            "status": "cancelled",
            "completed_at": utc_now(),
            "error_message": None,
            "result_summary": None,
        }
    ).eq("id", job_id).eq("status", "cancel_requested").execute()


def stop_if_cancelled(job_id: str) -> bool:
    if not is_cancel_requested(job_id):
        return False
    mark_cancelled(job_id)
    return True


def load_upload(upload_id: str) -> dict:
    response = (
        get_supabase_client()
        .table("analysis_uploads")
        .select("storage_path, original_filename, crop_code")
        .eq("id", upload_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise RuntimeError("Source upload is unavailable")
    return response.data[0]


def normalize_detections(result: Any) -> list[dict]:
    """Translate Ultralytics boxes to API-friendly, normalized coordinates."""
    if result.boxes is None:
        return []

    image_height, image_width = result.orig_shape
    names = result.names
    detections = []
    for box in result.boxes:
        x_min, y_min, x_max, y_max = [float(value) for value in box.xyxy[0].tolist()]
        class_id = int(box.cls[0].item())
        confidence = float(box.conf[0].item())
        detections.append(
            {
                "class_id": class_id,
                "class_name": str(names.get(class_id, class_id)),
                "confidence": confidence,
                "bounding_box": {
                    "x_min": x_min / image_width,
                    "y_min": y_min / image_height,
                    "x_max": x_max / image_width,
                    "y_max": y_max / image_height,
                },
            }
        )
    return detections


def fail_job(job_id: str, message: str) -> None:
    response = get_supabase_client().table("analysis_jobs").update(
        {"status": "failed", "completed_at": utc_now(), "error_message": message[:500]}
    ).eq("id", job_id).eq("status", "processing").execute()
    if not response.data:
        stop_if_cancelled(job_id)


def process_job(job: dict) -> None:
    client = get_supabase_client()
    temporary_image_path: Optional[Path] = None
    try:
        if stop_if_cancelled(job["id"]):
            return
        upload = load_upload(job["upload_id"])
        if stop_if_cancelled(job["id"]):
            return
        crop_code = job.get("crop_code") or upload.get("crop_code")
        if not crop_code:
            raise ModelConfigurationError("The image crop code is missing")
        spec = get_model_spec(crop_code)
        suffix = Path(upload["original_filename"]).suffix or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary_image:
            temporary_image.write(client.storage.from_(UPLOAD_BUCKET).download(upload["storage_path"]))
            temporary_image_path = Path(temporary_image.name)

        if stop_if_cancelled(job["id"]):
            return
        confidence_threshold = float(job["confidence_threshold"])
        result = model_cache.get(spec).predict(
            source=str(temporary_image_path),
            conf=confidence_threshold,
            verbose=False,
        )[0]
        detections = normalize_detections(result)
        if stop_if_cancelled(job["id"]):
            return
        if detections:
            client.table("analysis_detections").insert(
                [{"job_id": job["id"], **detection} for detection in detections]
            ).execute()

        if stop_if_cancelled(job["id"]):
            return

        class_counts = Counter(detection["class_name"] for detection in detections)
        client.table("analysis_jobs").update(
            {
                "status": "completed",
                "completed_at": utc_now(),
                "model_name": spec.model_name,
                "model_version": spec.model_version,
                "result_summary": {
                    "detection_count": len(detections),
                    "class_counts": dict(class_counts),
                    "max_confidence": max((item["confidence"] for item in detections), default=None),
                },
            }
        ).eq("id", job["id"]).execute()
    except ModelConfigurationError as exc:
        logger.warning("Analysis job %s failed: %s", job["id"], exc)
        fail_job(job["id"], str(exc))
    except Exception:
        logger.exception("Analysis job %s failed", job["id"])
        fail_job(job["id"], "Inference failed. Please retry the job.")
    finally:
        if temporary_image_path:
            temporary_image_path.unlink(missing_ok=True)


def process_next_job() -> bool:
    """Claim and process one queued job. Returns whether a job was claimed."""
    job = claim_next_job()
    if not job:
        return False
    process_job(job)
    return True
