# FERO Retry Scheduler

## 1. Implementation Overview

This implementation consists of a FastAPI REST API, durable SQLite job storage, and a separately operated polling worker. Jobs are delivered using HTTP POST, with configurable retry behavior, atomic claims, and lease-based recovery after interrupted processing.

## 2. Getting Started

**Requirements:** Python 3.12.

From the repository root, create a virtual environment and install dependencies (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a separate terminal, start the worker:

```powershell
.\.venv\Scripts\python.exe -m app.workers.scheduler
```

On Linux/macOS, use `.venv/bin/python` instead. The SQLite database and missing tables are initialized automatically; existing jobs are preserved. API documentation is available at <http://127.0.0.1:8000/docs>.

## 3. API Usage

**Create a job:** `POST /jobs/`

```json
{
  "url": "https://postman-echo.com/post",
  "payload": {"event": "order.created", "order_id": 123}
}
```

Returns `201 Created` with a generated `id` and initial status `pending`.

**Check its status:** `GET /jobs/{id}/`

```json
{
  "id": "generated-uuid",
  "status": "completed",
  "attempts": 1,
  "next_retry_at": null
}
```

Invalid job submissions return `422`; unknown IDs return `404`.

## 4. Architecture & Design Decisions

- **Separate API and worker:** submission does not depend on immediate delivery; jobs survive worker restarts.
- **Service + Repository:** application behavior and SQLAlchemy persistence have distinct responsibilities without unnecessary layers.
- **SQLite:** persistent storage with minimal operational setup for this exercise.
- **Atomic job claiming:** a database-level conditional update claims eligible jobs and increments the attempt count, preventing simultaneous claims under normal SQLite operation.
- **Expiring leases:** abandoned running jobs can be recovered; conditional finalization rejects stale worker updates. Exhausted jobs with expired leases become `dead`.
- **Independent retry policy:** deterministic, configurable decisions can be tested without real HTTP requests.
- **Stable idempotency key:** every outbound POST includes an `Idempotency-Key` header derived from the job UUID using SHA-256 (`fero-v1-` prefix). Retries and lease recovery reuse the same value, without sending the raw UUID as the header value.

A claim is committed before external HTTP I/O, avoiding long-lived database transactions. Delivery has **at-least-once semantics**, not exactly-once guarantees: a process may successfully send a request and crash before recording completion. The header enables cooperating receivers to deduplicate requests, but the receiver must enforce idempotency; the scheduler alone cannot prevent duplicate external side effects.

**Assumptions:** jobs originate from trusted internal clients; downstream targets accept HTTP POST with JSON; API and worker instances share the same SQLite database.

## 5. Retry Strategy & Configuration

The lifecycle uses `pending`, `running`, `completed`, `failed`, and `dead`.

| Result | Behavior |
| --- | --- |
| HTTP 2xx | `completed` |
| HTTP 429, 500, 503 (by default) | Scheduled retry, or `dead` when exhausted |
| Network/transport failure or timeout | Scheduled retry, or `dead` when exhausted |
| Other non-2xx response | `failed` |

Settings are defined in `app/appsettings.json`:

| Setting | Default |
| --- | --- |
| Maximum attempts | 5 |
| Initial delay / multiplier / maximum delay | 2 s / 2 / 60 s |
| Retryable HTTP statuses | 429, 500, 503 |
| Poll interval / HTTP timeout / lease | 1 s / 10 s / 60 s |

Default backoff delays after attempts 1–4 are **2, 4, 8, and 16 seconds**. The fifth retryable failure ends in `dead`. Actual execution can occur later than the retry deadline, depending on polling and worker availability.

## 6. Testing & Trade-offs

Development followed **TDD (RED → GREEN → REFACTOR)**, starting with retry-policy tests and extending to persistence, API validation, atomic claims, concurrent workers, lease recovery, HTTP processing, and stable idempotency-key propagation across retries.

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The completed implementation passed **136 Pytest tests** locally. Worker tests use controlled HTTP responses and isolated databases, keeping automated checks deterministic.

The Postman collection (`tests/postman/FERO_Jobs_API.postman_collection.json`) contains **19 requests** covering job creation, status polling, API validation, and delivery outcomes. One verified collection run completed with **324 passing assertions, zero failures, and zero errors**. Run it with the API and worker active and select **No Environment**.

We also verified **real end-to-end HTTP delivery** against public test services, rather than relying only on mocks:

- **Postman Echo** (`https://postman-echo.com/post`): HTTP 200 -> `completed` after one attempt.
- **HTTPBin** (`https://httpbin.org`): HTTP 200, 400, 429, 500, and 503 scenarios tested through Postman; HTTP 400 -> `failed` after one attempt, while retryable 429/500/503 responses -> `dead` after five attempts when failures persist. The HTTP 400 and 503 cases were also checked manually through the worker logs.

**Trade-offs / future improvements:** SQLite has limited write concurrency compared with PostgreSQL; exactly-once delivery is not provided and downstream deduplication requires receiver support. A production service would also need authentication, outbound URL/SSRF protections, migrations, observability, and potentially retry jitter, `Retry-After` support, and lease renewal for long-running requests.
