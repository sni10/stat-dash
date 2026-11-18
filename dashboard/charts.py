"""Chart specs for the extra pages (Districts, Market, Affordability, New buildings, Houses).

Every builder takes the page context and returns a plain dict that charts.js draws:

    {title, subtitle, type: line|area|bar|hbar|donut, unit, digits, series: [{name, data}], categories,
     labels, values, preliminary: [ISO dates], empty: str | None}

line/area: data = [{x: ISO date, y}]; bar/hbar: data aligned with `categories`; donut: `labels` + `values`.
"""
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from collector.models import City

from .lun_data import latest

SYMBOL = {'usd': '$', 'uah': '₴'}
ROOM = {None: 'Все', 1: '1 комн.', 2: '2 комн.', 3: '3 комн.'}  # 4+ rooms are not shown
DEAL_IDS = {'sale': 1, 'rent': 2}
NO_DATA = 'ЛУН не публикует эти данные для выбранного города.'


@dataclass(frozen=True)
class Ctx:
    city: City
    deal: str = 'sale'
    cur: str = 'usd'
    room: int = 1
    repair: str = 'all'  # all | renovated | not
    metric: str = 'price'  # price | m2

    @property
    def ct(self) -> int:
        return DEAL_IDS[self.deal]

    @property
    def symbol(self) -> str:
        return SYMBOL[self.cur]

    @property
    def per_month(self) -> str:
        return ' в месяц' if self.deal == 'rent' else ''


def _spec(title, subtitle='', *, type='line', unit='', digits=0, series=(), categories=None, labels=None,
          values=None, preliminary=(), empty=None, height=320):
    has_data = any(s['data'] for s in series) if series else bool(values)
    return {
        'title': title, 'subtitle': subtitle, 'type': type, 'unit': unit, 'digits': digits,
        'series': list(series), 'categories': categories or [], 'labels': labels or [], 'values': values or [],
        'preliminary': sorted(set(preliminary)), 'empty': None if has_data else (empty or NO_DATA),
        'height': height,
    }


def _line(points):
    # 0 never is a real price, term or share here: LUN sends it for months without data (spring 2022) -> a gap
    return [{'x': p.x.isoformat(), 'y': p.y or None} for p in sorted(points, key=lambda p: p.x)]


@dataclass(frozen=True)
class _P:
    x: object
    y: float | None


def _series_by(items, group, x, y, name=lambda g: str(g), order=None):
    """Line series, one per group value, sorted by x."""
    groups = defaultdict(list)
    for item in items:
        groups[group(item)].append(_P(x(item), y(item)))
    keys = order if order is not None else sorted(groups, key=lambda g: (g is not None, g))
    return [{'name': name(g), 'data': _line(groups[g])} for g in keys if g in groups]


def _today(items, x, flag='isToday'):
    return [x(i).isoformat() for i in items if getattr(i, flag, False)]


def _usd_uah(ctx, usd, uah):
    return usd if ctx.cur == 'usd' else uah


# --- Districts --------------------------------------------------------------------------------------------

def flat_districts(ctx: Ctx):
    data = latest('market-districts', ctx.city) or []
    rows = [r for r in data if r.contractTypeId == ctx.ct and r.roomCount == ctx.room]
    suffix = {'all': '', 'renovated': 'Renovated', 'not': 'NotRenovated'}[ctx.repair]
    field = ('median' if ctx.metric == 'price' else 'medianM2Total') + suffix
    rows.sort(key=lambda r: -(getattr(r, field) or 0))
    values = [None if getattr(r, field) is None else getattr(r, field) / (r.usdToUah if ctx.cur == 'usd' else 1)
              for r in rows]
    what = 'цена квартиры' if ctx.metric == 'price' else 'цена м²'
    repair = {'all': '', 'renovated': ', с ремонтом', 'not': ', без ремонта'}[ctx.repair]
    when = f' на {rows[0].date:%d.%m.%Y}' if rows else ''
    return _spec(
        f'{"Аренда" if ctx.deal == "rent" else "Вторичка"}: медианная {what}, {ROOM[ctx.room]}{repair}',
        f'По районам{when}. {ctx.cur.upper()}{ctx.per_month}.',
        type='hbar', unit=ctx.symbol, categories=[r.districtName or str(r.districtId) for r in rows],
        series=[{'name': 'Медиана', 'data': values}], height=60 + 44 * max(len(rows), 1),
    )


