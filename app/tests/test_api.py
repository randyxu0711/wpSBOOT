import io
import uuid
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from wpsboot import services as svc
from wpsboot.config import Settings
from wpsboot.examples import EXAMPLE_FASTA
from wpsboot.models import Job, JobStatus
from wpsboot.pipeline import StepStatus

pytestmark = pytest.mark.db


def submit(client: TestClient, **fields: object) -> dict:  # type: ignore[type-arg]
    data = {"sequences": EXAMPLE_FASTA, "aligners": ["mafft", "muscle"]} | fields
    files = data.pop("files", None)
    response = client.post("/api/v1/jobs", data=data, files=files)  # type: ignore[arg-type]
    return {"status": response.status_code, "body": response.json(), "headers": response.headers}


def test_submit_creates_queued_job(client: TestClient, db: Session, settings: Settings) -> None:
    result = submit(client)
    assert result["status"] == 201, result["body"]
    body = result["body"]
    job = db.get_one(Job, uuid.UUID(body["id"]))
    assert job.status is JobStatus.QUEUED
    assert job.aligners == ["mafft", "muscle"]
    assert job.seq_count == 11
    assert [s.name for s in job.steps] == ["mafft", "muscle", "concatenate"]
    assert (settings.data_dir / body["id"] / "input.fasta").read_text().startswith(">seq0\n")
    assert result["headers"]["location"].endswith(f"/api/v1/jobs/{body['id']}")
    assert body["result_url"].endswith(f"/jobs/{body['id']}")


def test_aligners_default_to_all(client: TestClient) -> None:
    response = client.post("/api/v1/jobs", data={"sequences": EXAMPLE_FASTA})
    assert response.status_code == 201
    job = client.get(f"/api/v1/jobs/{response.json()['id']}").json()
    assert job["aligners"] == ["mafft", "muscle", "clustalw", "tcoffee"]


def test_file_upload(client: TestClient) -> None:
    result = submit(client, sequences="", files={"file": ("seqs.fasta", EXAMPLE_FASTA.encode())})
    assert result["status"] == 201


@pytest.mark.parametrize(
    ("fields", "status", "message"),
    [
        ({"aligners": ["mafft"]}, 422, "at least 2 aligners"),
        ({"aligners": ["mafft", "prank"]}, 422, "Unknown aligner(s): prank"),
        ({"sequences": ""}, 422, "Paste sequences or upload"),
        ({"sequences": ">a\nAC\n"}, 422, "At least 2 sequences"),
        ({"email": "not-an-email"}, 422, "Email address is not valid"),
        ({"files": {"file": ("x.fasta", b">a\nAC\n>b\nAC\n")}}, 422, "not both"),
        ({"sequences": "", "files": {"file": ("x.fasta", b"\xff\xfe>")}}, 422, "not a plain-text"),
    ],
)
def test_submit_validation(client: TestClient, fields: dict, status: int, message: str) -> None:  # type: ignore[type-arg]
    result = submit(client, **fields)
    assert result["status"] == status
    assert any(message in e for e in result["body"]["errors"]), result["body"]


