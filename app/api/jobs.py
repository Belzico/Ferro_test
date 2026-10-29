from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.job_repository import JobRepository
from app.schemas import JobCreate, JobCreated, JobDetails
from app.services.job_service import JobService


router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_service(db: Session = Depends(get_db)) -> JobService:
    return JobService(JobRepository(db))


@router.post("/", status_code=201, response_model=JobCreated)
def create_job(
    request: JobCreate,
    service: JobService = Depends(get_job_service),
):
    job = service.create_job(
        url=str(request.url),
        payload=request.payload,
    )

    return JobCreated(id=job.id, status=job.status)


@router.get("/{job_id}/", response_model=JobDetails)
def get_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
):
    job = service.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetails(
        id=job.id,
        status=job.status,
        attempts=job.attempts,
        next_retry_at=job.next_retry_at,
    )