def _average_by_district(endpoint, ctx, title, subtitle):
    data = latest(endpoint, ctx.city) or []
    rows = sorted(data, key=lambda r: -(r.averageUsd or 0))
    when = f' на {rows[0].month:%d.%m.%Y}' if rows else ''
    return _spec(title, subtitle + when + '.', type='hbar', unit=ctx.symbol, categories=[r.label.uk for r in rows],
                 series=[{'name': 'Медиана', 'data': [_usd_uah(ctx, r.averageUsd, r.averageUah) for r in rows]}],
                 height=60 + 44 * max(len(rows), 1))


def primary_districts(ctx: Ctx):
    return _average_by_district('districts', ctx, 'Новостройки: стартовая цена м² по районам',
                                f'Медиана стартовой цены от застройщиков, {ctx.cur.upper()}')


def parking_districts(ctx: Ctx):
    return _average_by_district('parking-districts', ctx, 'Паркоместо в новостройке по районам',
                                f'Медиана стартовой цены, {ctx.cur.upper()}')


# --- Market -----------------------------------------------------------------------------------------------

def exposure(ctx: Ctx):
    data = [r for r in latest('median-exposure', ctx.city) or [] if r.contractType == ctx.ct and r.roomCount in ROOM]
    verb = 'сдаётся' if ctx.deal == 'rent' else 'продаётся'
    return _spec(
        f'Как быстро квартира {verb}', 'Медианный срок экспозиции объявления, дней.',
        unit='дн.', series=_series_by(data, lambda r: r.roomCount, lambda r: r.dateStr, lambda r: r.exposure,
                                      name=lambda g: ROOM[g]),
        preliminary=_today(data, lambda r: r.dateStr),
    )


def _bucket_label(start, end, symbol):
    def short(v):
        return f'{v / 1000:g} тыс.' if v >= 1000 else f'{v:g}'
    return f'от {short(start)} {symbol}' if end is None else f'{short(start)}–{short(end)} {symbol}'


def price_distribution(ctx: Ctx):
    # one room count: their buckets have different bounds, side by side they interleave
    data = [r for r in latest('price-distribution', ctx.city) or []
            if r.contractTypeId == ctx.ct and r.roomCount == ctx.room]
    currency = 1 if ctx.cur == 'usd' else 2
    rows = [r for r in data if r.currencyId == currency]
    note = ''
    if not rows and data:  # sale is published in USD only
        rows, currency, note = [r for r in data if r.currencyId == 1], 1, ' ЛУН публикует продажу только в USD.'
    symbol = '$' if currency == 1 else '₴'
    buckets = sorted({(r.priceStart, r.priceEnd) for r in rows}, key=lambda b: b[0])
    counts = defaultdict(int)
    for r in rows:
        counts[(r.roomCount, r.priceStart, r.priceEnd)] += r.count
    rooms = sorted({r.roomCount for r in rows})
    # LUN sends ~80 narrow buckets with a long, almost empty tail: keep the ones holding 97% of the listings and
    # fold the rest into one "from X" bucket
    totals = [sum(counts[(room, s, e)] for room in rooms) for s, e in buckets]
    grand, running, cut = sum(totals), 0, len(buckets)
    for i, total in enumerate(totals):
        running += total
        if grand and running >= 0.97 * grand:
            cut = i + 1
            break
    if cut < len(buckets) - 1:
        start = buckets[cut][0]
        for room in rooms:
            counts[(room, start, None)] = sum(counts[(room, s, e)] for s, e in buckets[cut:])
        buckets = buckets[:cut] + [(start, None)]
    when = f' на {rows[0].date:%d.%m.%Y}' if rows else ''
    return _spec(
        'Самые распространённые цены' + (' аренды' if ctx.deal == 'rent' else '') + f', {ROOM[ctx.room]}',
        f'Число объявлений по ценовым интервалам{when}.{note}', type='bar', unit='объявл.',
        categories=[_bucket_label(s, e, symbol) for s, e in buckets],
        series=[{'name': ROOM[room], 'data': [counts.get((room, s, e), 0) for s, e in buckets]} for room in rooms],
        height=360,
    )


