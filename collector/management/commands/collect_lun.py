import datetime as dt
import subprocess

from django.core.management.base import BaseCommand, CommandError

from collector.alerts import send_alert
from collector.backup import backup_from_settings
from collector.models import City, CollectRun
from collector.service import collect, is_stale, try_lock, unlock


class Command(BaseCommand):
    help = 'Collect LUN statistics for enabled cities into lun_raw / flat_price_point (one collect_run row).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--if-stale', action='store_true',
            help='Run only if the last successful collection is older than --max-age-days (catch-up after downtime).',
        )
        parser.add_argument('--max-age-days', type=float, default=7)
        parser.add_argument('--city', action='append', metavar='SLUG', help='Only these cities (repeatable).')
        parser.add_argument('--backup', action='store_true', help='pg_dump into BACKUP_DIR after a successful run.')

    def handle(self, *args, if_stale, max_age_days, city, backup, **options):
        if if_stale and not is_stale(dt.timedelta(days=max_age_days)):
            self.stdout.write(f'Last successful collection is younger than {max_age_days:g} days: skipped.')
            return
        cities = None
        if city:
            cities = list(City.objects.filter(slug__in=city))
            unknown = set(city) - {c.slug for c in cities}
            if unknown:
                raise CommandError(f'Unknown cities: {", ".join(sorted(unknown))}')

        if not try_lock():
            self.stdout.write('Another collection is running: skipped.')
            return
        try:
            run = collect(cities)
        finally:
            unlock()

        self.stdout.write(f'collect_run #{run.pk}: {run.status}, {run.rows_upserted} rows')
        if run.error:
            self.stderr.write(run.error)
        if run.status == CollectRun.Status.FAILED:
            raise CommandError('Collection failed')

        if backup:
            try:
                path = backup_from_settings()
            except (OSError, subprocess.CalledProcessError) as exc:
                stderr = getattr(exc, 'stderr', b'') or b''
                send_alert(f'backup failed: {exc} {stderr.decode(errors="replace")[:500]}')
                raise CommandError('Backup failed') from exc
            self.stdout.write(f'Backup: {path}' if path else 'Backup: BACKUP_DIR not set, skipped.')
