import logging
import smtplib
import ssl
import time
from email.message import EmailMessage

from wpsboot.config import Settings
from wpsboot.models import Job, JobStatus

log = logging.getLogger(__name__)

RETRY_DELAYS_SECONDS = (2, 10)


def send_mail(settings: Settings, *, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()
    smtp: smtplib.SMTP
    if settings.smtp_security == "ssl":
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=30)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def job_finished_message(settings: Settings, job: Job) -> tuple[str, str]:
    url = f"{settings.public_base_url.rstrip('/')}/jobs/{job.id}"
    if job.status is JobStatus.SUCCEEDED:
        subject = "Your wpSBOOT Super-MSA is ready"
        outcome = "Your wpSBOOT job has finished successfully."
    else:
        subject = "Your wpSBOOT job failed"
        outcome = f"Unfortunately your wpSBOOT job failed: {job.error_message or 'unknown error'}"
    body = (
        f"Hello,\n\n{outcome}\n\n"
        f"View and download the results:\n{url}\n\n"
        f"Results are kept until {job.expires_at:%Y-%m-%d %H:%M} UTC and then deleted.\n\n"
        "This is an automated message; please do not reply.\n\n"
        "wpSBOOT - Chang Lab, National Chengchi University\n"
    )
    return subject, body


def notify_job_finished(settings: Settings, job: Job) -> bool:
    """Send the completion email, retrying transient failures. Returns True on success."""
    if not settings.mail_enabled or not job.email:
        return False
    subject, body = job_finished_message(settings, job)
    for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None), start=1):
        try:
            send_mail(settings, to=job.email, subject=subject, body=body)
        except (OSError, smtplib.SMTPException):
            log.exception("sending notification for job %s failed (attempt %d)", job.id, attempt)
            if delay is None:
                return False
            time.sleep(delay)
        else:
            log.info("notification sent for job %s", job.id)
            return True
    return False
