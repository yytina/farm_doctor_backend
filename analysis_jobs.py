import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from auth import UserResponse, get_current_user, get_supabase_client
from filename_metadata import parse_image_metadata

router = APIRouter(prefix="/api/analysis", tags=["Analysis jobs"])

UPLOAD_BUCKET = "analysis-uploads"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
DEFAULT_CONFIDENCE_THRESHOLD = float(os.getenv("DEFAULT_CONFIDENCE_THRESHOLD", "0.25"))
ALLOWED_SUFFIXES = {".csv", ".jpeg", ".jpg", ".png"}
SUPPORTED_CROP_CODES = {"01", "02"}


class UploadJobResponse(BaseModel):
    dataset_id: UUID
    upload_id: UUID
    job_id: UUID
    crop_code: str
    confidence_threshold: float
    status: str


class AnalysisJobResponse(BaseModel):
    id: UUID
    upload_id: UUID
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    crop_code: Optional[str] = None
    model_name: Optional[str] = None
    confidence_threshold: Optional[float] = None
    result_summary: Optional[dict] = None


class DetectionResponse(BaseModel):
    class_id: int
    class_name: str
    confidence: float
    bounding_box: dict[str, float]


class CancelJobResponse(BaseModel):
    job_id: UUID
    status: str


def safe_filename(filename: Optional[str]) -> str:
    """Keep only a safe file name, never a client-provided path."""
    filename = Path(filename or "upload").name.replace("\\", "_")
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return filename or "upload"


def process_analysis_job(job_id: UUID) -> None:
    """Worker hook for the forthcoming YOLO inference implementation.

    A separate worker should claim a queued row, set it to ``processing``, run
    inference, write detections, then set it to ``completed`` or ``failed``.
    This skeleton intentionally does not run inference in the web request.
    """
    raise NotImplementedError(f"Inference worker is not configured for job {job_id}")


@router.post("/uploads", response_model=UploadJobResponse, status_code=status.HTTP_201_CREATED)
async def create_upload_job(
    file: UploadFile = File(...),
    dataset_name: Optional[str] = Form(None),
    orchard_name: Optional[str] = Form(None),
    collection_date: Optional[date] = Form(None),
    crop_code: Optional[str] = Form(None),
    confidence_threshold: float = Form(DEFAULT_CONFIDENCE_THRESHOLD),
    current_user: UserResponse = Depends(get_current_user),
):
    """Store a source image/CSV and create a queued disease-analysis job."""
    filename = safe_filename(file.filename)
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only CSV, JPG, JPEG, and PNG uploads are supported",
        )
    if not 0 < confidence_threshold <= 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confidence_threshold must be greater than 0 and no greater than 1",
        )

    parsed_metadata = parse_image_metadata(filename)
    parsed_crop_code = parsed_metadata.crop_code if parsed_metadata else None
    if crop_code and parsed_crop_code and crop_code != parsed_crop_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="crop_code does not match the standardized filename metadata",
        )
    effective_crop_code = parsed_crop_code or crop_code
    if not effective_crop_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A standardized filename or crop_code is required for analysis",
        )
    if effective_crop_code not in SUPPORTED_CROP_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only crop_code 01 (pear) and 02 (apple) are supported",
        )

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The upload is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    upload_id = uuid4()
    job_id = uuid4()
    dataset_id = uuid4()
    storage_path = f"{current_user.id}/{upload_id}/{filename}"
    client = get_supabase_client()
    effective_collection_date = collection_date or (parsed_metadata.collection_date if parsed_metadata else None)
    upload_metadata = (
        parsed_metadata.to_database_fields()
        if parsed_metadata
        else {
            "crop_code": effective_crop_code,
            "metadata_parse_status": "manual",
            "metadata_parse_error": None,
        }
    )

    try:
        client.table("datasets").insert(
            {
                "id": str(dataset_id),
                "user_id": current_user.id,
                "name": dataset_name or filename,
                "orchard_name": orchard_name,
                "collection_date": effective_collection_date.isoformat() if effective_collection_date else None,
            }
        ).execute()
        client.storage.from_(UPLOAD_BUCKET).upload(
            storage_path,
            content,
            file_options={"content-type": file.content_type or "application/octet-stream"},
        )
        client.table("analysis_uploads").insert(
            {
                "id": str(upload_id),
                "dataset_id": str(dataset_id),
                "user_id": current_user.id,
                "storage_path": storage_path,
                "original_filename": filename,
                "content_type": file.content_type,
                "size_bytes": len(content),
                "orchard_name": orchard_name,
                "collection_date": effective_collection_date.isoformat() if effective_collection_date else None,
                **upload_metadata,
            }
        ).execute()
        client.table("analysis_jobs").insert(
            {
                "id": str(job_id),
                "upload_id": str(upload_id),
                "user_id": current_user.id,
                "status": "queued",
                "crop_code": effective_crop_code,
                "confidence_threshold": confidence_threshold,
            }
        ).execute()
    except Exception as exc:
        try:
            client.storage.from_(UPLOAD_BUCKET).remove([storage_path])
        except Exception:
            pass
        try:
            client.table("datasets").delete().eq("id", str(dataset_id)).execute()
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create the analysis job",
        ) from exc

    return UploadJobResponse(
        dataset_id=dataset_id,
        upload_id=upload_id,
        job_id=job_id,
        crop_code=effective_crop_code,
        confidence_threshold=confidence_threshold,
        status="queued",
    )


