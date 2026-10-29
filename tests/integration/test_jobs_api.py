import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import create_app
from app.models import Job


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "api_test.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    Base.metadata.create_all(engine)

    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db():
        with testing_session() as session:
            yield session

    app = create_app(initialize_database=False)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client, testing_session
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_create_job_returns_201_and_pending(client):
    api, _ = client

    response = api.post(
        "/jobs/",
        json={
            "url": "https://example.com/webhook",
            "payload": {"order_id": 123},
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert isinstance(response.json()["id"], str)
    assert set(response.json()) == {"id", "status"}


def test_get_job_returns_persisted_data(client):
    api, _ = client

    created = api.post(
        "/jobs/",
        json={
            "url": "https://example.com/webhook",
            "payload": {"event": "created"},
        },
    )

    assert created.status_code == 201
    job_id = created.json()["id"]

    response = api.get(f"/jobs/{job_id}/")

    assert response.status_code == 200
    assert response.json() == {
        "id": job_id,
        "status": "pending",
        "attempts": 0,
        "next_retry_at": None,
    }


def test_unknown_job_returns_404(client):
    api, _ = client
    response = api.get("/jobs/nonexistent-job/")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "url",
    ["invalid", "ftp://example.com/file", "javascript:alert(1)"],
)
def test_invalid_urls_return_422(client, url):
    api, _ = client

    response = api.post(
        "/jobs/",
        json={"url": url, "payload": {"event": "test"}},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"payload": {"event": "test"}},
        {"url": "https://example.com/webhook"},
        {"url": "https://example.com/webhook", "payload": [1, 2]},
        {"url": "https://example.com/webhook", "payload": "invalid"},
    ],
)
def test_invalid_request_bodies_return_422(client, body):
    api, _ = client
    assert api.post("/jobs/", json=body).status_code == 422


def test_multiple_jobs_have_different_ids(client):
    api, _ = client

    first = api.post(
        "/jobs/",
        json={"url": "https://example.com/first", "payload": {"id": 1}},
    )
    second = api.post(
        "/jobs/",
        json={"url": "https://example.com/second", "payload": {"id": 2}},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_nested_payload_is_persisted(client):
    api, session_factory = client

    payload = {
        "event": "payment",
        "data": {"amount": 250, "items": [1, 2, 3]},
    }

    response = api.post(
        "/jobs/",
        json={"url": "https://example.com/webhook", "payload": payload},
    )

    assert response.status_code == 201

    with session_factory() as session:
        saved = session.get(Job, response.json()["id"])
        assert saved is not None
        assert saved.payload == payload
