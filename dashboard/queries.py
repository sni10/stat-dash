"""Read side of the dashboard: filters from query params, series and KPIs from lun_price_snapshot / v_price_monthly.

LUN's median price per m² is one number per city and date: it is the same for every room count (checked on the
whole Odesa history). So m² series are per city; only the object price differs by room count.
"""
import calendar
import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass

from django.conf import settings
from django.contrib.postgres.aggregates import BoolOr
from django.db import connection
from django.db.models import Max, Sum

from collector.models import City, CollectRun, ContractType, LunPriceSnapshot

DEALS = {'sale': ContractType.SALE, 'rent': ContractType.RENT}
CURRENCIES = ('usd', 'uah')
ROOMS = (1, 2, 3)  # 4+ rooms are collected but not shown anywhere in the dashboard
STALE_AFTER = dt.timedelta(days=8)  # spec: missed run = last successful collect_run older than 8 days


class BadFilter(ValueError):
    pass


@dataclass(frozen=True)
class Filters:
    city: City
    deal: str = 'sale'
    cur: str = 'usd'
    rooms: tuple[int, ...] = ROOMS
    date_from: dt.date | None = None
    date_to: dt.date | None = None

    @property
    def contract_type(self) -> int:
        return int(DEALS[self.deal])

    def as_query(self, **overrides) -> dict:
        """The filters as query params (for links and the JSON endpoints)."""
        values = {
            'city': self.city.slug, 'deal': self.deal, 'cur': self.cur,
            'from': self.date_from.strftime('%Y-%m') if self.date_from else '',
            'to': self.date_to.strftime('%Y-%m') if self.date_to else '',
        }
        if self.rooms != ROOMS:
            values['rooms'] = ','.join(map(str, self.rooms))
        values.update(overrides)
        return {k: v for k, v in values.items() if v}


def _month(value: str, *, end: bool) -> dt.date:
    try:
        year, month = map(int, value.split('-'))
        first = dt.date(year, month, 1)
    except ValueError:
        raise BadFilter(f'month must be YYYY-MM, got {value!r}') from None
    return first.replace(day=calendar.monthrange(year, month)[1]) if end else first


def default_city() -> City | None:
    return (City.objects.filter(slug=settings.DASHBOARD_DEFAULT_CITY).first()
            or City.objects.filter(enabled=True).order_by('id').first() or City.objects.order_by('id').first())


def parse_filters(params: Mapping[str, str]) -> Filters:
    slug = params.get('city') or ''
    city = City.objects.filter(slug=slug).first() if slug else default_city()
    if city is None:
        raise BadFilter(f'unknown city {slug!r}')
    deal = params.get('deal') or 'sale'
    if deal not in DEALS:
        raise BadFilter(f'deal must be one of {", ".join(DEALS)}')
    cur = params.get('cur') or 'usd'
    if cur not in CURRENCIES:
        raise BadFilter(f'cur must be one of {", ".join(CURRENCIES)}')
    rooms = ROOMS
    if params.get('rooms'):
        try:
            rooms = tuple(sorted({int(r) for r in params['rooms'].split(',')}))
        except ValueError:
            raise BadFilter('rooms must be a comma-separated list of numbers') from None
        if not set(rooms) <= set(ROOMS):
            raise BadFilter(f'rooms must be within {ROOMS}')
    date_from = _month(params['from'], end=False) if params.get('from') else None
    date_to = _month(params['to'], end=True) if params.get('to') else None
    if date_from and date_to and date_from > date_to:
        raise BadFilter('from is after to')
    return Filters(city, deal, cur, rooms, date_from, date_to)


def _snapshots(f: Filters):
    qs = LunPriceSnapshot.objects.filter(city=f.city, contract_type=f.contract_type)
    if f.date_from:
        qs = qs.filter(snap_date__gte=f.date_from)
    if f.date_to:
        qs = qs.filter(snap_date__lte=f.date_to)
    return qs


def _num(value) -> float | None:
    return None if value is None else float(value)


