import os
import re
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from auth import UserResponse, get_current_user, get_supabase_client

router = APIRouter(prefix="/api/analysis", tags=["Analysis jobs"])

UPLOAD_BUCKET = "analysis-uploads"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
ALLOWED_SUFFIXES = {".csv", ".jpeg", ".jpg", ".png"}


class UploadJobResponse(BaseModel):
    dataset_id: UUID
    upload_id: UUID
    job_id: UUID
    status: str


class AnalysisJobResponse(BaseModel):
    id: UUID
    upload_id: UUID
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


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
    current_user: UserResponse = Depends(get_current_user),
):
    """Store a source image/CSV and create a queued disease-analysis job."""
    filename = safe_filename(file.filename)
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only CSV, JPG, JPEG, and PNG uploads are supported",
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

    try:
        client.table("datasets").insert(
            {
                "id": str(dataset_id),
                "user_id": current_user.id,
                "name": dataset_name or filename,
                "orchard_name": orchard_name,
                "collection_date": collection_date.isoformat() if collection_date else None,
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
                "collection_date": collection_date.isoformat() if collection_date else None,
            }
        ).execute()
        client.table("analysis_jobs").insert(
            {"id": str(job_id), "upload_id": str(upload_id), "user_id": current_user.id, "status": "queued"}
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

    return UploadJobResponse(dataset_id=dataset_id, upload_id=upload_id, job_id=job_id, status="queued")


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
            .select("id, upload_id, status, created_at, started_at, completed_at, error_message")
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
