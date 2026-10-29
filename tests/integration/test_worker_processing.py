from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import JobStatus
from app.repositories.job_repository import JobRepository
from app.services.retry_policy import RetryPolicy
from app.workers.scheduler import Worker


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'processing.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    yield sessions
    engine.dispose()


def create_job(factory):
    with factory() as session:
        return JobRepository(session).create(
            "https://example.com/webhook",
            {"event": "created", "nested": {"count": 3}},
        ).id


def read_job(factory, job_id):
    with factory() as session:
        job = JobRepository(session).get_by_id(job_id)
        return (
            job.status,
            job.attempts,
            job.next_retry_at,
            job.locked_until,
            job.last_error,
        )


def execute(factory, handler, at=NOW):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        worker = Worker(
            session_factory=factory,
            retry_policy=RetryPolicy(settings.retry),
            http_client=client,
            clock=lambda: at,
        )
        return worker.run_once()


def test_successful_post_completes_job(factory):
    job_id = create_job(factory)
    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(200, json={"ok": True})

    assert execute(factory, handler) is True
    status, attempts, retry, lock, error = read_job(factory, job_id)
    assert status == JobStatus.COMPLETED.value
    assert attempts == 1
    assert retry is None
    assert lock is None
    assert error is None
    assert len(received) == 1
    assert received[0].method == "POST"
    assert received[0].url.path == "/webhook"
    assert received[0].read() == b'{"event":"created","nested":{"count":3}}'


def test_http_503_schedules_retry(factory):
    job_id = create_job(factory)

    assert execute(factory, lambda _: httpx.Response(503)) is True

    status, attempts, retry, lock, error = read_job(factory, job_id)
    assert status == JobStatus.PENDING.value
    assert attempts == 1
    assert retry == NOW + timedelta(seconds=2)
    assert lock is None
    assert "503" in error


def test_permanent_http_400_fails(factory):
    job_id = create_job(factory)

    assert execute(factory, lambda _: httpx.Response(400)) is True

    status, attempts, retry, lock, error = read_job(factory, job_id)
    assert status == JobStatus.FAILED.value
    assert attempts == 1
    assert retry is None
    assert lock is None
    assert "400" in error


@pytest.mark.parametrize("code", [429, 500, 503])
def test_retryable_codes_are_retried(factory, code):
    job_id = create_job(factory)

    assert execute(factory, lambda _: httpx.Response(code)) is True

    assert read_job(factory, job_id)[0] == JobStatus.PENDING.value


def test_timeout_is_retried(factory):
    job_id = create_job(factory)

    def handler(request):
        raise httpx.ReadTimeout("Simulated timeout", request=request)

    assert execute(factory, handler) is True
    status, attempts, retry, _, error = read_job(factory, job_id)
    assert status == JobStatus.PENDING.value
    assert attempts == 1
    assert retry == NOW + timedelta(seconds=2)
    assert "ReadTimeout" in error


def test_five_failed_attempts_end_dead(factory):
    job_id = create_job(factory)
    current = NOW

    for attempt in range(1, 6):
        assert execute(
            factory,
            lambda _: httpx.Response(503),
            at=current,
        ) is True

        status, attempts, retry, _, _ = read_job(factory, job_id)
        assert attempts == attempt

        if attempt < 5:
            assert status == JobStatus.PENDING.value
            assert retry == current + timedelta(
                seconds=2 ** attempt
            )
            current = retry
        else:
            assert status == JobStatus.DEAD.value
            assert retry is None

    assert execute(factory, lambda _: httpx.Response(200), at=current) is False


def test_worker_returns_false_when_queue_empty(factory):
    assert execute(factory, lambda _: httpx.Response(200)) is False


def test_stale_worker_cannot_complete_reclaimed_job(factory):
    job_id = create_job(factory)

    with factory() as session:
        repository = JobRepository(session)
        original = repository.claim_next(NOW, 60, 5)
        original_attempt = original.attempts
        original_lease = original.locked_until

    later = NOW + timedelta(seconds=61)

    with factory() as session:
        repository = JobRepository(session)
        recovered = repository.claim_next(later, 60, 5)
        assert recovered.id == job_id
        assert recovered.attempts == 2

    with factory() as session:
        accepted = JobRepository(session).finish_attempt(
            job_id=job_id,
            attempt=original_attempt,
            lease_until=original_lease,
            now=later,
            status=JobStatus.COMPLETED.value,
        )
        assert accepted is False

    assert read_job(factory, job_id)[0] == JobStatus.RUNNING.value


def test_exhausted_expired_running_job_becomes_dead(factory):
    job_id = create_job(factory)

    with factory() as session:
        job = JobRepository(session).get_by_id(job_id)
        job.status = JobStatus.RUNNING.value
        job.attempts = 5
        job.locked_until = NOW - timedelta(seconds=1)
        session.commit()

    assert execute(factory, lambda _: httpx.Response(200)) is False
    status, attempts, retry, lock, _ = read_job(factory, job_id)
    assert status == JobStatus.DEAD.value
    assert attempts == 5
    assert retry is None
    assert lock is None


def test_custom_retryable_status_exhaustion(factory):
    from app.config import RetrySettings

    job_id = create_job(factory)

    custom = RetrySettings(
        max_attempts=1,
        initial_delay_seconds=2,
        backoff_multiplier=2,
        max_delay_seconds=60,
        retryable_status_codes=[418],
    )

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(418)
        )
    ) as client:
        worker = Worker(
            session_factory=factory,
            retry_policy=RetryPolicy(custom),
            http_client=client,
            clock=lambda: NOW,
        )
        assert worker.run_once() is True

    status, attempts, retry, lock, error = read_job(factory, job_id)
    assert status == JobStatus.DEAD.value
    assert attempts == 1
    assert retry is None
    assert lock is None
    assert "418" in error


def test_unexpected_exception_recovers_after_lease(factory):
    job_id = create_job(factory)

    def crash(request):
        raise RuntimeError("Unexpected processing failure")

    with pytest.raises(RuntimeError, match="Unexpected processing failure"):
        execute(factory, crash)

    status, attempts, retry, lock, _ = read_job(factory, job_id)
    assert status == JobStatus.RUNNING.value
    assert attempts == 1
    assert lock == NOW + timedelta(seconds=60)

    # The lease is still active: another worker cannot claim it.
    assert execute(
        factory,
        lambda _: httpx.Response(200),
        at=NOW + timedelta(seconds=59),
    ) is False

    # After expiry, another worker recovers and completes it.
    assert execute(
        factory,
        lambda _: httpx.Response(200),
        at=NOW + timedelta(seconds=61),
    ) is True

    status, attempts, retry, lock, error = read_job(factory, job_id)
    assert status == JobStatus.COMPLETED.value
    assert attempts == 2
    assert retry is None
    assert lock is None
    assert error is None
