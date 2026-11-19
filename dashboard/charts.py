"""Chart specs for the extra pages (Districts, Market, Affordability, New buildings, Houses), read from the entity
tables (docs/data-model.md). Snapshot tables are shown at their latest snap_date.

Every builder takes the page context and returns a plain dict that charts.js draws:

    {title, subtitle, type: line|area|bar|hbar|donut, unit, digits, series: [{name, data}], categories,
     labels, values, preliminary: [ISO dates], empty: str | None}

line/area: data = [{x: ISO date, y}]; bar/hbar: data aligned with `categories` (optional `highlight`: the index of
the bar to stand out); donut: `labels` + `values`; scatter: data = [{x, y, label}] with `x_title`, `y_title`.
"""
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Max, QuerySet

from collector import models as m

SYMBOL = {'usd': '$', 'uah': '₴'}
ROOM = {0: 'Усі', 1: '1 кімн.', 2: '2 кімн.', 3: '3 кімн.'}  # 0 = all room counts; 4+ rooms are not shown
SHOWN_ROOMS = tuple(ROOM)
DEAL_IDS = {'sale': 1, 'rent': 2}
NO_DATA = 'Відсутні дані для вибраного міста.'
MAX_DISTRICTS = 20  # some cities have ~150 micro-districts
CLASS_NAMES = {'economy': 'Економ', 'comfort': 'Комфорт', 'business': 'Бізнес', 'premium': 'Преміум',
               'all': 'Середня по місту'}


@dataclass(frozen=True)
class Ctx:
    city: m.City
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
        return ' на місяць' if self.deal == 'rent' else ''


def _f(value) -> float | None:
    """Decimal -> float for the JSON spec; 0 is a gap (the source sends it for months without data, spring 2022)."""
    if value is None:
        return None
    value = float(value) if isinstance(value, Decimal) else value
    return value or None


def _spec(title, subtitle='', *, type='line', unit='', digits=0, series=(), categories=None, labels=None,
          values=None, preliminary=(), empty=None, height=320, **extra):
    has_data = any(any(v is not None for v in (p['y'] if isinstance(p, dict) else p for p in s['data']))
                   for s in series) if series else bool(values)
    return {
        'title': title, 'subtitle': subtitle, 'type': type, 'unit': unit, 'digits': digits,
        'series': list(series), 'categories': categories or [], 'labels': labels or [], 'values': values or [],
        'preliminary': sorted(set(preliminary)), 'empty': None if has_data else (empty or NO_DATA),
        'height': height, **extra,
    }


def _lines(rows, group, x, y, name=lambda g: str(g), order=None):
    """Line series, one per group value, sorted by x; also the ISO dates of the preliminary ("today") points."""
    groups = defaultdict(list)
    today = []
    for row in rows:
        groups[group(row)].append((x(row), _f(y(row))))
        if getattr(row, 'is_today', False):
            today.append(x(row).isoformat())
    keys = order if order is not None else sorted(groups)
    series = [{'name': name(g), 'data': [{'x': d.isoformat(), 'y': v} for d, v in sorted(groups[g])]}
              for g in keys if g in groups]
    return series, today


def _latest(qs: QuerySet, field='snap_date') -> QuerySet:
    """A snapshot table at its newest date (for the filters already applied)."""
    newest = qs.aggregate(newest=Max(field))['newest']
    return qs.filter(**{field: newest}) if newest else qs.none()


def _usd_uah(ctx, usd, uah):
    return usd if ctx.cur == 'usd' else uah


def _when(rows, field='snap_date'):
    return f' на {getattr(rows[0], field):%d.%m.%Y}' if rows else ''


# --- Districts --------------------------------------------------------------------------------------------

def flat_districts(ctx: Ctx):
    rows = list(_latest(m.DistrictPrice.objects.filter(
        district__city=ctx.city, contract_type=ctx.ct, room_count=ctx.room)).select_related('district'))
    split = {'all': '', 'renovated': '_renovated', 'not': '_not_renovated'}[ctx.repair]

    def value(r):
        """UAH median, converted with the rate; the short shape (micro-districts, no rate) has USD of its own."""
        uah = getattr(r, ('median' if ctx.metric == 'price' else 'median_m2') + split + '_uah')
        if ctx.cur == 'uah':
            return _f(uah)
        if uah is not None and r.usd_to_uah:
            return _f(uah / r.usd_to_uah)
        return _f(None if split else (r.median_usd if ctx.metric == 'price' else r.median_m2_usd))

    rows = sorted((r for r in rows if value(r) is not None), key=lambda r: -value(r))
    shown = rows[:MAX_DISTRICTS]
    what = 'ціна квартири' if ctx.metric == 'price' else 'ціна м²'
    repair = {'all': '', 'renovated': ', з ремонтом', 'not': ', без ремонту'}[ctx.repair]
    top = f' {MAX_DISTRICTS} найдорожчих із {len(rows)}.' if len(rows) > MAX_DISTRICTS else ''
    return _spec(
        f'{"Оренда" if ctx.deal == "rent" else "Вторинка"}: медіанна {what}, {ROOM[ctx.room]}{repair}',
        f'За районами{_when(rows)}. {ctx.cur.upper()}{ctx.per_month}.{top}',
        type='hbar', unit=ctx.symbol, categories=[r.district.name_uk for r in shown],
        series=[{'name': 'Медіана', 'data': [value(r) for r in shown]}], height=60 + 36 * max(len(shown), 1),
    )


def _average_by_district(item, ctx, title, subtitle):
    rows = list(_latest(m.DistrictAveragePrice.objects.filter(district__city=ctx.city, item=item))
                .select_related('district'))
    rows = sorted(rows, key=lambda r: -(r.avg_usd or 0))[:MAX_DISTRICTS]
    return _spec(title, subtitle + _when(rows) + '.', type='hbar', unit=ctx.symbol,
                 categories=[r.district.name_uk for r in rows],
                 series=[{'name': 'Медіана', 'data': [_f(_usd_uah(ctx, r.avg_usd, r.avg_uah)) for r in rows]}],
                 height=60 + 44 * max(len(rows), 1))


def primary_districts(ctx: Ctx):
    return _average_by_district(m.DistrictAveragePrice.Item.FLAT_M2, ctx, 'Новобудови: стартова ціна м² за районами',
                                f'Медіана стартової ціни від забудовників, {ctx.cur.upper()}')


def parking_districts(ctx: Ctx):
    return _average_by_district(m.DistrictAveragePrice.Item.PARKING, ctx, 'Паркомісце в новобудові за районами',
                                f'Медіана стартової ціни, {ctx.cur.upper()}')


# --- Market -----------------------------------------------------------------------------------------------

def exposure(ctx: Ctx):
    rows = m.ExposurePoint.objects.filter(city=ctx.city, contract_type=ctx.ct, room_count__in=SHOWN_ROOMS)
    series, today = _lines(rows, lambda r: r.room_count, lambda r: r.date, lambda r: r.days, name=ROOM.get)
    verb = 'здається' if ctx.deal == 'rent' else 'продається'
    return _spec(f'Як швидко квартира {verb}', 'Медіанний строк експозиції оголошення, днів.', unit='дн.',
                 series=series, preliminary=today)


def _bucket_label(start, end, symbol):
    def short(v):
        v = float(v)
        return f'{v / 1000:g} тис.' if v >= 1000 else f'{v:g}'
    return f'від {short(start)} {symbol}' if end is None else f'{short(start)}–{short(end)} {symbol}'


def price_distribution(ctx: Ctx):
    # one room count: their buckets have different bounds, side by side they interleave
    base = m.PriceBucket.objects.filter(city=ctx.city, contract_type=ctx.ct, room_count=ctx.room)
    rows = list(_latest(base.filter(currency=ctx.cur)))
    currency, note = ctx.cur, ''
    if not rows:  # sale is published in USD only
        rows = list(_latest(base.filter(currency='usd')))
        currency, note = 'usd', ' Продаж доступний лише в USD.' if rows else ''
    rows.sort(key=lambda r: r.price_from)
    buckets = [(r.price_from, r.price_to) for r in rows]
    counts = [r.cnt for r in rows]
    # the source sends ~80 narrow buckets with a long, almost empty tail: keep the ones holding 97% of the listings and
    # fold the rest into one "from X" bucket
    grand, running, cut = sum(counts), 0, len(buckets)
    for i, count in enumerate(counts):
        running += count
        if grand and running >= 0.97 * grand:
            cut = i + 1
            break
    if cut < len(buckets) - 1:
        buckets = buckets[:cut] + [(buckets[cut][0], None)]
        counts = counts[:cut] + [sum(counts[cut:])]
    return _spec(
        'Найпоширеніші ціни' + (' оренди' if ctx.deal == 'rent' else '') + f', {ROOM[ctx.room]}',
        f'Кількість оголошень за ціновими інтервалами{_when(rows)}.{note}', type='bar', unit='оголош.',
        categories=[_bucket_label(s, e, SYMBOL[currency]) for s, e in buckets],
        series=[{'name': ROOM[ctx.room], 'data': counts}] if rows else [], height=360,
    )


def listing_vs_deal(ctx: Ctx):
    rows = list(m.DealPricePoint.objects.filter(city=ctx.city, contract_type=ctx.ct, room_count=ctx.room))
    listing, today = _lines(rows, lambda r: 'listing', lambda r: r.date,
                            lambda r: _usd_uah(ctx, r.listing_usd, r.listing_uah))
    deal, _ = _lines(rows, lambda r: 'deal', lambda r: r.date, lambda r: _usd_uah(ctx, r.deal_usd, r.deal_uah))
    return _spec(
        f'Ціна в оголошенні і ціна угоди, {ROOM[ctx.room]}',
        f'Медіани за даними рієлторів, {ctx.cur.upper()}{ctx.per_month}. Різниця — торг.', unit=ctx.symbol,
        series=[{**s, 'name': name} for s, name in ((listing[0], 'В оголошенні'), (deal[0], 'Угода'))] if rows else [],
        preliminary=today,
    )


# --- Affordability ----------------------------------------------------------------------------------------

def salary_history(ctx: Ctx):
    rows = m.AffordabilityPoint.objects.filter(city=ctx.city, contract_type=ctx.ct, room_count__in=SHOWN_ROOMS)
    if ctx.deal == 'rent':
        title, subtitle, unit, digits = ('Частка зарплати, що йде на оренду',
                                         'Медіанна оренда у % від медіанної зарплати (work.ua).', '%', 0)
    else:
        title, subtitle, unit, digits = ('Ціна квартири в роках зарплати',
                                         'Скільки років відкладати всю медіанну зарплату (work.ua).', 'р.', 1)
    series, today = _lines(rows, lambda r: r.room_count, lambda r: r.date, lambda r: r.value, name=ROOM.get)
    return _spec(title, subtitle, unit=unit, digits=digits, series=series, preliminary=today)


def salary_positions(ctx: Ctx):
    rows = list(_latest(m.ProfessionAffordability.objects.filter(
        city=ctx.city, contract_type=ctx.ct, room_count__in=SHOWN_ROOMS)))
    salary = {r.profession_uk: r.salary or 0 for r in rows}
    professions = sorted(salary, key=salary.get)
    value = {(r.room_count, r.profession_uk): _f(r.value) for r in rows}
    rooms = sorted({r.room_count for r in rows})
    rent = ctx.deal == 'rent'
    return _spec(
        'Частка зарплати на оренду за професіями' if rent else 'Ціна квартири в роках зарплати за професіями',
        'Медіанні зарплати професій за даними work.ua.', type='hbar', unit='%' if rent else 'р.',
        digits=0 if rent else 1, categories=professions,
        series=[{'name': ROOM[room], 'data': [value.get((room, p)) for p in professions]} for room in rooms],
        height=80 + 36 * max(len(professions), 1),
    )


def sale_in_rent(ctx: Ctx):
    rows = m.RentPaybackPoint.objects.filter(city=ctx.city, room_count__in=SHOWN_ROOMS)
    series, today = _lines(rows, lambda r: r.room_count, lambda r: r.date, lambda r: r.years, name=ROOM.get)
    return _spec('Ціна квартири в роках оренди', 'За скільки років оренда окупає купівлю тієї ж квартири.',
                 unit='р.', digits=1, series=series, preliminary=today)


def pets_rent(ctx: Ctx):
    row = _latest(m.PetsRentShare.objects.filter(city=ctx.city, realty_type='flat', scope='city')).first()
    return _spec(
        'Оренда з домашніми тваринами', 'Частка оголошень квартир.', type='donut', unit='%', digits=1,
        labels=['Можна', 'За домовленістю', 'Не можна', 'Не вказано'],
        values=[row.allowed, row.by_agreement, row.forbidden, row.unknown] if row else [],
        empty='Дані є лише для Києва та Львова.',
    )


# --- New buildings ----------------------------------------------------------------------------------------