def listing_vs_deal(ctx: Ctx):
    data = [r for r in latest('rieltor', ctx.city) or [] if r.contractType == ctx.ct and r.roomCount == ctx.room]
    listing = [_P(r.dateStr, _usd_uah(ctx, r.priceUsd, r.price)) for r in data]
    deal = [_P(r.dateStr, _usd_uah(ctx, r.dealPriceUsd, r.dealPrice)) for r in data]
    return _spec(
        f'Цена в объявлении и цена сделки, {ROOM[ctx.room]}',
        f'Медианы по данным риелторов, {ctx.cur.upper()}{ctx.per_month}. Разница — торг.',
        unit=ctx.symbol, series=[{'name': 'В объявлении', 'data': _line(listing)},
                                 {'name': 'Сделка', 'data': _line(deal)}],
        preliminary=_today(data, lambda r: r.dateStr),
    )


# --- Affordability ----------------------------------------------------------------------------------------

def salary_history(ctx: Ctx):
    data = [r for r in latest('salary-history', ctx.city) or [] if r.contractTypeId == ctx.ct and r.roomCount in ROOM]
    if ctx.deal == 'rent':
        title, subtitle, unit, digits = ('Доля зарплаты, которая уходит на аренду',
                                         'Медианная аренда в % от медианной зарплаты (work.ua).', '%', 0)
    else:
        title, subtitle, unit, digits = ('Цена квартиры в годах зарплаты',
                                         'Сколько лет копить всю медианную зарплату (work.ua).', 'лет', 1)
    return _spec(title, subtitle, unit=unit, digits=digits,
                 series=_series_by(data, lambda r: r.roomCount, lambda r: r.date.date(), lambda r: r.value,
                                   name=lambda g: ROOM[g]),
                 preliminary=_today(data, lambda r: r.date.date()))


def salary_positions(ctx: Ctx):
    data = [r for r in latest('salary-positions', ctx.city) or []
            if r.contractTypeId == ctx.ct and r.roomCount in ROOM]
    professions = sorted({r.nameUa for r in data},
                         key=lambda n: next((r.salary or 0) for r in data if r.nameUa == n))
    value = {(r.roomCount, r.nameUa): r.value for r in data}
    rooms = sorted({r.roomCount for r in data})
    rent = ctx.deal == 'rent'
    return _spec(
        'Доля зарплаты на аренду по профессиям' if rent else 'Цена квартиры в годах зарплаты по профессиям',
        'Медианные зарплаты профессий по данным work.ua.', type='hbar', unit='%' if rent else 'лет',
        digits=0 if rent else 1, categories=professions,
        series=[{'name': ROOM[room], 'data': [value.get((room, p)) for p in professions]} for room in rooms],
        height=80 + 36 * max(len(professions), 1),
    )


def sale_in_rent(ctx: Ctx):
    data = [r for r in latest('sale-in-rent-history', ctx.city) or [] if r.roomCount in ROOM]
    return _spec('Цена квартиры в годах аренды', 'За сколько лет аренда окупает покупку той же квартиры.',
                 unit='лет', digits=1,
                 series=_series_by(data, lambda r: r.roomCount, lambda r: r.date, lambda r: r.value,
                                   name=lambda g: ROOM[g]),
                 preliminary=_today(data, lambda r: r.date))