@router.get("/jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis_job(
    job_id: UUID,
    current_user: UserResponse = Depends(get_current_user),
):
    """Return status for one of the caller's queued or processed jobs."""
    try:
        response = (
            get_supabase_client()
            .table("analysis_jobs")
            .select(
                "id, upload_id, status, created_at, started_at, completed_at, error_message, "
                "crop_code, model_name, confidence_threshold, result_summary"
            )
            .eq("id", str(job_id))
            .eq("user_id", current_user.id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not retrieve the analysis job",
        ) from exc

    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")
    return AnalysisJobResponse(**response.data[0])


@router.get("/jobs/{job_id}/detections", response_model=list[DetectionResponse])
async def get_analysis_detections(
    job_id: UUID,
    current_user: UserResponse = Depends(get_current_user),
):
    """Return detections for one of the caller's completed analysis jobs."""
    client = get_supabase_client()
    try:
        job_response = (
            client.table("analysis_jobs")
            .select("id")
            .eq("id", str(job_id))
            .eq("user_id", current_user.id)
            .limit(1)
            .execute()
        )
        if not job_response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")
        detection_response = (
            client.table("analysis_detections")
            .select("class_id, class_name, confidence, bounding_box")
            .eq("job_id", str(job_id))
            .order("confidence", desc=True)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not retrieve analysis detections",
        ) from exc
    return detection_response.data


@router.post("/jobs/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_analysis_job(
    job_id: UUID,
    current_user: UserResponse = Depends(get_current_user),
):
    """Cancel a queued job immediately or request cancellation of active work."""
    client = get_supabase_client()
    try:
        response = (
            client.table("analysis_jobs")
            .select("id, status")
            .eq("id", str(job_id))
            .eq("user_id", current_user.id)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

        job_status = response.data[0]["status"]
        if job_status == "queued":
            updated = (
                client.table("analysis_jobs")
                .update(
                    {
                        "status": "cancelled",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("id", str(job_id))
                .eq("status", "queued")
                .execute()
            )
            if updated.data:
                return CancelJobResponse(job_id=job_id, status="cancelled")
            refreshed = (
                client.table("analysis_jobs")
                .select("status")
                .eq("id", str(job_id))
                .eq("user_id", current_user.id)
                .limit(1)
                .execute()
            )
            job_status = refreshed.data[0]["status"] if refreshed.data else "cancelled"

        if job_status == "processing":
            client.table("analysis_jobs").update({"status": "cancel_requested"}).eq("id", str(job_id)).eq(
                "status", "processing"
            ).execute()
            return CancelJobResponse(job_id=job_id, status="cancel_requested")
        return CancelJobResponse(job_id=job_id, status=job_status)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not cancel the analysis job",
        ) from exc
