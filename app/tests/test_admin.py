import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from wpsboot import services as svc
from wpsboot.config import Settings
from wpsboot.examples import EXAMPLE_FASTA
from wpsboot.main import create_app
from wpsboot.models import Job, JobStatus

pytestmark = pytest.mark.db

AUTH = ("admin", "admin")
SAME_ORIGIN = {"Origin": "http://testserver"}


def new_job(client: TestClient) -> str:
    response = client.post("/api/v1/jobs", data={"sequences": EXAMPLE_FASTA})
    assert response.status_code == 201
    job_id: str = response.json()["id"]
    return job_id


def test_requires_credentials(client: TestClient) -> None:
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    page = client.get("/admin", auth=AUTH)
    assert page.status_code == 200
    assert "default admin/admin password" in page.text


def test_disabled_without_password(db: Session, settings: Settings) -> None:
    disabled = settings.model_copy(update={"admin_password": ""})
    with TestClient(create_app(disabled)) as client:
        assert client.get("/admin", auth=AUTH).status_code == 404


def test_list_filter_and_detail(client: TestClient) -> None:
    job_id = new_job(client)
    listing = client.get("/admin", params={"status": "queued", "q": job_id[:6]}, auth=AUTH)
    assert job_id[:8] in listing.text
    empty = client.get("/admin", params={"status": "failed"}, auth=AUTH)
    assert "No jobs match" in empty.text
    detail = client.get(f"/admin/jobs/{job_id}", auth=AUTH)
    assert detail.status_code == 200
    assert "Cancel job" in detail.text


def test_actions_need_same_origin(client: TestClient) -> None:
    job_id = new_job(client)
    response = client.post(f"/admin/jobs/{job_id}/cancel", auth=AUTH)
    assert response.status_code == 403
    evil = client.post(
        f"/admin/jobs/{job_id}/cancel", auth=AUTH, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403


def test_cancel_then_requeue(client: TestClient, db: Session) -> None:
    job_id = new_job(client)
    response = client.post(
        f"/admin/jobs/{job_id}/cancel", auth=AUTH, headers=SAME_ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303
    job = db.get_one(Job, uuid.UUID(job_id))
    assert job.status is JobStatus.FAILED
    assert job.error_message == "Cancelled by an administrator."

    again = client.post(
        f"/admin/jobs/{job_id}/cancel", auth=AUTH, headers=SAME_ORIGIN, follow_redirects=False
    )
    assert again.status_code == 409

    requeued = client.post(
        f"/admin/jobs/{job_id}/requeue", auth=AUTH, headers=SAME_ORIGIN, follow_redirects=False
    )
    assert requeued.status_code == 303
    db.expire_all()
    assert db.get_one(Job, uuid.UUID(job_id)).status is JobStatus.QUEUED


def test_delete(client: TestClient, db: Session, settings: Settings) -> None:
    job_id = new_job(client)
    response = client.post(
        f"/admin/jobs/{job_id}/delete", auth=AUTH, headers=SAME_ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303
    assert db.get_one(Job, uuid.UUID(job_id)).status is JobStatus.DELETED
    assert not (settings.data_dir / job_id).exists()
    # Deleted jobs stay visible to admins for statistics.
    assert client.get(f"/admin/jobs/{job_id}", auth=AUTH).status_code == 200


def test_stats(client: TestClient, db: Session) -> None:
    new_job(client)
    stats = svc.stats(db)
    assert stats.created_24h == 1
    assert stats.by_status == {"queued": 1}
