
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Job, JobStatus
from app.repositories.job_repository import JobRepository


@pytest.fixture
def session(tmp_path):
    database_path = tmp_path / "test_jobs.db"

    engine = create_engine(
        f"sqlite:///{database_path}"
    )

    Base.metadata.create_all(engine)

    with Session(engine) as db:
        yield db

    engine.dispose()


def test_create_and_retrieve_job(session):
    repository = JobRepository(session)

    job = repository.create(
        url="https://example.com/webhook",
        payload={"order_id": 123}
    )

    saved = repository.get_by_id(job.id)

    assert saved is not None
    assert saved.id == job.id
    assert saved.url == "https://example.com/webhook"
    assert saved.payload == {"order_id": 123}


def test_new_job_has_correct_defaults(session):
    repository = JobRepository(session)

    job = repository.create(
        url="https://example.com/webhook",
        payload={"message": "hello"}
    )

    assert job.status == JobStatus.PENDING
    assert job.attempts == 0
    assert job.next_retry_at is None
    assert job.locked_until is None
    assert job.last_error is None
    assert job.created_at is not None
    assert job.updated_at is not None


def test_job_persists_across_sessions(session):
    repository = JobRepository(session)

    job = repository.create(
        url="https://example.com/webhook",
        payload={"event": "created"}
    )

    job_id = job.id
    session.expunge_all()

    with Session(session.get_bind()) as new_session:
        new_repository = JobRepository(new_session)
        saved = new_repository.get_by_id(job_id)

        assert saved is not None
        assert saved.payload == {"event": "created"}


def test_get_unknown_job_returns_none(session):
    repository = JobRepository(session)

    result = repository.get_by_id("nonexistent-job")

    assert result is None


def test_jobs_have_unique_ids(session):
    repository = JobRepository(session)

    first = repository.create(
        url="https://example.com/first",
        payload={"id": 1}
    )

    second = repository.create(
        url="https://example.com/second",
        payload={"id": 2}
    )

    assert first.id != second.id

def test_dates_preserve_utc_timezone_after_database_reload(session):
    from datetime import datetime, timezone

    repository = JobRepository(session)
    job = repository.create(
        url="https://example.com/webhook",
        payload={"event": "utc_test"},
    )

    job_id = job.id
    session.expunge_all()

    with Session(session.get_bind()) as new_session:
        saved = JobRepository(new_session).get_by_id(job_id)

        assert saved.created_at.tzinfo is not None
        assert saved.updated_at.tzinfo is not None
        assert saved.created_at.utcoffset().total_seconds() == 0
        assert saved.updated_at.utcoffset().total_seconds() == 0

        now = datetime.now(timezone.utc)
        assert saved.created_at <= now
