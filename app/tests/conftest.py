import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Settings are read from the environment; set safe test values before anything imports them.
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="wpsboot-test-data-")
os.environ["SMTP_HOST"] = ""
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin"
os.environ["CONCATENATE_SCRIPT"] = str(Path(__file__).parent / "fakes" / "concatenate.pl")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from wpsboot.config import Settings, get_settings
from wpsboot.db import get_sessionmaker
from wpsboot.main import create_app

FAKES = Path(__file__).parent / "fakes"
HAS_DB = bool(os.environ.get("DATABASE_URL"))
HAS_TOOLS = shutil.which("mafft") is not None and shutil.which("t_coffee") is not None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "db" in item.keywords and not HAS_DB:
            item.add_marker(pytest.mark.skip(reason="DATABASE_URL not set"))
        if "tools" in item.keywords and not HAS_TOOLS:
            item.add_marker(pytest.mark.skip(reason="aligners not installed"))


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    """Create a fresh test database and run the real migrations against it."""
    from alembic import command
    from alembic.config import Config

    url = os.environ["DATABASE_URL"]
    base, name = url.rsplit("/", 1)
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield url


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def db(migrated_db: str, settings: Settings) -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
        with get_sessionmaker()() as cleanup:
            cleanup.execute(text("TRUNCATE jobs, job_steps"))
            cleanup.commit()
        for child in settings.data_dir.iterdir():
            shutil.rmtree(child, ignore_errors=True)


@pytest.fixture
def client(db: Session, settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
def fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put fake aligners first on PATH. Behaviour per tool via FAKE_<NAME>=ok|fail|empty|hang."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for name in ("mafft", "muscle", "clustalw", "t_coffee"):
        exe = bin_dir / name
        shutil.copyfile(FAKES / "aligner.sh", exe)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv(f"FAKE_{name.upper()}", "ok")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir
