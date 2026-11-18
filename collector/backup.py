"""pg_dump after a collection (spec: after every successful collect_lun, keep 8 copies)."""
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

PREFIX = 'stat_dash_'


def backup(directory: str | Path, keep: int) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    db = connection.settings_dict
    target = directory / f'{PREFIX}{timezone.localtime():%Y%m%d-%H%M%S}.dump'
    subprocess.run(
        ['pg_dump', '--format=custom', '--no-owner', f'--file={target}',
         f'--host={db["HOST"]}', f'--port={db["PORT"]}', f'--username={db["USER"]}', db['NAME']],
        env={**os.environ, 'PGPASSWORD': db['PASSWORD']},
        check=True,
        capture_output=True,
    )
    dumps = sorted(directory.glob(f'{PREFIX}*.dump'))
    for old in dumps[:-keep] if keep > 0 else []:
        old.unlink()
    return target


def backup_from_settings() -> Path | None:
    if not settings.BACKUP['DIR']:
        return None
    return backup(settings.BACKUP['DIR'], settings.BACKUP['KEEP'])
