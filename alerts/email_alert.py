"""
alerts/email_alert.py — SMTP email alert sender.

Sends both simple text alerts and full HTML session summaries via email.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from loguru import logger


def send_email_alert(
    subject: str,
    body: str,
    html_body: Optional[str] = None,
) -> bool:
    """
    Send an email alert to the configured ALERT_EMAIL address.
    Returns True on success, False on failure.
    """
    from config import settings

    if not settings.has_email_alerts():
        logger.warning("Email alerts not configured — skipping")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[JobAgent] {subject}"
    msg["From"] = settings.smtp_user
    msg["To"] = settings.alert_email

    msg.attach(MIMEText(body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_user, settings.alert_email, msg.as_string())
        logger.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def format_session_summary(stats: dict) -> tuple[str, str]:
    """
    Format session stats as (plain_text, html_text) for email body.
    """
    applied = stats.get("total_applied", 0)
    skipped = stats.get("total_skipped", 0)
    failed = stats.get("total_failed", 0)
    blocked = stats.get("sites_blocked", [])
    alerts_sent = stats.get("alerts_sent", [])

    plain = (
        f"Job Agent Session Summary\n"
        f"{'='*35}\n"
        f"Applied:  {applied}\n"
        f"Skipped:  {skipped}\n"
        f"Failed:   {failed}\n"
        f"Total:    {applied + skipped + failed}\n"
    )
    if blocked:
        plain += f"\nBlocked sites: {', '.join(blocked)}"
    if alerts_sent:
        plain += f"\nAlerts fired: {len(alerts_sent)}"

    html = f"""
    <html><body style="font-family: Arial, sans-serif;">
    <h2>🤖 Job Agent Session Summary</h2>
    <table border="1" cellpadding="8" style="border-collapse:collapse;">
      <tr><td><b>✅ Applied</b></td><td>{applied}</td></tr>
      <tr><td><b>⏭️ Skipped</b></td><td>{skipped}</td></tr>
      <tr><td><b>❌ Failed</b></td><td>{failed}</td></tr>
      <tr><td><b>📊 Total</b></td><td>{applied + skipped + failed}</td></tr>
    </table>
    {"<p><b>🚫 Blocked sites:</b> " + ", ".join(blocked) + "</p>" if blocked else ""}
    {"<p><b>🚨 Alerts fired:</b> " + str(len(alerts_sent)) + "</p>" if alerts_sent else ""}
    </body></html>
    """
    return plain, html
