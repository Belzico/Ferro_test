from sqlalchemy.orm import Session

from app.models import Job, JobStatus


class JobRepository:

    def __init__(self, session: Session):
        self.session = session

    def create(self, url: str, payload: dict) -> Job:
        job = Job(
            url=url,
            payload=payload,
            status=JobStatus.PENDING.value,
            attempts=0,
        )

        self.session.add(job)

        try:
            self.session.commit()
            self.session.refresh(job)
        except Exception:
            self.session.rollback()
            raise

        return job

    def get_by_id(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)