def primary_classes(ctx: Ctx):
    rows = m.PrimaryClassPrice.objects.filter(city=ctx.city, scope='city')
    series, today = _lines(rows, lambda r: r.housing_class, lambda r: r.month,
                           lambda r: _usd_uah(ctx, r.avg_usd, r.avg_uah), name=CLASS_NAMES.get,
                           order=list(CLASS_NAMES))
    return _spec('Новобудови: стартова ціна м² за класами',
                 f'Медіана стартової ціни від забудовників, {ctx.cur.upper()}.', unit=ctx.symbol, series=series,
                 preliminary=today)


PARKING_ORDER = ['economy', 'comfort', 'business', 'premium']


def parking_classes(ctx: Ctx):
    rows = _latest(m.ParkingClassPrice.objects.filter(city=ctx.city))
    value = {(r.scope, r.housing_class): _f(_usd_uah(ctx, r.median_usd, r.median_uah)) for r in rows}
    return _spec('Паркомісце в новобудові за класом будинку', f'Медіана стартової ціни, {ctx.cur.upper()}.',
                 type='bar', unit=ctx.symbol, categories=[CLASS_NAMES[c] for c in PARKING_ORDER],
                 series=[{'name': name, 'data': [value.get((scope, c)) for c in PARKING_ORDER]}
                         for scope, name in (('city', 'Місто'), ('region', 'Область'))
                         if any((scope, c) in value for c in PARKING_ORDER)])


def developers_ranking(ctx: Ctx):
    rows = list(_latest(m.DeveloperRank.objects.filter(city=ctx.city), 'year').order_by('-flats')[:10])
    year = rows[0].year if rows else None
    return _spec(f'Топ забудовників за зданими квартирами{f", {year}" if year else ""}',
                 'Місто та область, за сертифікатами про введення в експлуатацію.', type='hbar', unit='кв.',
                 categories=[r.name for r in rows], series=[{'name': 'Здано квартир', 'data': [r.flats for r in rows]}],
                 height=60 + 36 * max(len(rows), 1))


def developers_share(ctx: Ctx):
    rows = list(_latest(m.DeveloperShare.objects.filter(city=ctx.city), 'year').order_by('-share_pct'))
    year = rows[0].year if rows else None
    labels, values = [r.name for r in rows], [r.share_pct for r in rows]
    rest = round(100 - sum(values), 1)
    if rows and rest > 0.5:
        labels.append('Інші')
        values.append(rest)
    return _spec(f'Частки забудовників{f", {year}" if year else ""}', '% зданих квартир.', type='donut', unit='%',
                 digits=1, labels=labels, values=values)


def _city_region_bar(model, ctx, title, subtitle, fields):
    rows = {r.scope: r for r in _latest(model.objects.filter(city=ctx.city))}
    series = [{'name': name, 'data': [getattr(rows[scope], f) for f in fields]}
              for scope, name in (('city', ctx.city.name), ('region', 'Область')) if scope in rows]
    if not any(any(s['data']) for s in series):
        series = []
    return _spec(title, subtitle, type='bar', categories=list(fields.values()), series=series)


def construction(ctx: Ctx):
    return _city_region_bar(m.ConstructionStat, ctx, 'Активність будівництва', 'Секцій житлових комплексів.', {
        'on_sale': 'У продажу', 'under_construction': 'Будується', 'preparatory': 'Котловани',
        'built': 'Збудовано з 2010',
    })


def lending(ctx: Ctx):
    return _city_region_bar(m.LendingStat, ctx, 'Новобудови з довгостроковими виплатами',
                            'Кількість житлових комплексів.', {
                                'installments': 'Розтермінування від забудовника', 'mortgages': 'Іпотека «єОселя»',
                                'credits': 'Кредит',
                            })


def commissioning(ctx: Ctx):
    """quarter 0 is the State Statistics' total for the year; a year without it yet is the sum of its quarters."""
    totals, quarters = {}, defaultdict(lambda: [0.0, 0.0, 0])
    for r in m.HousingCommissioning.objects.filter(region_id=ctx.city.id):
        if r.quarter == 0:
            totals[r.year] = [r.all_m2 or 0, r.apartment_m2 or 0, 4]
        else:
            quarters[r.year][0] += r.all_m2 or 0
            quarters[r.year][1] += r.apartment_m2 or 0
            quarters[r.year][2] = max(quarters[r.year][2], r.quarter)
    years = {**quarters, **totals}
    ordered = sorted(years)[-9:]
    last = f' (за {years[ordered[-1]][2]} кв.)' if ordered and years[ordered[-1]][2] < 4 else ''
    return _spec('Введення житла в експлуатацію', f'Область, Держстат, млн м² на рік{last}.', type='bar',
                 unit='млн м²', digits=2, categories=[str(y) for y in ordered],
                 series=[{'name': 'Усе житло', 'data': [round(years[y][0] / 1e6, 3) for y in ordered]},
                         {'name': 'Багатоквартирні', 'data': [round(years[y][1] / 1e6, 3) for y in ordered]}])


