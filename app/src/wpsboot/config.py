from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, read from environment variables."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://wpsboot:wpsboot@db:5432/wpsboot"
    # Used to HMAC client IPs for rate limiting. Required: no safe default exists.
    secret_key: str
    public_base_url: str = "http://localhost:8000"
    data_dir: Path = Path("/data/jobs")

    # Input limits
    max_sequences: int = 200
    max_sequence_length: int = 10_000
    max_upload_bytes: int = 2 * 1024 * 1024
    rate_limit_per_hour: int = 10

    # Job lifecycle
    job_timeout_seconds: int = 1800
    retention_days: int = 14
    worker_poll_seconds: float = 2.0
    heartbeat_seconds: int = 10
    stale_after_seconds: int = 120
    max_attempts: int = 2
    maintenance_interval_seconds: int = 60

    # Toolchain (paths inside the worker image)
    concatenate_script: Path = Path("/opt/wpsboot/tools/concatenate.pl")
    tools_packages_file: Path = Path("/opt/tools/conda-packages.json")

    # Email (disabled when smtp_host is empty)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    mail_from: str = "wpSBOOT <noreply@localhost>"

    # Admin panel (disabled when admin_password is empty)
    admin_username: str = "admin"
    admin_password: str = "admin"  # noqa: S105  # default requested; warned about loudly

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def admin_enabled(self) -> bool:
        return bool(self.admin_password)

    @property
    def admin_uses_default_password(self) -> bool:
        return self.admin_username == "admin" and self.admin_password == "admin"  # noqa: S105


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
