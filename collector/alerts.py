"""Alerts: always logged; also sent to Telegram when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096


def send_alert(text: str) -> None:
    logger.warning('ALERT: %s', text)
    token, chat_id = settings.TELEGRAM['BOT_TOKEN'], settings.TELEGRAM['CHAT_ID']
    if not (token and chat_id):
        return
    try:
        httpx.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data={'chat_id': chat_id, 'text': f'stat_dash: {text}'[:TELEGRAM_LIMIT]},
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError as exc:
        # never let a failed alert break the collection; the message is in the log anyway
        logger.error('Telegram alert not sent: %s', type(exc).__name__)
