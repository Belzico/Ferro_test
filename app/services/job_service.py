from app.models import Job
from app.repositories.job_repository import JobRepository


class JobService:
    def __init__(self, repository: JobRepository):
        self.repository = repository

    def create_job(self, url: str, payload: dict) -> Job:
        return self.repository.create(
            url=url,
            payload=payload,
        )

    def get_job(self, job_id: str) -> Job | None:
        return self.repository.get_by_id(job_id)
