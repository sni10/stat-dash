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