# --- Houses -----------------------------------------------------------------------------------------------

def _houses(ctx, usd, uah):
    rows = m.HousePricePoint.objects.filter(city=ctx.city, contract_type=ctx.ct)
    names = {'city': ctx.city.name, 'region': 'Область'}
    return _lines(rows, lambda r: r.scope, lambda r: r.date,
                  lambda r: _usd_uah(ctx, getattr(r, usd), getattr(r, uah)), name=names.get,
                  order=['city', 'region'])


def houses_price(ctx: Ctx):
    series, today = _houses(ctx, 'median_usd', 'median_uah')
    return _spec(f'Будинки: медіанна ціна{" оренди" if ctx.deal == "rent" else ""}',
                 f'{ctx.cur.upper()}{ctx.per_month}.', unit=ctx.symbol, series=series, preliminary=today)


def houses_m2(ctx: Ctx):
    series, today = _houses(ctx, 'median_m2_usd', 'median_m2_uah')
    return _spec('Будинки: медіанна ціна м²', f'{ctx.cur.upper()}{ctx.per_month}.', unit=ctx.symbol, series=series,
                 digits=0 if ctx.cur == 'uah' or ctx.deal == 'sale' else 2, preliminary=today)


def houses_districts(ctx: Ctx):
    rows = list(_latest(m.HouseDistrictPrice.objects.filter(district__city=ctx.city, contract_type=ctx.ct))
                .select_related('district'))
    rows.sort(key=lambda r: -(r.median_usd or 0))
    return _spec('Будинки: медіанна ціна за районами', f'USD{_when(rows)}. Доступний лише продаж у USD.',
                 type='hbar', unit='$', categories=[r.district.name_uk for r in rows],
                 series=[{'name': 'Медіана', 'data': [_f(r.median_usd) for r in rows]}],
                 height=60 + 44 * max(len(rows), 1))


# --- Cities: every city side by side, at the latest monthly point (the same date for all of them) -----------

BIG_CITIES = ('kyiv', 'lviv', 'odesa', 'kharkiv', 'dnipro')


def _monthly_latest(qs, field='snap_date') -> list:
    return list(_latest(qs.filter(is_today=False), field).select_related('city'))


def _compared(ctx) -> list[m.City]:
    """The selected city and the five biggest markets, for the dynamics charts."""
    cities = {c.slug: c for c in m.City.objects.filter(slug__in=BIG_CITIES)}
    return [ctx.city] + [cities[s] for s in BIG_CITIES if s in cities and s != ctx.city.slug]


def _ranking(ctx, values: dict, title, subtitle, *, unit, digits=0):
    """values: {City: number}; bars sorted from the highest, the selected city highlighted."""
    rows = sorted(((c, v) for c, v in values.items() if v is not None), key=lambda r: -r[1])
    return _spec(title, subtitle, type='hbar', unit=unit, digits=digits, categories=[c.name for c, _ in rows],
                 series=[{'name': title.split(':')[0], 'data': [round(v, 2) for _, v in rows]}],
                 highlight=next((i for i, (c, _) in enumerate(rows) if c.pk == ctx.city.pk), None),
                 height=60 + 28 * max(len(rows), 1), wide=False, empty='Немає даних.')


def _flat_prices(ctx, contract_type, field):
    rows = _monthly_latest(m.FlatPricePoint.objects.filter(contract_type=contract_type, room_count=ctx.room))
    return {r.city: _f(getattr(r, field)) for r in rows}, rows


def cities_m2(ctx: Ctx):
    values, rows = _flat_prices(ctx, ctx.ct, f'median_m2_{ctx.cur}')
    return _ranking(ctx, values, f'Ціна м²: {"оренда" if ctx.deal == "rent" else "продаж"}',
                    f'Медіана{_when(rows)}, {ctx.cur.upper()}{ctx.per_month}.', unit=ctx.symbol,
                    digits=2 if ctx.deal == 'rent' and ctx.cur == 'usd' else 0)


