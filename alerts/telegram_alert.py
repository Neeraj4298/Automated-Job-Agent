"""
alerts/telegram_alert.py — Telegram bot real-time alert sender.

Used for immediate notification of critical events:
  CAPTCHA detected, MFA triggered, sensitive fields found, site blocked.
"""

from loguru import logger


async def send_telegram_alert(message: str) -> bool:
    """
    Send an alert via Telegram bot API.
    Returns True on success, False if not configured or failed.
    """
    from config import settings

    if not settings.has_telegram():
        logger.debug("Telegram not configured — skipping alert")
        return False

    try:
        from telegram import Bot
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=f"🤖 *JobAgent Alert*\n\n{message}",
            parse_mode="Markdown",
        )
        logger.info("Telegram alert sent.")
        return True
    except Exception as e:
        logger.error(f"Telegram alert failed: {type(e).__name__}")
        return False
