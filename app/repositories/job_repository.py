from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
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

    def claim_next(
        self,
        now: datetime,
        lease_duration_seconds: int,
        max_attempts: int = 5,
    ) -> Job | None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        if lease_duration_seconds <= 0:
            raise ValueError("lease_duration_seconds must be positive")

        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        now = now.astimezone(timezone.utc)
        locked_until = now + timedelta(seconds=lease_duration_seconds)

        pending_and_due = and_(
            Job.status == JobStatus.PENDING.value,
            or_(
                Job.next_retry_at.is_(None),
                Job.next_retry_at <= now,
            ),
        )

        running_with_expired_lease = and_(
            Job.status == JobStatus.RUNNING.value,
            Job.locked_until.is_not(None),
            Job.locked_until <= now,
        )

        eligible_job_id = (
            select(Job.id)
            .where(
                Job.attempts < max_attempts,
                or_(
                    pending_and_due,
                    running_with_expired_lease,
                ),
            )
            .order_by(
                Job.created_at.asc(),
                Job.id.asc(),
            )
            .limit(1)
            .scalar_subquery()
        )

        statement = (
            update(Job)
            .where(Job.id == eligible_job_id)
            .values(
                status=JobStatus.RUNNING.value,
                attempts=Job.attempts + 1,
                locked_until=locked_until,
                next_retry_at=None,
            )
            .returning(Job)
            .execution_options(
                synchronize_session=False,
                populate_existing=True,
            )
        )

        try:
            claimed = self.session.execute(statement).scalar_one_or_none()
            self.session.commit()

            if claimed is not None:
                self.session.refresh(claimed)

            return claimed
        except Exception:
            self.session.rollback()
            raise


    def finish_attempt(
        self,
        job_id: str,
        attempt: int,
        lease_until: datetime,
        now: datetime,
        status: str,
        next_retry_at: datetime | None = None,
        last_error: str | None = None,
    ) -> bool:
        """Finish only the currently owned, unexpired attempt."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        if status not in {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.DEAD.value,
            JobStatus.PENDING.value,
        }:
            raise ValueError("Invalid final status")

        if status == JobStatus.PENDING.value:
            if next_retry_at is None:
                raise ValueError("Pending retry requires next_retry_at")
        elif next_retry_at is not None:
            raise ValueError("Only pending retries may have next_retry_at")

        if lease_until.tzinfo is None or lease_until.utcoffset() is None:
            raise ValueError("lease_until must be timezone-aware")

        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.attempts == attempt,
                Job.locked_until == lease_until,
                Job.locked_until > now,
            )
            .values(
                status=status,
                locked_until=None,
                next_retry_at=next_retry_at,
                last_error=last_error,
            )
            .execution_options(synchronize_session=False)
        )

        try:
            result = self.session.execute(statement)
            self.session.commit()
            self.session.expire_all()
            return result.rowcount == 1
        except Exception:
            self.session.rollback()
            raise

    def expire_exhausted(
        self,
        now: datetime,
        max_attempts: int,
    ) -> int:
        """Mark crashed jobs dead once their last lease expires."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        statement = (
            update(Job)
            .where(
                Job.status == JobStatus.RUNNING.value,
                Job.attempts >= max_attempts,
                Job.locked_until.is_not(None),
                Job.locked_until <= now,
            )
            .values(
                status=JobStatus.DEAD.value,
                locked_until=None,
                next_retry_at=None,
                last_error="Worker lease expired after maximum attempts",
            )
            .execution_options(synchronize_session=False)
        )

        try:
            result = self.session.execute(statement)
            self.session.commit()
            self.session.expire_all()
            return result.rowcount
        except Exception:
            self.session.rollback()
            raise
