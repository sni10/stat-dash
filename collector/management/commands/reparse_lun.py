from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from pydantic import ValidationError

from collector.lun.endpoints import ENDPOINTS
from collector.models import LunRaw
from collector.service import Job, SchemaMismatch, store_parsed, try_lock, unlock


class Command(BaseCommand):
    help = ('Rebuild the entity tables from the lun_raw archive, oldest answer first (after a parser change, or to '
            'load answers collected before the tables existed). Idempotent.')

    def add_arguments(self, parser):
        parser.add_argument('--endpoint', action='append', choices=sorted(ENDPOINTS), help='Only these (repeatable).')
        parser.add_argument('--city', action='append', metavar='SLUG', help='Only these cities (repeatable).')

    def handle(self, *args, endpoint, city, **options):
        rows = LunRaw.objects.select_related('city').order_by('fetched_at', 'id')
        if endpoint:
            rows = rows.filter(endpoint__in=endpoint)
        if city:
            rows = rows.filter(city__slug__in=city)
        if not try_lock():
            raise CommandError('A collection is running: try again later.')
        written, parsed, failed = Counter(), Counter(), Counter()
        try:
            for raw in rows.iterator(chunk_size=50):
                job = Job(raw.endpoint, raw.city, raw.params)
                try:
                    written[raw.endpoint] += store_parsed(job, raw.payload, raw.fetched_at)
                    parsed[raw.endpoint] += 1
                except (ValidationError, SchemaMismatch) as exc:
                    failed[raw.endpoint] += 1
                    self.stderr.write(f'#{raw.pk} {job}: {type(exc).__name__}: {str(exc)[:300]}')
        finally:
            unlock()
        for name in sorted(parsed | failed):
            self.stdout.write(f'{name:24} answers {parsed[name]:4}  rows {written[name]:6}'
                              + (f'  failed {failed[name]}' if failed[name] else ''))
        if failed:
            raise CommandError(f'{sum(failed.values())} answers failed to parse')
