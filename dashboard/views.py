from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from collector.models import City, LunRaw

from . import charts, queries
from .queries import CURRENCIES, DEALS, BadFilter
from .templatetags.dash import money, num, pct

DEAL_LABELS = {'sale': 'Продаж', 'rent': 'Оренда'}
CURRENCY_LABELS = {'usd': 'USD', 'uah': 'UAH'}
METRICS = [('price', 'Ціна об’єкта'), ('m2', 'Ціна м²')]
REPAIRS = [('all', 'Усі'), ('renovated', 'З ремонтом'), ('not', 'Без ремонту')]
STAGE1_ENDPOINTS = ('flat-price-history', 'price')  # collected since stage 1; the pages below need the others
NOT_COLLECTED = ('Ці дані по місту ще не зібрані. Вони з’являться після найближчого збору '
                 '(понеділок 04:17) або після ручного запуску collect_lun.')

# Pages built from the other endpoints (dashboard/charts.py): filters shown and cards, in order
PAGES = {
    'districts': {
        'title': 'Райони', 'filters': ('deal', 'cur', 'room', 'repair', 'metric'), 'rooms': (1, 2, 3),
        'cards': (charts.flat_districts, charts.primary_districts, charts.parking_districts),
    },
    'market': {
        'title': 'Ринок', 'filters': ('deal', 'cur', 'room'), 'rooms': (1, 2, 3),
        'cards': (charts.exposure, charts.price_distribution, charts.listing_vs_deal),
    },
    'affordability': {
        'title': 'Доступність', 'filters': ('deal',),
        'cards': (charts.salary_history, charts.salary_positions, charts.sale_in_rent, charts.pets_rent),
    },
    'primary': {
        'title': 'Новобудови', 'filters': ('cur',),
        'cards': (charts.primary_classes, charts.developers_ranking, charts.developers_share, charts.parking_classes,
                  charts.construction, charts.lending, charts.commissioning),
    },
    'houses': {
        'title': 'Будинки', 'filters': ('deal', 'cur'),
        'cards': (charts.houses_price, charts.houses_m2, charts.houses_districts),
    },
}


def _group(name, label, options, value):
    return {'name': name, 'label': label, 'options': options, 'value': value}


def _context(filters, page, groups, **extra):
    return {
        'page': page,
        'f': filters,
        # the sidebar keeps city, deal and currency when switching pages
        'nav_query': urlencode({'city': filters.city.slug, 'deal': filters.deal, 'cur': filters.cur}),
        'cities': City.objects.order_by('name'),  # all cities, collected or not; one without data says so
        'filter_groups': groups,
        **extra,
    }


def _deal_cur(filters, which=('deal', 'cur')):
    groups = []
    if 'deal' in which:
        groups.append(_group('deal', 'Угода', [(k, DEAL_LABELS[k]) for k in DEALS], filters.deal))
    if 'cur' in which:
        groups.append(_group('cur', 'Валюта', [(c, CURRENCY_LABELS[c]) for c in CURRENCIES], filters.cur))
    return groups


def _filters_or_400(request):
    try:
        return queries.parse_filters(request.GET), None
    except BadFilter as exc:
        return None, HttpResponseBadRequest(str(exc))


def _choice(request, name, options, default):
    value = request.GET.get(name) or default
    if value not in options:
        raise BadFilter(f'{name} must be one of {", ".join(map(str, options))}')
    return value


def _prices_url(filters, **overrides) -> str:
    return reverse('api-prices') + '?' + urlencode(filters.as_query(**overrides))


def _tiles(kpi: dict, cur: str) -> list[dict]:
    when = f'{"попередньо, " if kpi["preliminary"] else ""}на {kpi["date"]:%d.%m.%Y}'
    return [
        {'label': 'Медіана ціни м²', 'value': money(kpi['price_m2'], cur), 'hint': when, 'change': None},
        {'label': 'Зміна за місяць', 'value': pct(kpi['m2_mom']),
         'hint': f'до {kpi["month_ago"]:%d.%m.%Y}' if kpi['month_ago'] else 'немає точки місяць тому', 'change': None},
        {'label': 'Зміна за рік', 'value': pct(kpi['m2_yoy']),
         'hint': f'до {kpi["year_ago"]:%d.%m.%Y}' if kpi['year_ago'] else 'немає точки рік тому', 'change': None},
        {'label': 'Оголошень', 'value': num(kpi['count']), 'hint': '1–3 кімн.',
         'change': kpi['count_mom'], 'change_hint': 'до минулого місяця'},
    ]