def price_points(f: Filters) -> list[dict]:
    """Every point of the series: per date and room count, the "today" point marked as preliminary."""
    rows = (
        _snapshots(f).filter(room_count__in=f.rooms)
        .order_by('snap_date', 'room_count')
        .values_list('snap_date', 'room_count', f'median_{f.cur}', f'median_m2_{f.cur}', 'cnt', 'is_today')
    )
    return [
        {'date': d.isoformat(), 'rooms': r, 'price': _num(p), 'price_m2': _num(m2), 'count': c, 'preliminary': t}
        for d, r, p, m2, c, t in rows
    ]


def city_series(f: Filters) -> list[dict]:
    """Per date: the city's m² median (one value for all room counts) and the number of listings (all rooms)."""
    rows = (
        _snapshots(f).filter(room_count__in=f.rooms).values('snap_date')
        .annotate(m2=Max(f'median_m2_{f.cur}'), count=Sum('cnt'), today=BoolOr('is_today'))
        .order_by('snap_date')
    )
    return [
        {'date': r['snap_date'], 'price_m2': _num(r['m2']), 'count': r['count'], 'preliminary': bool(r['today'])}
        for r in rows
    ]


def monthly_rows(f: Filters) -> list[dict]:
    sql = (
        f'SELECT month, room_count, w_avg_m2_{f.cur}, med_m2_{f.cur}, w_avg_{f.cur}, avg_cnt '
        'FROM v_price_monthly WHERE city_id = %s AND contract_type = %s AND room_count = ANY(%s)'
    )
    params: list = [f.city.id, f.contract_type, list(f.rooms)]
    if f.date_from:
        sql += ' AND month >= %s'
        params.append(f.date_from.replace(day=1))
    if f.date_to:
        sql += ' AND month <= %s'
        params.append(f.date_to)
    sql += ' ORDER BY month, room_count'
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [
        {'month': m.strftime('%Y-%m'), 'rooms': r, 'w_avg_m2': _num(wm2), 'med_m2': _num(mm2),
         'w_avg_price': _num(wp), 'avg_count': _num(c)}
        for m, r, wm2, mm2, wp, c in rows
    ]


def _closest(series: list[dict], target: dt.date, tolerance: int = 20) -> dict | None:
    """The point nearest to `target`, if within `tolerance` days (the series is monthly, on the 24th)."""
    best = min(series, key=lambda p: abs((p['date'] - target).days), default=None)
    if best is None or abs((best['date'] - target).days) > tolerance:
        return None
    return best


def _change(now: float | None, before: dict | None, key: str) -> float | None:
    if now is None or before is None or not before[key]:
        return None
    return now / before[key] - 1


def overview(f: Filters) -> dict | None:
    """KPIs of the overview page for the whole history of the city x deal: the latest point (possibly the
    preliminary "today" one), its change month over month and year over year, and the number of listings."""
    series = city_series(Filters(f.city, f.deal, f.cur))
    if not series:
        return None
    latest = series[-1]
    earlier = [p for p in series if p['date'] < latest['date']]
    month_ago = _closest(earlier, latest['date'] - dt.timedelta(days=30))
    year_ago = _closest(earlier, latest['date'] - dt.timedelta(days=365))
    return {
        'date': latest['date'],
        'preliminary': latest['preliminary'],
        'price_m2': latest['price_m2'],
        'm2_mom': _change(latest['price_m2'], month_ago, 'price_m2'),
        'm2_yoy': _change(latest['price_m2'], year_ago, 'price_m2'),
        'count': latest['count'],
        'count_mom': _change(latest['count'], month_ago, 'count'),
        'month_ago': month_ago['date'] if month_ago else None,
        'year_ago': year_ago['date'] if year_ago else None,
        'first_date': series[0]['date'],
    }


def collection_status(now: dt.datetime) -> dict:
    last = CollectRun.objects.filter(status__in=[CollectRun.Status.OK, CollectRun.Status.PARTIAL]).first()
    return {
        'last_success': last,
        'stale': last is None or now - last.started_at > STALE_AFTER,
    }
