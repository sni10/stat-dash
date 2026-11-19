"""LUN answer -> rows of the entity tables (docs/data-model.md), one parser per endpoint.

A parser gets the validated `data` of an answer and returns Batches; apply() upserts them on each table's natural key.
Series replace their floating "today" rows (today_scope); snapshots are keyed by snap_date, so the same date
overwrites and a new one adds a snapshot. flat-price-history keeps its own SQL upsert in collector.service.
"""
import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import models, transaction
from django.utils import timezone

from . import models as m
from .models import natural_key

logger = logging.getLogger(__name__)

# LUN's labels and ids -> ours
CLASS_LABELS = {'економ': 'economy', 'комфорт': 'comfort', 'бізнес': 'business', 'преміум': 'premium'}
PARKING_CLASS_IDS = {1: 'economy', 4: 'comfort', 2: 'business', 3: 'premium'}  # checked on lun.ua/stat/primary
CURRENCY_IDS = {1: 'usd', 2: 'uah'}
MICRODISTRICT_FROM = 10_000_000  # Ivano-Frankivsk sends micro-districts with ids like 10027077


@dataclass
class Context:
    city: m.City | None  # None for the global endpoints
    contract_type: int | None  # the request's contractTypeId, if any
    fetched_at: dt.datetime  # snapshots without a date of their own are dated by the collection

    @property
    def collected_on(self) -> dt.date:
        return timezone.localdate(self.fetched_at)


@dataclass
class Batch:
    model: type[models.Model]
    rows: list[dict]
    today_scope: dict | None = None  # series: delete these rows' is_today points before the upsert
    label: str = field(default='')


def apply(batches: list[Batch]) -> int:
    """Upsert every batch (one transaction per call). Returns the number of rows written."""
    written = 0
    with transaction.atomic():
        for batch in batches:
            written += _upsert(batch)
    return written


def _upsert(batch: Batch) -> int:
    model = batch.model
    key = natural_key(model)
    attnames = [model._meta.get_field(f).attname for f in key]
    # one row per key; for series the monthly point wins over "today" on the same date
    unique = {}
    for row in sorted(batch.rows, key=lambda r: not r.get('is_today', False)):
        unique[tuple(row[a] for a in attnames)] = row
    if batch.today_scope is not None:
        model.objects.filter(is_today=True, **batch.today_scope).delete()
    if not unique:
        return 0
    update = [f.name for f in model._meta.concrete_fields if not f.primary_key and f.name not in key]
    model.objects.bulk_create([model(**row) for row in unique.values()], update_conflicts=True,
                              unique_fields=key, update_fields=update)
    return len(unique)


def _districts(city: m.City, items) -> dict[tuple[str, int], int]:
    """Upsert the districts [(kind, lun_id, name_uk, name_en)] of a city; map (kind, lun_id) -> district pk."""
    rows = {(kind, lun_id): (name_uk, name_en or '') for kind, lun_id, name_uk, name_en in items}
    if rows:
        m.District.objects.bulk_create(
            [m.District(city=city, kind=k, lun_id=i, name_uk=uk, name_en=en) for (k, i), (uk, en) in rows.items()],
            update_conflicts=True, unique_fields=['city', 'kind', 'lun_id'], update_fields=['name_uk', 'name_en'],
        )
    return {(d.kind, d.lun_id): d.pk for d in m.District.objects.filter(city=city)}


def _day(value: dt.datetime | dt.date) -> dt.date:
    return value.date() if isinstance(value, dt.datetime) else value


def _label(label) -> tuple[str, str]:
    return (label, '') if isinstance(label, str) else (label.uk, label.en or '')


# --- series ----------------------------------------------------------------------------------------------------

def parse_price(data, ctx: Context) -> list[Batch]:
    rows = []
    for scope, classes, average in (('city', data.cityClasses, data.cityAvg),
                                    ('region', data.regionClasses, data.regionAvg)):
        for item in classes:
            housing_class = CLASS_LABELS.get((item.label or '').lower())
            if housing_class is None:
                logger.warning('price: unknown housing class %r skipped', item.label)
                continue
            rows.append(_class_row(ctx, scope, housing_class, item))
        rows += [_class_row(ctx, scope, 'all', item) for item in average]
    return [Batch(m.PrimaryClassPrice, rows, today_scope={'city': ctx.city})]


def _class_row(ctx, scope, housing_class, item):
    return {'city_id': ctx.city.id, 'scope': scope, 'housing_class': housing_class, 'month': item.monthDate,
            'avg_uah': item.averageUah, 'avg_usd': item.averageUsd, 'cnt': item.count, 'is_today': item.isToday}