@login_required
def overview(request):
    filters, error = _filters_or_400(request)
    if error:
        return error
    kpi = queries.overview(filters)
    return render(request, 'dashboard/overview.html', _context(
        filters, 'overview', _deal_cur(filters), heading_text=f'Огляд · {filters.city.name}', kpi=kpi,
        tiles=_tiles(kpi, filters.cur) if kpi else [],
        # m² is the same for every room count: one room's series is the city's
        chart_url=_prices_url(filters, rooms='1', **{'from': '', 'to': ''}),
    ))


@login_required
def rooms(request):
    filters, error = _filters_or_400(request)
    if error:
        return error
    metric = request.GET.get('metric') or 'price'
    if metric not in dict(METRICS):
        return HttpResponseBadRequest('metric must be price or m2')
    groups = _deal_cur(filters) + [_group('metric', 'Показник', METRICS, metric)]
    return render(request, 'dashboard/rooms.html', _context(
        filters, 'rooms', groups, heading_text=f'За кімнатністю · {filters.city.name}', metric=metric, period=True,
        chart_url=_prices_url(filters, **({'rooms': '1'} if metric == 'm2' else {})),
    ))


@login_required
def lun_page(request, page):
    """Districts, Market, Affordability, New buildings, Houses: cards drawn from the entity tables."""
    conf = PAGES[page]
    try:
        filters = queries.parse_filters(request.GET)
        room_options = conf.get('rooms', (1,))
        room = int(_choice(request, 'room', [str(r) for r in room_options], str(room_options[0])))
        repair = _choice(request, 'repair', dict(REPAIRS), 'all')
        metric = _choice(request, 'metric', dict(METRICS), 'price')
    except BadFilter as exc:
        return HttpResponseBadRequest(str(exc))
    ctx = charts.Ctx(filters.city, filters.deal, filters.cur, room, repair, metric)
    groups = _deal_cur(filters, conf['filters'])
    if 'room' in conf['filters']:
        groups.append(_group('room', 'Кімнат', [(str(r), charts.ROOM[r].replace(' кімн.', '')) for r in room_options],
                             str(room)))
    if 'repair' in conf['filters']:
        groups.append(_group('repair', 'Ремонт', REPAIRS, repair))
    if 'metric' in conf['filters']:
        groups.append(_group('metric', 'Показник', METRICS, metric))
    specs = [build(ctx) for build in conf['cards']]
    # "no data" only once the source was asked: before the first collection of these endpoints say so
    collected = LunRaw.objects.filter(city=filters.city).exclude(endpoint__in=STAGE1_ENDPOINTS).exists()
    for spec in specs:
        spec['wide'] = spec['type'] in ('line', 'area') or len(spec['categories']) > 8
        if spec['empty'] and not collected:
            spec['empty'] = NOT_COLLECTED
    return render(request, 'dashboard/cards.html', _context(
        filters, page, groups, heading_text=f'{conf["title"]} · {filters.city.name}', title=conf['title'],
        specs=specs,
    ))


def api_login_required(view):
    """JSON endpoints answer 401 instead of redirecting to the login page."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'authentication required'}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _api(request, build):
    try:
        f = queries.parse_filters(request.GET)
    except BadFilter as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    meta = {'city': f.city.slug, 'deal': f.deal, 'cur': f.cur, 'rooms': list(f.rooms)}
    return JsonResponse({**meta, **build(f)})


@api_login_required
def api_prices(request):
    """/api/prices?city=odesa&deal=sale&rooms=1,2&from=YYYY-MM&to=YYYY-MM&cur=usd: every point of the series."""
    return _api(request, lambda f: {'points': queries.price_points(f)})


@api_login_required
def api_monthly(request):
    """/api/monthly with the same params: the monthly aggregate (v_price_monthly, no "today" point)."""
    return _api(request, lambda f: {'rows': queries.monthly_rows(f)})