def test_upload_size_limit(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    result = submit(client, sequences="", files={"file": ("x.fasta", EXAMPLE_FASTA.encode())})
    assert result["status"] == 413


def test_email_ignored_when_mail_disabled(client: TestClient, db: Session) -> None:
    result = submit(client, email="someone@example.org")
    assert result["status"] == 201
    assert any("not enabled" in w for w in result["body"]["warnings"])
    assert db.get_one(Job, uuid.UUID(result["body"]["id"])).email is None


def test_email_stored_when_mail_enabled(
    client: TestClient, db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    result = submit(client, email="Someone@Example.org")
    assert db.get_one(Job, uuid.UUID(result["body"]["id"])).email == "Someone@example.org"


def test_rate_limit(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_hour", 2)
    assert submit(client)["status"] == 201
    assert submit(client)["status"] == 201
    limited = submit(client)
    assert limited["status"] == 429
    assert 0 < int(limited["headers"]["retry-after"]) <= 3601


def test_get_job_and_queue_position(client: TestClient) -> None:
    first = submit(client)["body"]["id"]
    second = submit(client)["body"]["id"]
    body = client.get(f"/api/v1/jobs/{second}").json()
    assert body["status"] == "queued"
    assert body["queue_position"] == 2
    assert body["files"] == []
    assert client.get(f"/api/v1/jobs/{first}").json()["queue_position"] == 1


def test_unknown_and_malformed_job_ids(client: TestClient) -> None:
    assert client.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/v1/jobs/not-a-uuid").status_code == 422
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404
    assert client.get("/jobs/not-a-uuid").status_code == 404


def test_delete_queued_job(client: TestClient, db: Session, settings: Settings) -> None:
    job_id = submit(client)["body"]["id"]
    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204
    assert not (settings.data_dir / job_id).exists()
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404
    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 404
    assert db.get_one(Job, uuid.UUID(job_id)).status is JobStatus.DELETED


def test_delete_running_job_requests_cancel(client: TestClient, db: Session) -> None:
    job_id = uuid.UUID(submit(client)["body"]["id"])
    assert svc.claim_next_job(db, "w1") == job_id
    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204
    db.expire_all()
    job = db.get_one(Job, job_id)
    assert job.status is JobStatus.RUNNING
    assert job.cancel_action == "delete"


def _finish(db: Session, settings: Settings, job_id: str) -> None:
    job = db.get_one(Job, uuid.UUID(job_id))
    directory = settings.data_dir / job_id
    for name in ("mafft.fasta", "muscle.fasta"):
        (directory / name).write_text(EXAMPLE_FASTA)
    (directory / "superMSA.phylip").write_text("11 100\n")
    job.status = JobStatus.SUCCEEDED
    job.concat_order = ["muscle", "mafft"]
    for step in job.steps:
        step.status = StepStatus.SUCCEEDED
    db.commit()


def test_downloads(client: TestClient, db: Session, settings: Settings) -> None:
    job_id = submit(client)["body"]["id"]
    _finish(db, settings, job_id)

    body = client.get(f"/api/v1/jobs/{job_id}").json()
    assert [f["name"] for f in body["files"]] == [
        "input.fasta",
        "mafft.fasta",
        "muscle.fasta",
        "superMSA.phylip",
    ]
    assert body["concatenation_order"] == ["muscle", "mafft"]

    response = client.get(f"/api/v1/jobs/{job_id}/files/superMSA.phylip")
    assert response.status_code == 200
    assert response.text == "11 100\n"
    assert "attachment" in response.headers["content-disposition"]

    for bad in ("..%2F..%2Fetc%2Fpasswd", "clustalw.fasta", "input.txt"):
        assert client.get(f"/api/v1/jobs/{job_id}/files/{bad}").status_code == 404

    archive = client.get(f"/api/v1/jobs/{job_id}/archive")
    assert archive.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert sorted(n.split("/")[1] for n in names) == [
        "input.fasta",
        "mafft.fasta",
        "muscle.fasta",
        "superMSA.phylip",
    ]


def test_expire_hides_files(client: TestClient, db: Session, settings: Settings) -> None:
    job_id = submit(client)["body"]["id"]
    _finish(db, settings, job_id)
    job = db.get_one(Job, uuid.UUID(job_id))
    job.expires_at = svc.now() - timedelta(minutes=1)
    db.commit()
    assert svc.expire_jobs(db, settings) == 1
    db.commit()
    body = client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "expired"
    assert body["files"] == []
    assert not (settings.data_dir / job_id).exists()


def test_pages_render(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "Build Super-MSA" in home.text
    job_id = submit(client)["body"]["id"]
    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert job_id in page.text
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.head("/").status_code == 200
    assert client.head("/healthz").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200


def test_jobs_listed_newest_first_in_db(client: TestClient, db: Session) -> None:
    ids = [submit(client)["body"]["id"] for _ in range(3)]
    stored = db.scalars(select(Job.id).order_by(Job.created_at)).all()
    assert [str(i) for i in stored] == ids


@pytest.mark.parametrize("key", ["change-me", "short"])
def test_placeholder_secret_key_is_rejected(key: str, settings: Settings) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings.model_validate(settings.model_dump() | {"secret_key": key})
