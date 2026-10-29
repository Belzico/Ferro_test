import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from app.config import WorkerSettings, settings
from app.database import SessionLocal, init_db
from app.models import JobStatus
from app.repositories.job_repository import JobRepository
from app.services.retry_policy import (
    RetryPolicy,
    TransportFailure,
)


logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Worker:
    def __init__(
        self,
        session_factory,
        retry_policy: RetryPolicy,
        http_client: httpx.Client,
        clock: Callable[[], datetime] = utc_now,
        worker_settings: WorkerSettings | None = None,
    ):
        self.session_factory = session_factory
        self.retry_policy = retry_policy
        self.http_client = http_client
        self.clock = clock
        self.worker_settings = worker_settings or settings.worker

    def run_once(self) -> bool:
        now = self.clock()

        # Database transactions finish before external HTTP calls.
        with self.session_factory() as session:
            repository = JobRepository(session)

            repository.expire_exhausted(
                now=now,
                max_attempts=self.retry_policy.max_attempts,
            )

            job = repository.claim_next(
                now=now,
                lease_duration_seconds=(
                    self.worker_settings.lease_duration_seconds
                ),
                max_attempts=self.retry_policy.max_attempts,
            )

            if job is None:
                return False

            job_id = job.id
            url = job.url
            payload = job.payload
            attempt = job.attempts
            lease_until = job.locked_until

        final_status = JobStatus.COMPLETED.value
        next_retry_at = None
        last_error = None

        try:
            response = self.http_client.post(
                url,
                json=payload,
                timeout=self.worker_settings.http_timeout_seconds,
            )

            if not 200 <= response.status_code < 300:
                last_error = f"HTTP {response.status_code}"

                decision = self.retry_policy.should_retry(
                    attempt=attempt,
                    status_code=response.status_code,
                )

                if decision.should_retry:
                    final_status = JobStatus.PENDING.value
                    next_retry_at = self.clock() + timedelta(
                        seconds=decision.next_backoff_seconds
                    )
                elif response.status_code in self.retry_policy.retryable_status_codes:
                    final_status = JobStatus.DEAD.value
                else:
                    final_status = JobStatus.FAILED.value

        except httpx.RequestError as exc:
            last_error = type(exc).__name__

            failure = (
                TransportFailure.TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else TransportFailure.CONNECTION_ERROR
            )

            decision = self.retry_policy.should_retry(
                attempt=attempt,
                transport_failure=failure,
            )

            if decision.should_retry:
                final_status = JobStatus.PENDING.value
                next_retry_at = self.clock() + timedelta(
                    seconds=decision.next_backoff_seconds
                )
            else:
                final_status = JobStatus.DEAD.value

        with self.session_factory() as session:
            accepted = JobRepository(session).finish_attempt(
                job_id=job_id,
                attempt=attempt,
                lease_until=lease_until,
                now=self.clock(),
                status=final_status,
                next_retry_at=next_retry_at,
                last_error=last_error,
            )

        if not accepted:
            logger.warning(
                "Job %s attempt %s lost its lease; result discarded",
                job_id,
                attempt,
            )
        else:
            logger.info(
                "Job %s attempt %s -> %s",
                job_id,
                attempt,
                final_status,
            )

        return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    init_db()

    logger.info(
        "FERO worker started. Poll interval: %ss",
        settings.worker.poll_interval_seconds,
    )

    with httpx.Client() as client:
        worker = Worker(
            session_factory=SessionLocal,
            retry_policy=RetryPolicy(settings.retry),
            http_client=client,
        )

        try:
            while True:
                try:
                    processed = worker.run_once()
                except Exception:
                    logger.exception("Worker iteration failed")
                    processed = False

                if not processed:
                    time.sleep(settings.worker.poll_interval_seconds)

        except KeyboardInterrupt:
            logger.info("FERO worker stopped")


if __name__ == "__main__":
    main()
