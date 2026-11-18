"""The latest LUN answer of an endpoint, validated: what the dashboard's extra pages are drawn from.

lun_raw keeps an answer only when the data changed, so the newest row is LUN's current state, and most endpoints
carry their own history (monthly points) inside the answer.
"""
from collector.lun.endpoints import ENDPOINTS
from collector.models import City, LunRaw


def latest(endpoint: str, city: City | None, contract_type: int | None = None):
    """The `data` of the newest stored answer (validated with the endpoint's schema), or None if never collected."""
    e = ENDPOINTS[endpoint]
    params = e.params(city.id if e.per_city else None)
    if contract_type is not None:
        params = [p for p in params if p.get('contractTypeId') == contract_type]
    qs = LunRaw.objects.filter(endpoint=endpoint, params=params[0])
    qs = qs.filter(city=city) if e.per_city else qs.filter(city__isnull=True)
    row = qs.order_by('-fetched_at', '-id').only('payload', 'fetched_at').first()
    if row is None:
        return None
    return e.schema.model_validate(row.payload).data