def pets_rent(ctx: Ctx):
    rows = [r for r in latest('pets-rent', None) or []
            if r.cityId == ctx.city.id and r.realtyType == 'flat' and r.regionType == 'city']
    row = rows[0] if rows else None
    return _spec(
        'Аренда с домашними животными', 'Доля объявлений квартир.', type='donut', unit='%', digits=1,
        labels=['Можно', 'По договорённости', 'Нельзя', 'Не указано'],
        values=[row.yesPercent, row.somePercent, row.noPercent, row.unknownPercent] if row else [],
        empty='ЛУН публикует это только для Киева и Львова.',
    )


# --- New buildings ----------------------------------------------------------------------------------------

CLASS_NAMES = {'економ': 'Эконом', 'комфорт': 'Комфорт', 'бізнес': 'Бизнес', 'преміум': 'Премиум'}
CLASS_ORDER = ['Эконом', 'Комфорт', 'Бизнес', 'Премиум']


def primary_classes(ctx: Ctx):
    data = latest('price', ctx.city)
    items = []
    if data is not None:
        items = [(CLASS_NAMES.get(r.label, r.label), r) for r in data.cityClasses]
        items += [('Средняя по городу', r) for r in data.cityAvg]
    # 0 = no listings that month (spring 2022): a gap, not a price
    series = _series_by(items, lambda i: i[0], lambda i: i[1].monthDate,
                        lambda i: _usd_uah(ctx, i[1].averageUsd, i[1].averageUah) or None,
                        order=CLASS_ORDER + ['Средняя по городу'])
    return _spec('Новостройки: стартовая цена м² по классам',
                 f'Медиана стартовой цены от застройщиков, {ctx.cur.upper()}.', unit=ctx.symbol, series=series,
                 preliminary=[i[1].monthDate.isoformat() for i in items if i[1].isToday])


PARKING_CLASSES = {1: 'Эконом', 4: 'Комфорт', 2: 'Бизнес', 3: 'Премиум'}  # LUN's classId, in display order


def parking_classes(ctx: Ctx):
    data = latest('parking-classes', ctx.city) or []
    value = {(r.regionType, r.classId): _usd_uah(ctx, r.medianUsd, r.medianUah) for r in data}
    return _spec('Паркоместо в новостройке по классу дома', f'Медиана стартовой цены, {ctx.cur.upper()}.',
                 type='bar', unit=ctx.symbol, categories=list(PARKING_CLASSES.values()),
                 series=[{'name': name, 'data': [value.get((region, c)) for c in PARKING_CLASSES]}
                         for region, name in (('city', 'Город'), ('region', 'Область'))
                         if any((region, c) in value for c in PARKING_CLASSES)])


def _latest_year(rows):
    return max((r.year for r in rows), default=None)


def developers_ranking(ctx: Ctx):
    data = latest('developers-ranking', ctx.city) or []
    year = _latest_year(data)
    rows = sorted((r for r in data if r.year == year), key=lambda r: -r.count)[:10]
    return _spec(f'Топ застройщиков по сданным квартирам{f", {year}" if year else ""}',
                 'Город и область, по сертификатам о вводе в эксплуатацию.', type='hbar', unit='кв.',
                 categories=[r.name for r in rows], series=[{'name': 'Сдано квартир', 'data': [r.count for r in rows]}],
                 height=60 + 36 * max(len(rows), 1))


def developers_share(ctx: Ctx):
    data = latest('developers-distribution', ctx.city) or []
    year = _latest_year(data)
    rows = sorted((r for r in data if r.year == year), key=lambda r: -r.value)
    labels, values = [r.name for r in rows], [r.value for r in rows]
    rest = round(100 - sum(values), 1)
    if rows and rest > 0.5:
        labels.append('Остальные')
        values.append(rest)
    return _spec(f'Доли застройщиков{f", {year}" if year else ""}', '% сданных квартир.', type='donut', unit='%',
                 digits=1, labels=labels, values=values)


