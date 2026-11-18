"""Weekly collection (spec, "Сбор данных"): fetch -> lun_raw -> validate -> lun_price_snapshot -> collect_run."""
import datetime as dt
import logging
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from pydantic import ValidationError

from .alerts import send_alert
from .lun.client import LunBlocked, LunClient, LunError
from .lun.hashing import payload_hash
from .lun.schemas import FlatPriceHistoryResponse, FlatPricePoint, PriceResponse
from .models import City, CollectRun, ContractType, LunRaw

logger = logging.getLogger(__name__)

FLAT_PRICE_HISTORY = 'flat-price-history'
PRICE = 'price'

# A run still "running" after this long was killed (container stopped, computer off) and never finished
INTERRUPTED_AFTER = dt.timedelta(hours=1)
# Two collections must not run at once: the weekly cron and the --if-stale catch-up can meet
ADVISORY_LOCK_KEY = 0x5747A7  # any constant unique within this database


class SchemaMismatch(Exception):
    """The response parsed, but does not belong to the request (other city or contract type)."""


@dataclass(frozen=True)
class Job:
    endpoint: str
    city: City
    params: dict

    def __str__(self):
        return f'{self.endpoint} {self.city.slug} {self.params}'


def plan_jobs(cities: Iterable[City]) -> list[Job]:
    jobs = []
    for city in cities:
        for contract_type in ContractType:
            jobs.append(Job(FLAT_PRICE_HISTORY, city, {'cityId': city.id, 'contractTypeId': int(contract_type)}))
        # `price` is archived raw and validated; normalized tables come in stage 2
        jobs.append(Job(PRICE, city, {'cityId': city.id}))
    return jobs


def store_raw(job: Job, payload: dict) -> bool:
    """Keep the response unless the last one for the same request had the same data. True if a row was added."""
    digest = payload_hash(payload)
    last = (
        LunRaw.objects.filter(endpoint=job.endpoint, city=job.city, params=job.params)
        .order_by('-fetched_at', '-id')
        .values_list('payload_hash', flat=True)
        .first()
    )
    if last == digest:
        return False
    LunRaw.objects.create(endpoint=job.endpoint, city=job.city, params=job.params, payload_hash=digest, payload=payload)
    return True


_SNAPSHOT_COLUMNS = (
    'snap_date', 'city_id', 'contract_type', 'room_count', 'median_uah', 'median_usd', 'median_m2_uah',
    'median_m2_usd', 'cnt', 'is_today', 'updated_at',
)
_VALUE_COLUMNS = ('median_uah', 'median_usd', 'median_m2_uah', 'median_m2_usd', 'cnt', 'is_today')
_UPSERT_SQL = (
    f'INSERT INTO lun_price_snapshot ({", ".join(_SNAPSHOT_COLUMNS)}) VALUES {{values}} '
    'ON CONFLICT (snap_date, city_id, contract_type, room_count) DO UPDATE SET '
    + ', '.join(f'{c} = EXCLUDED.{c}' for c in (*_VALUE_COLUMNS, 'updated_at'))
    # untouched points are not rewritten: the row count is the real delta
    + f' WHERE ({", ".join(f"lun_price_snapshot.{c}" for c in _VALUE_COLUMNS)})'
    f' IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in _VALUE_COLUMNS)})'
)


def upsert_price_history(city_id: int, contract_type: int, points: list[FlatPricePoint]) -> int:
    """Write one flat-price-history series. Returns the number of inserted or changed rows.

    The previous "today" rows of this city x contract type are deleted first. When the export date falls on a
    monthly date (the 24th), the monthly point wins and the "today" one is dropped: both have the same key.
    """
    monthly = {(p.date, p.roomCount): p for p in points if not p.isToday}
    today = {(p.date, p.roomCount): p for p in points if p.isToday and (p.date, p.roomCount) not in monthly}
    rows = [*monthly.values(), *today.values()]
    now = timezone.now()
    params = []
    for p in rows:
        params += [
            p.date, city_id, contract_type, p.roomCount, p.medianUah, p.medianUsd, p.medianM2Uah, p.medianM2Usd,
            p.count, p.isToday, now,
        ]
    placeholders = ', '.join(['(' + ', '.join(['%s'] * len(_SNAPSHOT_COLUMNS)) + ')'] * len(rows))
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            'DELETE FROM lun_price_snapshot WHERE city_id = %s AND contract_type = %s AND is_today',
            [city_id, contract_type],
        )
        if not rows:
            return 0
        cursor.execute(_UPSERT_SQL.format(values=placeholders), params)
        return cursor.rowcount


