"""Synthetic LUN payloads in the real response shape. Real LUN data is not stored in this public repo."""
import datetime as dt

MONTHLY_DATES = [dt.date(2025, m, 24) for m in range(1, 13)]


def flat_point(city_id, contract_type, room, date, *, today=False, m2_usd=1000.0, count=100):
    return {
        'cityId': city_id,
        'contractType': contract_type,
        'roomCount': room,
        'medianUah': m2_usd * 40 * 45 * room,
        'medianM2Uah': m2_usd * 40,
        'count': count,
        'date': date.isoformat(),
        'isToday': today,
        'medianUsd': m2_usd * 45 * room,
        'medianM2Usd': m2_usd,
        'diffM1': None,
        'diffM6': None,
        'diffYear': None,
    }


def flat_price_history(city_id=115, contract_type=1, *, dates=MONTHLY_DATES, rooms=(1, 2, 3, 4),
                       today=dt.date(2026, 1, 10), m2_usd=1000.0):
    data = [flat_point(city_id, contract_type, r, d, m2_usd=m2_usd + i) for i, d in enumerate(dates) for r in rooms]
    if today:
        data += [flat_point(city_id, contract_type, r, today, today=True, m2_usd=m2_usd + 99) for r in rooms]
    return {'status': 'success', 'data': data}


def price_item(city_id=115, month=dt.date(2025, 12, 1), label=None, today=False):
    return {
        'cityId': city_id, 'averageUah': 52700, 'averageUsd': 1170, 'label': label, 'count': 71,
        'monthDate': month.isoformat(), 'isToday': today, 'diffM1': 0.01, 'diffM6': 0.02, 'diffYear': 0.1,
    }


def price(city_id=115):
    return {
        'status': 'success',
        'data': {
            'cityClasses': [price_item(city_id, label='комфорт'), price_item(city_id, label='бізнес', today=True)],
            'regionClasses': [price_item(city_id, label='комфорт')],
            'cityAvg': [price_item(city_id)],
            'regionAvg': [price_item(city_id)],
        },
    }


class FakeClient:
    """Stands in for LunClient: answers from a dict keyed by (endpoint, contractTypeId or None)."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        answer = self.answers[(endpoint, params.get('contractTypeId'))]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self):
        pass


class ByCityClient(FakeClient):
    """Healthy answers for whatever city is asked."""

    def __init__(self):
        super().__init__({})

    def get(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        return answers(params['cityId'])[(endpoint, params.get('contractTypeId'))]


SALE = ('flat-price-history', 1)
RENT = ('flat-price-history', 2)
PRICE = ('price', None)


def answers(city_id=115):
    """Healthy answers for one city; tests replace single entries (SALE, RENT, PRICE)."""
    return {
        SALE: flat_price_history(city_id, 1),
        RENT: flat_price_history(city_id, 2, m2_usd=8.0),
        PRICE: price(city_id),
    }


# --- the other endpoints: small synthetic answers in LUN's shape ---------------------------------------------

CORE = ('flat-price-history', 'price')  # what the stage 1 tests collect
DISTRICTS = {11: 'Київський', 12: 'Хаджибейський', 13: 'Приморський', 14: 'Пересипський'}
TODAY_ISO = '2026-01-10T00:00:00.000Z'
RATE = 40.0  # UAH per USD in the synthetic data


def _ok(data):
    return {'status': 'success', 'data': data}


def _months(n=6):
    return [dt.date(2025, m, 24) for m in range(13 - n, 13)]


def median_exposure(city_id=115):
    data = []
    for ct in (1, 2):
        for room in (None, 1, 2, 3):
            for i, d in enumerate(_months()):
                data.append({'cityId': city_id, 'dateStr': d.isoformat(), 'isToday': False, 'contractType': ct,
                             'roomCount': room, 'exposure': 60 + i + (room or 0) - 30 * (ct == 2), 'count': 100})
    return _ok(data)


def market_districts(city_id=115):
    data = []
    for district, name in DISTRICTS.items():
        for ct in (1, 2):
            for room in (1, 2, 3):
                base = (district - 10) * 10000 * room if ct == 1 else (district - 10) * 100 * room
                uah = base * RATE
                data.append({
                    'cityId': city_id, 'districtId': district, 'districtName': name, 'contractTypeId': ct,
                    'roomCount': room, 'median': str(uah), 'medianRenovated': str(uah * 1.2),
                    'medianNotRenovated': str(uah * 0.9), 'medianM2Total': str(uah / 40),
                    'medianM2TotalRenovated': str(uah * 1.2 / 40), 'medianM2TotalNotRenovated': str(uah * 0.9 / 40),
                    'count': 100 * district, 'usdToUah': str(RATE), 'date': TODAY_ISO,
                })
    return _ok(data)


def price_distribution(city_id=115):
    data = []
    for ct, currency, step in ((1, 1, 10000), (2, 1, 100), (2, 2, 4000)):
        for room in (1, 2, 3):
            for i in range(5):
                data.append({'roomCount': room, 'currencyId': currency, 'contractTypeId': ct, 'priceStart': i * step,
                             'priceEnd': (i + 1) * step if i < 4 else None, 'count': (i + 1) * room,
                             'date': TODAY_ISO})
    return _ok(data)


def rieltor(city_id=115):
    data = []
    for ct in (1, 2):
        for room in (1, 2, 3, 4):
            for d in _months():
                usd = 40000.0 * room if ct == 1 else 300.0 * room
                data.append({'cityId': city_id, 'contractType': ct, 'roomCount': room, 'dateStr': d.isoformat(),
                             'isToday': False, 'price': usd * RATE, 'dealPrice': usd * 0.9 * RATE,
                             'priceUsd': usd, 'dealPriceUsd': usd * 0.9})
    return _ok(data)


def salary_history(city_id=115):
    data = []
    for ct in (1, 2):
        for room in (1, 2, 3):
            for m in range(7, 13):
                data.append({'cityId': city_id, 'contractTypeId': ct, 'roomCount': room,
                             'date': f'2025-{m:02d}-01T00:00:00.000Z', 'isToday': False,
                             'value': str(6.0 + room if ct == 1 else 30 + 10 * room), 'price': '1', 'salary': '30000'})
    return _ok(data)


def salary_positions(city_id=115):
    return _ok([
        {'cityId': city_id, 'contractTypeId': ct, 'roomCount': room, 'date': TODAY_ISO, 'nameUa': name,
         'value': (5.0 + i) * room if ct == 1 else 40.0 + i, 'salary': 25000.0 + 1000 * i}
        for ct in (1, 2) for room in (1, 2, 3) for i, name in enumerate(['Кухар', 'Водій', 'Касир'])
    ])


def sale_in_rent(city_id=115):
    return _ok([{'cityId': city_id, 'roomCount': room, 'date': d.isoformat(), 'isToday': False,
                 'value': 15.0 + room} for room in (1, 2, 3) for d in _months()])


def houses_price_history(city_id=115, contract_type=1):
    return _ok([
        {'cityId': city_id, 'contractTypeId': contract_type, 'regionType': region, 'date': d.isoformat(),
         'isToday': False, 'medianUah': 100000.0 * RATE, 'medianUsd': 100000.0 if region == 'city' else 50000.0,
         'medianM2Uah': 800.0 * RATE, 'medianM2Usd': 800.0, 'area': 120.0, 'count': 300}
        for region in ('city', 'region') for d in _months()
    ])


def districts_house_price(city_id=115):
    return _ok([{'cityId': city_id, 'districtId': k, 'nameUk': name, 'contractTypeId': 1, 'date': TODAY_ISO,
                 'medianUsd': 100000.0 + k, 'medianM2Usd': 900.0, 'area': 150.0, 'count': 10}
                for k, name in DISTRICTS.items()])


def average_by_district(city_id=115, usd=1500.0):
    return _ok([{'cityId': city_id, 'key': k, 'label': {'uk': name, 'en': name}, 'averageUah': (usd + k) * RATE,
                 'averageUsd': usd + k, 'count': 5, 'month': TODAY_ISO} for k, name in DISTRICTS.items()])


def parking_classes(city_id=115):
    return _ok([{'classId': c, 'regionType': region, 'date': TODAY_ISO, 'count': 3, 'medianUah': 15000.0 * c * RATE,
                 'medianUsd': 15000.0 * c} for c in (1, 2, 3, 4) for region in ('city', 'region')])


def developers_ranking(city_id=115):
    return _ok([{'cityId': city_id, 'year': year, 'place': str(i + 1), 'name': f'Dev {i + 1}', 'count': 1000 - 100 * i}
                for year in (2024, 2025) for i in range(3)])


def developers_distribution(city_id=115):
    return _ok([{'cityId': city_id, 'year': year, 'name': f'Dev {i + 1}', 'value': str(30 - 10 * i)}
                for year in (2024, 2025) for i in range(3)])


def dssu():
    """Quarters 1-4 and, for finished years, quarter 0 = the year's total (as State Statistics sends it)."""
    return _ok([{'year': y, 'quarter': q, 'regionId': r, 'allBuildings': 100000.0 * (q or 10),
                 'apartmentBuildings': 50000.0 * (q or 10)}
                for y in (2025, 2026) for q in (0, 1, 2, 3, 4) for r in (115, 10000) if (y, q) not in ((2026, 0), (2026, 4))])


