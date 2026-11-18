from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from collector.models import City

from . import queries
from .queries import CURRENCIES, DEALS, BadFilter
from .templatetags.dash import money, num, pct

DEAL_LABELS = {'sale': 'Продажа', 'rent': 'Аренда'}
CURRENCY_LABELS = {'usd': 'USD', 'uah': 'UAH'}
METRICS = [('price', 'Цена объекта'), ('m2', 'Цена м²')]


def _context(filters, page, **extra):
    return {
        'page': page,
        'f': filters,
        # the sidebar keeps city, deal and currency when switching pages
        'nav_query': urlencode({'city': filters.city.slug, 'deal': filters.deal, 'cur': filters.cur}),
        'cities': (City.objects.filter(enabled=True) | City.objects.filter(pk=filters.city.pk)).distinct(),
        'deals': [(k, DEAL_LABELS[k]) for k in DEALS],
        'currencies': [(c, CURRENCY_LABELS[c]) for c in CURRENCIES],
        **extra,
    }


def _filters_or_400(request):
    try:
        return queries.parse_filters(request.GET), None
    except BadFilter as exc:
        return None, HttpResponseBadRequest(str(exc))


def _prices_url(filters, **overrides) -> str:
    return reverse('api-prices') + '?' + urlencode(filters.as_query(**overrides))


def _tiles(kpi: dict, cur: str) -> list[dict]:
    when = f'{"предварительно, " if kpi["preliminary"] else ""}на {kpi["date"]:%d.%m.%Y}'
    return [
        {'label': 'Медиана цены м²', 'value': money(kpi['price_m2'], cur), 'hint': when, 'change': None},
        {'label': 'Изменение за месяц', 'value': pct(kpi['m2_mom']),
         'hint': f'к {kpi["month_ago"]:%d.%m.%Y}' if kpi['month_ago'] else 'нет точки месяц назад', 'change': None},
        {'label': 'Изменение за год', 'value': pct(kpi['m2_yoy']),
         'hint': f'к {kpi["year_ago"]:%d.%m.%Y}' if kpi['year_ago'] else 'нет точки год назад', 'change': None},
        {'label': 'Объявлений', 'value': num(kpi['count']), 'hint': 'все комнатности',
         'change': kpi['count_mom'], 'change_hint': 'к прошлому месяцу'},
    ]


@login_required
def overview(request):
    filters, error = _filters_or_400(request)
    if error:
        return error
    kpi = queries.overview(filters)
    return render(request, 'dashboard/overview.html', _context(
        filters, 'overview', heading_text=f'Обзор · {filters.city.name}', kpi=kpi, tiles=_tiles(kpi, filters.cur) if kpi else [],
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
    return render(request, 'dashboard/rooms.html', _context(
        filters, 'rooms', heading_text=f'По комнатности · {filters.city.name}', metric=metric, metrics=METRICS, period=True,
        chart_url=_prices_url(filters, **({'rooms': '1'} if metric == 'm2' else {})),
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
