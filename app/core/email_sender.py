"""Send verification emails. If SMTP not configured, verification link is logged only."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, username: str, verification_url: str) -> bool:
    """Send verification email. Returns True if sent, False otherwise (e.g. SMTP not configured)."""
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password]):
        logger.info("SMTP not configured; verification link (send to %s): %s", to_email, verification_url)
        return False
    from_addr = settings.email_from or settings.smtp_user
    subject = "Verify your CareFlow account"
    body = f"Hi {username},\n\nClick the link below to verify your email and activate your CareFlow account:\n\n{verification_url}\n\nIf you didn't sign up, you can ignore this email.\n\n— CareFlow"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(from_addr, [to_email], msg.as_string())
        logger.info("Verification email sent to %s", to_email)
        return True
    except Exception as e:
        logger.warning("Failed to send verification email to %s: %s", to_email, e)
        return False