def store_parsed(job: Job, payload: dict) -> int:
    """Validate the payload and write the normalized rows. Raises ValidationError / SchemaMismatch."""
    if job.endpoint == FLAT_PRICE_HISTORY:
        response = FlatPriceHistoryResponse.model_validate(payload)
        contract_type = job.params['contractTypeId']
        foreign = [p for p in response.data if p.cityId != job.city.id or p.contractType != contract_type]
        if foreign:
            raise SchemaMismatch(f'{len(foreign)} points of another city or contract type')
        return upsert_price_history(job.city.id, contract_type, response.data)
    if job.endpoint == PRICE:
        PriceResponse.model_validate(payload)
        return 0
    raise ValueError(f'unknown endpoint {job.endpoint}')


def last_success(statuses=(CollectRun.Status.OK, CollectRun.Status.PARTIAL)) -> CollectRun | None:
    return CollectRun.objects.filter(status__in=statuses).order_by('-started_at').first()


def is_stale(max_age: dt.timedelta) -> bool:
    run = last_success()
    return run is None or timezone.now() - run.started_at > max_age


def mark_interrupted_runs() -> None:
    CollectRun.objects.filter(
        status=CollectRun.Status.RUNNING, started_at__lt=timezone.now() - INTERRUPTED_AFTER
    ).update(status=CollectRun.Status.FAILED, finished_at=timezone.now(), error='interrupted: never finished')


def try_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [ADVISORY_LOCK_KEY])
        return cursor.fetchone()[0]


def unlock() -> None:
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s)', [ADVISORY_LOCK_KEY])


def collect(
    cities: Iterable[City] | None = None,
    *,
    client: LunClient | None = None,
    sleep: Callable[[float], None] = time.sleep,
    alert: Callable[[str], None] = send_alert,
) -> CollectRun:
    """One collection over the given (default: enabled) cities. Always leaves a finished collect_run row."""
    mark_interrupted_runs()
    cities = list(City.objects.filter(enabled=True) if cities is None else cities)
    own_client = client is None
    client = client or LunClient(settings.LUN['BASE_URL'], sleep=sleep)
    run = CollectRun.objects.create(started_at=timezone.now(), status=CollectRun.Status.RUNNING)
    errors: list[str] = []
    rows = done = 0
    jobs = plan_jobs(cities)
    try:
        for i, job in enumerate(jobs):
            if i:
                sleep(random.uniform(*settings.LUN['PAUSE']))
            try:
                payload = client.get(job.endpoint, job.params)
            except LunBlocked as exc:
                errors.append(f'blocked: {exc}; {len(jobs) - i - 1} requests skipped')
                break  # don't hammer a site that blocks us
            except LunError as exc:
                errors.append(f'request failed: {exc}')
                continue
            stored = store_raw(job, payload)
            try:
                upserted = store_parsed(job, payload)
            except (ValidationError, SchemaMismatch) as exc:
                errors.append(f'schema: {job}: {exc}'.strip()[:2000])
                continue
            rows += upserted
            done += 1
            logger.info('%s: raw %s, %d rows', job, 'stored' if stored else 'unchanged', upserted)
    except Exception as exc:
        errors.append(f'crashed: {type(exc).__name__}: {exc}')
        _finish(run, errors, rows, done, alert)
        raise
    finally:
        if own_client:
            client.close()
    return _finish(run, errors, rows, done, alert)


def _finish(run: CollectRun, errors: list[str], rows: int, done: int, alert: Callable[[str], None]) -> CollectRun:
    if not errors:
        run.status = CollectRun.Status.OK
    else:
        run.status = CollectRun.Status.PARTIAL if done else CollectRun.Status.FAILED
    run.finished_at = timezone.now()
    run.rows_upserted = rows
    run.error = '\n'.join(errors)
    run.save()
    if errors:
        alert(f'collection #{run.pk} {run.status}:\n' + '\n'.join(errors))
    return run