def cities_price(ctx: Ctx):
    values, rows = _flat_prices(ctx, ctx.ct, f'median_{ctx.cur}')
    return _ranking(ctx, values, f'Ціна квартири: {"оренда" if ctx.deal == "rent" else "продаж"}, {ROOM[ctx.room]}',
                    f'Медіана{_when(rows)}, {ctx.cur.upper()}{ctx.per_month}.', unit=ctx.symbol)


def _yields(rows) -> dict:
    """{(city, date): gross rental yield, %}: a year of the median rent over the median sale price."""
    price = defaultdict(dict)
    for r in rows:
        price[(r.city, r.snap_date)][r.contract_type] = r.median_usd
    return {key: float(p[2] * 12 / p[1] * 100) for key, p in price.items() if p.get(1) and p.get(2)}


def cities_yield(ctx: Ctx):
    rows = _monthly_latest(m.FlatPricePoint.objects.filter(room_count=ctx.room))
    values = {city: v for (city, _), v in _yields(rows).items()}
    return _ranking(ctx, values, f'Дохідність оренди: {ROOM[ctx.room]}',
                    f'Річна оренда у % від ціни купівлі{_when(rows)}, до податків і простою.', unit='%', digits=1)


def cities_sale_rent(ctx: Ctx):
    sale, rows = _flat_prices(ctx, 1, f'median_{ctx.cur}')
    rent, _ = _flat_prices(ctx, 2, f'median_{ctx.cur}')
    points = {c: {'x': sale[c], 'y': rent[c], 'label': c.name} for c in sale if sale[c] and rent.get(c)}
    series = [{'name': 'Міста', 'data': [p for c, p in points.items() if c.pk != ctx.city.pk]}]
    if ctx.city in points:
        series.append({'name': ctx.city.name, 'data': [points[ctx.city]]})
    return _spec(f'Купівля проти оренди: {ROOM[ctx.room]}',
                 f'Медіани{_when(rows)}, {ctx.cur.upper()}. Що вище точка, то дорожча оренда відносно ціни купівлі.',
                 type='scatter', unit=ctx.symbol, series=series if points else [], x_title='Ціна купівлі',
                 y_title='Оренда на місяць', height=460, wide=True, empty='Немає даних.')


def cities_affordability(ctx: Ctx):
    rows = _monthly_latest(m.AffordabilityPoint.objects.filter(contract_type=ctx.ct, room_count=ctx.room), 'date')
    values = {r.city: _f(r.value) for r in rows}
    if ctx.deal == 'rent':
        return _ranking(ctx, values, f'Оренда у % зарплати: {ROOM[ctx.room]}',
                        f'Медіанна оренда до медіанної зарплати міста{_when(rows, "date")}.', unit='%')
    return _ranking(ctx, values, f'Ціна квартири в роках зарплати: {ROOM[ctx.room]}',
                    f'Скільки років відкладати всю медіанну зарплату{_when(rows, "date")}.', unit='р.', digits=1)


def cities_m2_dynamics(ctx: Ctx):
    cities = _compared(ctx)
    rows = m.FlatPricePoint.objects.filter(city__in=cities, contract_type=ctx.ct, room_count=1).select_related('city')
    series, today = _lines(rows, lambda r: r.city, lambda r: r.snap_date, lambda r: getattr(r, f'median_m2_{ctx.cur}'),
                           name=lambda c: c.name, order=cities)
    return _spec(f'Ціна м² у динаміці: {"оренда" if ctx.deal == "rent" else "продаж"}',
                 f'Вибране місто і п’ять найбільших ринків, медіана, {ctx.cur.upper()}{ctx.per_month}.',
                 unit=ctx.symbol, digits=2 if ctx.deal == 'rent' and ctx.cur == 'usd' else 0, series=series,
                 preliminary=today, height=380)


def cities_yield_dynamics(ctx: Ctx):
    cities = _compared(ctx)
    rows = (m.FlatPricePoint.objects.filter(city__in=cities, room_count=ctx.room, is_today=False)
            .select_related('city'))
    by_city = defaultdict(list)
    for (city, date), value in _yields(rows).items():
        by_city[city].append({'x': date.isoformat(), 'y': round(value, 2)})
    series = [{'name': c.name, 'data': sorted(by_city[c], key=lambda p: p['x'])} for c in cities if by_city[c]]
    return _spec(f'Дохідність оренди в динаміці: {ROOM[ctx.room]}', 'Річна оренда у % від ціни купівлі, щомісяця.',
                 unit='%', digits=1, series=series, height=380)


Builder = Callable[[Ctx], dict]