def city_region_counts(**counts):
    return _ok({'115': {'city': counts, 'region': {k: v * 2 for k, v in counts.items()}}, '1': {'city': {}, 'region': {}}})


def pets_rent():
    return _ok([{'cityId': 1, 'contractTypeId': 2, 'realtyType': 'flat', 'regionType': 'city', 'count': 100,
                 'yesPercent': 20.0, 'somePercent': 30.0, 'noPercent': 10.0, 'unknownPercent': 40.0}])


def all_answers(city_id=115):
    """Healthy answers for every endpoint of the registry, one city."""
    return {
        **answers(city_id),
        ('median-exposure', None): median_exposure(city_id),
        ('market-districts', None): market_districts(city_id),
        ('price-distribution', None): price_distribution(city_id),
        ('rieltor', None): rieltor(city_id),
        ('salary-history', None): salary_history(city_id),
        ('salary-positions', None): salary_positions(city_id),
        ('sale-in-rent-history', None): sale_in_rent(city_id),
        ('houses-price-history', 1): houses_price_history(city_id, 1),
        ('houses-price-history', 2): houses_price_history(city_id, 2),
        ('districts-house-price', None): districts_house_price(city_id),
        ('districts', None): average_by_district(city_id),
        ('parking-districts', None): average_by_district(city_id, usd=20000.0),
        ('parking-classes', None): parking_classes(city_id),
        ('developers-ranking', None): developers_ranking(city_id),
        ('developers-distribution', None): developers_distribution(city_id),
        ('dssu', None): dssu(),
        ('lending', None): city_region_counts(installments=37, mortgagesYeOselya=7, credits=1),
        ('sections', None): city_region_counts(active=220, under_construct=79, preparatory_work=7, built=896),
        ('pets-rent', None): pets_rent(),
    }


class AllByCityClient(FakeClient):
    """Healthy answers of every endpoint for whatever city is asked."""

    def __init__(self):
        super().__init__({})

    def get(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        return all_answers(params.get('cityId', 115))[(endpoint, params.get('contractTypeId'))]
