from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Job, JobStatus
from app.repositories.job_repository import JobRepository


@pytest.fixture
def session_factory(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'worker_test.db').as_posix()}"

    engine = create_engine(
        database_url,
        connect_args={
            "check_same_thread": False,
            "timeout": 10,
        },
    )
    Base.metadata.create_all(engine)

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    yield factory

    engine.dispose()


def test_claim_pending_job(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        created = repository.create(
            url="https://example.com/webhook",
            payload={"event": "created"},
        )

        claimed = repository.claim_next(
            now=now,
            lease_duration_seconds=60,
        )

        assert claimed is not None
        assert claimed.id == created.id
        assert claimed.status == JobStatus.RUNNING.value
        assert claimed.attempts == 1
        assert claimed.locked_until == now + timedelta(seconds=60)


def test_claim_is_persisted(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        created = repository.create(
            url="https://example.com/webhook",
            payload={},
        )
        job_id = created.id
        repository.claim_next(now=now, lease_duration_seconds=60)

    with session_factory() as session:
        stored = session.get(Job, job_id)

        assert stored.status == JobStatus.RUNNING.value
        assert stored.attempts == 1
        assert stored.locked_until == now + timedelta(seconds=60)


def test_future_retry_is_not_claimed(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        job = repository.create(
            url="https://example.com/webhook",
            payload={},
        )
        job.next_retry_at = now + timedelta(seconds=30)
        session.commit()

        claimed = repository.claim_next(now=now, lease_duration_seconds=60)

        assert claimed is None
        session.refresh(job)
        assert job.status == JobStatus.PENDING.value
        assert job.attempts == 0


def test_due_retry_can_be_claimed(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        job = repository.create(
            url="https://example.com/webhook",
            payload={},
        )
        job.attempts = 1
        job.next_retry_at = now - timedelta(seconds=1)
        session.commit()

        claimed = repository.claim_next(now=now, lease_duration_seconds=60)

        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.attempts == 2
        assert claimed.next_retry_at is None


def test_two_workers_cannot_claim_same_job(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        created = repository.create(
            url="https://example.com/webhook",
            payload={"concurrency": True},
        )
        job_id = created.id

    barrier = Barrier(2)

    def worker():
        with session_factory() as session:
            repository = JobRepository(session)
            barrier.wait(timeout=10)
            result = repository.claim_next(
                now=now,
                lease_duration_seconds=60,
            )
            return result.id if result is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]

    assert results.count(job_id) == 1
    assert results.count(None) == 1

    with session_factory() as session:
        stored = session.get(Job, job_id)
        assert stored.status == JobStatus.RUNNING.value
        assert stored.attempts == 1

def test_expired_running_job_can_be_reclaimed(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        job = repository.create(
            url="https://example.com/webhook",
            payload={"event": "recovery"},
        )
        job_id = job.id
        job.status = JobStatus.RUNNING.value
        job.attempts = 1
        job.locked_until = now - timedelta(seconds=1)
        session.commit()

        claimed = repository.claim_next(
            now=now,
            lease_duration_seconds=60,
            max_attempts=5,
        )

        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.status == JobStatus.RUNNING.value
        assert claimed.attempts == 2
        assert claimed.locked_until == now + timedelta(seconds=60)


def test_active_lease_cannot_be_reclaimed(session_factory):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        job = repository.create(
            url="https://example.com/webhook",
            payload={},
        )
        job.status = JobStatus.RUNNING.value
        job.attempts = 1
        job.locked_until = now + timedelta(seconds=30)
        session.commit()

        claimed = repository.claim_next(
            now=now,
            lease_duration_seconds=60,
            max_attempts=5,
        )

        assert claimed is None
        session.refresh(job)
        assert job.attempts == 1
        assert job.status == JobStatus.RUNNING.value


@pytest.mark.parametrize(
    "terminal_status",
    [
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.DEAD.value,
    ],
)
def test_terminal_job_cannot_be_reclaimed(
    session_factory,
    terminal_status,
):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        job = repository.create(
            url="https://example.com/webhook",
            payload={},
        )
        job.status = terminal_status
        job.attempts = 1
        session.commit()

        claimed = repository.claim_next(
            now=now,
            lease_duration_seconds=60,
            max_attempts=5,
        )

        assert claimed is None
        session.refresh(job)
        assert job.status == terminal_status
        assert job.attempts == 1


@pytest.mark.parametrize(
    "initial_status",
    [
        JobStatus.PENDING.value,
        JobStatus.RUNNING.value,
    ],
)
def test_exhausted_job_cannot_be_reclaimed(
    session_factory,
    initial_status,
):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        repository = JobRepository(session)
        job = repository.create(
            url="https://example.com/webhook",
            payload={},
        )
        job.status = initial_status
        job.attempts = 5
        job.locked_until = now - timedelta(seconds=1)
        session.commit()

        claimed = repository.claim_next(
            now=now,
            lease_duration_seconds=60,
            max_attempts=5,
        )

        assert claimed is None
        session.refresh(job)
        assert job.attempts == 5