def _city_region_bar(endpoint, ctx, title, subtitle, keys):
    data = latest(endpoint, None) or {}
    entry = data.get(ctx.city.id)
    series = []
    if entry is not None:
        series = [{'name': name, 'data': [getattr(entry, part).get(k, 0) for k in keys]}
                  for part, name in (('city', ctx.city.name), ('region', 'Область'))]
        if not any(any(s['data']) for s in series):
            series = []
    return _spec(title, subtitle, type='bar', categories=list(keys.values()), series=series)


def construction(ctx: Ctx):
    return _city_region_bar('sections', ctx, 'Активность строительства', 'Секций жилых комплексов.', {
        'active': 'В продаже', 'under_construct': 'Строится', 'preparatory_work': 'Котлованы',
        'built': 'Построено с 2010',
    })


def lending(ctx: Ctx):
    return _city_region_bar('lending', ctx, 'Новостройки с долгосрочной оплатой', 'Число жилых комплексов.', {
        'installments': 'Рассрочка от застройщика', 'mortgagesYeOselya': 'Ипотека «єОселя»', 'credits': 'Кредит',
    })


def commissioning(ctx: Ctx):
    data = [r for r in latest('dssu', None) or [] if r.regionId == ctx.city.id]
    years = defaultdict(lambda: [0.0, 0.0, 0])
    for r in data:
        years[r.year][0] += r.allBuildings or 0
        years[r.year][1] += r.apartmentBuildings or 0
        years[r.year][2] = max(years[r.year][2], r.quarter)
    ordered = sorted(years)[-9:]
    last = f' (за {years[ordered[-1]][2]} кв.)' if ordered and years[ordered[-1]][2] < 4 else ''
    return _spec('Ввод жилья в эксплуатацию', f'Область, Госстат, млн м² в год{last}.', type='bar', unit='млн м²',
                 digits=2, categories=[str(y) for y in ordered],
                 series=[{'name': 'Всё жильё', 'data': [round(years[y][0] / 1e6, 3) for y in ordered]},
                         {'name': 'Многоквартирные', 'data': [round(years[y][1] / 1e6, 3) for y in ordered]}])


# --- Houses -----------------------------------------------------------------------------------------------

def _houses(ctx, metric):
    data = latest('houses-price-history', ctx.city, ctx.ct) or []
    region_names = {'city': ctx.city.name, 'region': 'Область'}
    field = (lambda r: _usd_uah(ctx, r.medianUsd, r.medianUah)) if metric == 'price' else \
        (lambda r: _usd_uah(ctx, r.medianM2Usd, r.medianM2Uah))
    return data, _series_by(data, lambda r: r.regionType, lambda r: r.date, field,
                            name=lambda g: region_names.get(g, g), order=['city', 'region'])


def houses_price(ctx: Ctx):
    data, series = _houses(ctx, 'price')
    return _spec(f'Дома: медианная цена{" аренды" if ctx.deal == "rent" else ""}',
                 f'{ctx.cur.upper()}{ctx.per_month}.', unit=ctx.symbol, series=series,
                 preliminary=_today(data, lambda r: r.date))


def houses_m2(ctx: Ctx):
    data, series = _houses(ctx, 'm2')
    return _spec('Дома: медианная цена м²', f'{ctx.cur.upper()}{ctx.per_month}.', unit=ctx.symbol, series=series,
                 digits=0 if ctx.cur == 'uah' or ctx.deal == 'sale' else 2,
                 preliminary=_today(data, lambda r: r.date))


def houses_districts(ctx: Ctx):
    data = [r for r in latest('districts-house-price', ctx.city) or [] if r.contractTypeId == ctx.ct]
    rows = sorted(data, key=lambda r: -(r.medianUsd or 0))
    when = f' на {rows[0].date:%d.%m.%Y}' if rows else ''
    return _spec('Дома: медианная цена по районам', f'USD{when}. ЛУН публикует только продажу в USD.',
                 type='hbar', unit='$', categories=[r.nameUk for r in rows],
                 series=[{'name': 'Медиана', 'data': [r.medianUsd for r in rows]}],
                 height=60 + 44 * max(len(rows), 1))


Builder = Callable[[Ctx], dict]