def parse_exposure(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'contract_type': r.contractType, 'room_count': r.roomCount or 0,
             'date': r.dateStr, 'days': r.exposure, 'cnt': r.count, 'is_today': r.isToday} for r in data]
    return [Batch(m.ExposurePoint, rows, today_scope={'city': ctx.city})]


def parse_rieltor(data, ctx: Context) -> list[Batch]:
    rows = [{
        'city_id': ctx.city.id, 'contract_type': r.contractType, 'room_count': r.roomCount, 'date': r.dateStr,
        'listing_uah': r.price, 'listing_usd': r.priceUsd, 'deal_uah': r.dealPrice, 'deal_usd': r.dealPriceUsd,
        'listing_m2_uah': r.priceM2, 'listing_m2_usd': r.priceUsdM2, 'deal_m2_uah': r.dealPriceM2,
        'deal_m2_usd': r.dealPriceUsdM2, 'is_today': r.isToday,
    } for r in data]
    return [Batch(m.DealPricePoint, rows, today_scope={'city': ctx.city})]


def parse_salary_history(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'contract_type': r.contractTypeId, 'room_count': r.roomCount,
             'date': _day(r.date), 'value': r.value, 'price': r.price, 'salary': r.salary, 'cnt': r.count,
             'is_today': r.isToday} for r in data]
    return [Batch(m.AffordabilityPoint, rows, today_scope={'city': ctx.city})]


def parse_sale_in_rent(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'room_count': r.roomCount, 'date': r.date, 'years': r.value,
             'is_today': r.isToday} for r in data]
    return [Batch(m.RentPaybackPoint, rows, today_scope={'city': ctx.city})]


def parse_houses(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'contract_type': r.contractTypeId, 'scope': r.regionType, 'date': r.date,
             'median_uah': r.medianUah, 'median_usd': r.medianUsd, 'median_m2_uah': r.medianM2Uah,
             'median_m2_usd': r.medianM2Usd, 'area': r.area, 'cnt': r.count, 'is_today': r.isToday} for r in data]
    return [Batch(m.HousePricePoint, rows, today_scope={'city': ctx.city, 'contract_type': ctx.contract_type})]


def parse_dssu(data, ctx: Context) -> list[Batch]:
    rows = [{'region_id': r.regionId, 'year': r.year, 'quarter': r.quarter, 'all_m2': r.allBuildings,
             'apartment_m2': r.apartmentBuildings} for r in data]
    return [Batch(m.HousingCommissioning, rows)]


# --- snapshots ---------------------------------------------------------------------------------------------------

def parse_market_districts(data, ctx: Context) -> list[Batch]:
    def kind(r):
        return m.District.Kind.MICRODISTRICT if r.districtId >= MICRODISTRICT_FROM else m.District.Kind.DISTRICT

    ids = _districts(ctx.city, [(kind(r), r.districtId, r.districtName or str(r.districtId), r.districtNameEng)
                                for r in data])
    rows = [{
        'district_id': ids[(kind(r), r.districtId)], 'contract_type': r.contractTypeId, 'room_count': r.roomCount,
        'snap_date': _day(r.date),
        'median_uah': r.median, 'median_renovated_uah': r.medianRenovated,
        'median_not_renovated_uah': r.medianNotRenovated,
        # per m² of total area; the short shape (micro-districts) has only medianM2
        'median_m2_uah': r.medianM2Total if r.medianM2Total is not None else r.medianM2,
        'median_m2_renovated_uah': r.medianM2TotalRenovated,
        'median_m2_not_renovated_uah': r.medianM2TotalNotRenovated,
        'median_usd': r.medianUsd, 'median_m2_usd': r.medianM2Usd, 'usd_to_uah': r.usdToUah,
        'cnt': r.count, 'cnt_renovated': r.countRenovated, 'cnt_not_renovated': r.countNotRenovated,
    } for r in data]
    return [Batch(m.DistrictPrice, rows)]


def _average_by_district(item):
    def parse(data, ctx: Context) -> list[Batch]:
        def kind(r):
            return m.District.Kind.SETTLEMENT if r.isCity else m.District.Kind.DISTRICT

        ids = _districts(ctx.city, [(kind(r), r.key, *_label(r.label)) for r in data])
        rows = [{'district_id': ids[(kind(r), r.key)], 'item': item, 'snap_date': _day(r.month),
                 'avg_uah': r.averageUah, 'avg_usd': r.averageUsd, 'cnt': r.count} for r in data]
        return [Batch(m.DistrictAveragePrice, rows)]
    return parse


