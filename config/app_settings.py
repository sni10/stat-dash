"""Environment-specific values: env vars, or .env for runs on the host. Validated once at startup."""
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')

    django_secret_key: SecretStr
    django_debug: bool = False
    django_allowed_hosts: str = 'localhost,127.0.0.1'  # comma-separated

    db_name: str
    db_user: str
    db_password: SecretStr
    db_host: str = '127.0.0.1'
    db_port: int = 5435

    lun_base_url: str = 'https://lun.ua/stat/api/data/'
    lun_pause_min: float = 2.0  # seconds between requests to LUN
    lun_pause_max: float = 5.0

    # Alerts go to Telegram when both are set; otherwise they are only logged
    telegram_bot_token: SecretStr = SecretStr('')
    telegram_chat_id: str = ''

    dashboard_default_city: str = 'odesa'  # slug shown when the URL names no city

    backup_dir: str = ''  # `collect_lun --backup` writes pg_dump files here; empty -> backups off
    backup_keep: int = 8


def load_settings(env_file: Path) -> AppSettings:
    return AppSettings(_env_file=env_file if env_file.exists() else None)