def parse_house_districts(data, ctx: Context) -> list[Batch]:
    ids = _districts(ctx.city, [(m.District.Kind.DISTRICT, r.districtId, r.nameUk, r.nameEn) for r in data])
    rows = [{'district_id': ids[(m.District.Kind.DISTRICT, r.districtId)], 'contract_type': r.contractTypeId,
             'snap_date': _day(r.date), 'median_usd': r.medianUsd, 'median_m2_usd': r.medianM2Usd, 'area': r.area,
             'cnt': r.count} for r in data]
    return [Batch(m.HouseDistrictPrice, rows)]


def parse_price_distribution(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'contract_type': r.contractTypeId, 'room_count': r.roomCount,
             'currency': CURRENCY_IDS.get(r.currencyId, str(r.currencyId)), 'snap_date': _day(r.date),
             'price_from': r.priceStart, 'price_to': r.priceEnd, 'cnt': r.count} for r in data]
    return [Batch(m.PriceBucket, rows)]


def parse_salary_positions(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'contract_type': r.contractTypeId, 'room_count': r.roomCount,
             'profession_uk': r.nameUa, 'profession_en': r.nameEn or '', 'snap_date': _day(r.date),
             'value': r.value, 'salary': r.salary, 'price': r.price, 'url': (r.url or '')[:500]} for r in data]
    return [Batch(m.ProfessionAffordability, rows)]


def parse_parking_classes(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'scope': r.regionType, 'housing_class': PARKING_CLASS_IDS[r.classId],
             'snap_date': _day(r.date), 'median_uah': r.medianUah, 'median_usd': r.medianUsd, 'cnt': r.count}
            for r in data if r.classId in PARKING_CLASS_IDS]
    return [Batch(m.ParkingClassPrice, rows)]


def parse_developers_ranking(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'year': r.year, 'name': r.name, 'place': r.place, 'flats': r.count}
            for r in data]
    return [Batch(m.DeveloperRank, rows)]


def parse_developers_distribution(data, ctx: Context) -> list[Batch]:
    rows = [{'city_id': ctx.city.id, 'year': r.year, 'name': r.name, 'share_pct': r.value} for r in data]
    return [Batch(m.DeveloperShare, rows)]


def _known_cities() -> set[int]:
    return set(m.City.objects.values_list('id', flat=True))


def _city_region(model, fields):
    """lending and sections: {cityId: {city: {...}, region: {...}}} for every city, dated by the collection."""
    def parse(data, ctx: Context) -> list[Batch]:
        known = _known_cities()
        rows = [
            {'city_id': city_id, 'scope': scope, 'snap_date': ctx.collected_on,
             **{ours: getattr(entry, scope).get(theirs, 0) for ours, theirs in fields.items()}}
            for city_id, entry in data.items() if city_id in known for scope in ('city', 'region')
        ]
        return [Batch(model, rows)]
    return parse


def parse_pets_rent(data, ctx: Context) -> list[Batch]:
    known = _known_cities()
    rows = [{'city_id': r.cityId, 'scope': r.regionType, 'realty_type': r.realtyType,
             'snap_date': _day(r.date) if r.date else ctx.collected_on, 'allowed': r.yesPercent,
             'by_agreement': r.somePercent, 'forbidden': r.noPercent, 'unknown': r.unknownPercent, 'cnt': r.count}
            for r in data if r.cityId in known]
    return [Batch(m.PetsRentShare, rows)]


PARSERS: dict[str, Callable] = {
    'price': parse_price,
    'median-exposure': parse_exposure,
    'rieltor': parse_rieltor,
    'salary-history': parse_salary_history,
    'sale-in-rent-history': parse_sale_in_rent,
    'houses-price-history': parse_houses,
    'dssu': parse_dssu,
    'market-districts': parse_market_districts,
    'districts': _average_by_district(m.DistrictAveragePrice.Item.FLAT_M2),
    'parking-districts': _average_by_district(m.DistrictAveragePrice.Item.PARKING),
    'districts-house-price': parse_house_districts,
    'price-distribution': parse_price_distribution,
    'salary-positions': parse_salary_positions,
    'parking-classes': parse_parking_classes,
    'developers-ranking': parse_developers_ranking,
    'developers-distribution': parse_developers_distribution,
    'sections': _city_region(m.ConstructionStat, {
        'on_sale': 'active', 'under_construction': 'under_construct', 'preparatory': 'preparatory_work',
        'built': 'built'}),
    'lending': _city_region(m.LendingStat, {
        'installments': 'installments', 'mortgages': 'mortgagesYeOselya', 'credits': 'credits'}),
    'pets-rent': parse_pets_rent,
}


def parse(endpoint: str, data, ctx: Context) -> int:
    """Parse a validated answer into the entity tables. Returns the number of rows written."""
    return apply(PARSERS[endpoint](data, ctx))
