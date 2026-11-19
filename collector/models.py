"""Tables of the spec ("Модель данных"): city, lun_raw, lun_price_snapshot, collect_run."""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ContractType(models.IntegerChoices):
    SALE = 1, 'sale'
    RENT = 2, 'rent'


class City(models.Model):
    """A LUN city. `id` is LUN's cityId; only enabled cities are collected."""

    id = models.IntegerField(primary_key=True, help_text='LUN cityId')
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'city'
        ordering = ['id']
        verbose_name_plural = 'cities'

    def __str__(self):
        return self.slug


class LunRaw(models.Model):
    """A raw LUN response. A new row only when the data changed (hash without the floating "today" point)."""

    fetched_at = models.DateTimeField(default=timezone.now)
    endpoint = models.TextField()
    city = models.ForeignKey(City, on_delete=models.PROTECT, null=True, blank=True)  # None: global endpoint
    params = models.JSONField()
    payload_hash = models.CharField(max_length=64)
    payload = models.JSONField()

    class Meta:
        db_table = 'lun_raw'
        indexes = [models.Index(fields=['endpoint', 'city', '-fetched_at'], name='lun_raw_lookup')]
        verbose_name = 'raw response'

    def __str__(self):
        return f'{self.endpoint} {self.params} @ {self.fetched_at:%Y-%m-%d %H:%M}'


class FlatPricePoint(models.Model):
    """One point of flat-price-history: a date x city x contract type x room count.

    Monthly points (the 24th) plus one floating "today" point per city x contract type (is_today), replaced on
    every collection. Written by collector.service with INSERT ... ON CONFLICT, not through the ORM.
    The other endpoints' tables are below; docs/data-model.md has the whole model.
    """

    pk = models.CompositePrimaryKey('snap_date', 'city', 'contract_type', 'room_count')
    snap_date = models.DateField()
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()
    median_uah = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    median_usd = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    median_m2_uah = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    median_m2_usd = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    cnt = models.IntegerField(null=True)
    is_today = models.BooleanField(default=False, db_default=False)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = 'flat_price_point'
        verbose_name = 'flat price point'


class CollectRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running'
        OK = 'ok'
        PARTIAL = 'partial'  # some requests or responses failed, the rest is stored
        FAILED = 'failed'

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status)
    rows_upserted = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = 'collect_run'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.started_at:%Y-%m-%d %H:%M} {self.status}'


# --- LUN entities: one table per endpoint (docs/data-model.md) ---------------------------------------------------
# Written by collector/parsers.py with bulk upserts on the natural key, which is each table's one unique constraint
# (natural_key()). `room_count = 0` means all room counts.

class Scope(models.TextChoices):
    CITY = 'city'
    REGION = 'region'  # the oblast around the city


class HousingClass(models.TextChoices):
    ECONOMY = 'economy'
    COMFORT = 'comfort'
    BUSINESS = 'business'
    PREMIUM = 'premium'
    ALL = 'all'  # the city / region average


def _money():
    return models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)


def _number():
    return models.FloatField(null=True, blank=True)


def _count():
    return models.IntegerField(null=True, blank=True)


def _key(table, *fields):
    return [models.UniqueConstraint(fields=fields, name=f'{table}_natural_key')]


def natural_key(model) -> tuple[str, ...]:
    return tuple(model._meta.constraints[0].fields)


class District(models.Model):
    """A city district as LUN numbers it: the same ids in every endpoint of the city."""

    class Kind(models.TextChoices):
        DISTRICT = 'district'
        SETTLEMENT = 'settlement'  # a town next to the city (Kyiv's new-building answer: isCity)
        MICRODISTRICT = 'microdistrict'  # ids >= 10 000 000 (Ivano-Frankivsk)

    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name='districts')
    kind = models.CharField(max_length=16, choices=Kind, default=Kind.DISTRICT)
    lun_id = models.BigIntegerField()
    name_uk = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'district'
        ordering = ['city', 'kind', 'name_uk']
        constraints = _key('district', 'city', 'kind', 'lun_id')

    def __str__(self):
        return f'{self.city.slug}: {self.name_uk}'


# Series: LUN sends the history; the floating "today" point is replaced on every collection

class HousePricePoint(models.Model):
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    scope = models.CharField(max_length=8, choices=Scope)
    date = models.DateField()
    median_uah = _money()
    median_usd = _money()
    median_m2_uah = _money()
    median_m2_usd = _money()
    area = _number()
    cnt = _count()
    is_today = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'house_price_point'
        constraints = _key('house_price_point', 'city', 'contract_type', 'scope', 'date')


class ExposurePoint(models.Model):
    """Median days on the market."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()  # 0 = all room counts
    date = models.DateField()
    days = _number()
    cnt = _count()
    is_today = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exposure_point'
        constraints = _key('exposure_point', 'city', 'contract_type', 'room_count', 'date')


class DealPricePoint(models.Model):
    """The listing price next to the deal price reported by realtors (rieltor)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()
    date = models.DateField()
    listing_uah = _money()
    listing_usd = _money()
    deal_uah = _money()
    deal_usd = _money()
    listing_m2_uah = _money()
    listing_m2_usd = _money()
    deal_m2_uah = _money()
    deal_m2_usd = _money()
    is_today = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'deal_price_point'
        constraints = _key('deal_price_point', 'city', 'contract_type', 'room_count', 'date')


class AffordabilityPoint(models.Model):
    """Sale: the price in years of the median salary. Rent: the rent as % of it (salary-history)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()
    date = models.DateField()
    value = _number()
    price = _money()
    salary = _money()
    cnt = _count()
    is_today = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'affordability_point'
        constraints = _key('affordability_point', 'city', 'contract_type', 'room_count', 'date')


class RentPaybackPoint(models.Model):
    """A flat's price in years of its rent (sale-in-rent-history)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    room_count = models.PositiveSmallIntegerField()
    date = models.DateField()
    years = _number()
    is_today = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rent_payback_point'
        constraints = _key('rent_payback_point', 'city', 'room_count', 'date')


class PrimaryClassPrice(models.Model):
    """New buildings: the average starting m² price by housing class (price)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    scope = models.CharField(max_length=8, choices=Scope)
    housing_class = models.CharField(max_length=10, choices=HousingClass)
    month = models.DateField()
    avg_uah = _money()
    avg_usd = _money()
    cnt = _count()
    is_today = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'primary_class_price'
        constraints = _key('primary_class_price', 'city', 'scope', 'housing_class', 'month')


class HousingCommissioning(models.Model):
    """Housing put into service, State Statistics (dssu): quarters 1-4 and quarter 0 = the total for the year.
    region_id: LUN id of the oblast centre, 42 = Kyiv oblast, 10000 = Ukraine; not a foreign key, those two are not
    cities of ours."""
    region_id = models.IntegerField()
    year = models.PositiveSmallIntegerField()
    quarter = models.PositiveSmallIntegerField()
    all_m2 = _number()
    apartment_m2 = _number()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'housing_commissioning'
        constraints = _key('housing_commissioning', 'region_id', 'year', 'quarter')


# Snapshots: LUN sends the current state only; one snapshot per snap_date, history builds up on our side

class DistrictPrice(models.Model):
    """Secondary market and rent medians by district (market-districts); m² is per m² of total area."""
    district = models.ForeignKey(District, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()
    snap_date = models.DateField()
    median_uah = _money()
    median_renovated_uah = _money()
    median_not_renovated_uah = _money()
    median_m2_uah = _money()
    median_m2_renovated_uah = _money()
    median_m2_not_renovated_uah = _money()
    median_usd = _money()  # sent by the short shape (micro-districts) only; otherwise UAH / usd_to_uah
    median_m2_usd = _money()
    usd_to_uah = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    cnt = _count()
    cnt_renovated = _count()
    cnt_not_renovated = _count()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'district_price'
        constraints = _key('district_price', 'district', 'contract_type', 'room_count', 'snap_date')


class DistrictAveragePrice(models.Model):
    """New buildings: the average starting price by district, of a flat's m² or of a parking space."""

    class Item(models.TextChoices):
        FLAT_M2 = 'flat_m2'  # districts
        PARKING = 'parking'  # parking-districts

    district = models.ForeignKey(District, on_delete=models.PROTECT)
    item = models.CharField(max_length=8, choices=Item)
    snap_date = models.DateField()
    avg_uah = _money()
    avg_usd = _money()
    cnt = _count()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'district_average_price'
        constraints = _key('district_average_price', 'district', 'item', 'snap_date')


class HouseDistrictPrice(models.Model):
    district = models.ForeignKey(District, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    snap_date = models.DateField()
    median_usd = _money()
    median_m2_usd = _money()
    area = _number()
    cnt = _count()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'house_district_price'
        constraints = _key('house_district_price', 'district', 'contract_type', 'snap_date')


class PriceBucket(models.Model):
    """Number of listings in a price range (price-distribution); price_to None = the open last bucket."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()
    currency = models.CharField(max_length=3)  # usd | uah
    snap_date = models.DateField()
    price_from = models.DecimalField(max_digits=14, decimal_places=2)
    price_to = _money()
    cnt = models.IntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'price_bucket'
        constraints = _key('price_bucket', 'city', 'contract_type', 'room_count', 'currency', 'snap_date',
                           'price_from')


class ProfessionAffordability(models.Model):
    """salary-positions: per profession, years of salary for a flat (sale) or % of salary for the rent."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    contract_type = models.PositiveSmallIntegerField(choices=ContractType)
    room_count = models.PositiveSmallIntegerField()
    profession_uk = models.CharField(max_length=160)
    profession_en = models.CharField(max_length=160, blank=True)
    snap_date = models.DateField()
    value = _number()
    salary = _money()
    price = _money()
    url = models.URLField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'profession_affordability'
        constraints = _key('profession_affordability', 'city', 'contract_type', 'room_count', 'profession_uk',
                           'snap_date')


class ParkingClassPrice(models.Model):
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    scope = models.CharField(max_length=8, choices=Scope)
    housing_class = models.CharField(max_length=10, choices=HousingClass)
    snap_date = models.DateField()
    median_uah = _money()
    median_usd = _money()
    cnt = _count()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'parking_class_price'
        constraints = _key('parking_class_price', 'city', 'scope', 'housing_class', 'snap_date')


class DeveloperRank(models.Model):
    """Top developers by flats delivered in a year (city and oblast, certificates of commissioning)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)
    place = models.CharField(max_length=10)  # "1", or a shared place like "9-10"
    flats = models.IntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'developer_rank'
        constraints = _key('developer_rank', 'city', 'year', 'name')


class DeveloperShare(models.Model):
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)
    share_pct = models.FloatField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'developer_share'
        constraints = _key('developer_share', 'city', 'year', 'name')


class ConstructionStat(models.Model):
    """Sections of residential complexes (sections)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    scope = models.CharField(max_length=8, choices=Scope)
    snap_date = models.DateField()
    on_sale = models.IntegerField(default=0)
    under_construction = models.IntegerField(default=0)
    preparatory = models.IntegerField(default=0)
    built = models.IntegerField(default=0)  # since 2010
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'construction_stat'
        constraints = _key('construction_stat', 'city', 'scope', 'snap_date')


class LendingStat(models.Model):
    """New-building complexes with long-term payment (lending)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    scope = models.CharField(max_length=8, choices=Scope)
    snap_date = models.DateField()
    installments = models.IntegerField(default=0)
    mortgages = models.IntegerField(default=0)  # "єОселя"
    credits = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lending_stat'
        constraints = _key('lending_stat', 'city', 'scope', 'snap_date')


class PetsRentShare(models.Model):
    """Rent listings allowing pets, % (pets-rent; LUN publishes it for a few cities only)."""
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    scope = models.CharField(max_length=8, choices=Scope)
    realty_type = models.CharField(max_length=8)  # flat | house
    snap_date = models.DateField()
    allowed = _number()
    by_agreement = _number()
    forbidden = _number()
    unknown = _number()
    cnt = _count()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pets_rent_share'
        constraints = _key('pets_rent_share', 'city', 'scope', 'realty_type', 'snap_date')


ENTITIES = [
    District, HousePricePoint, ExposurePoint, DealPricePoint, AffordabilityPoint, RentPaybackPoint, PrimaryClassPrice,
    HousingCommissioning, DistrictPrice, DistrictAveragePrice, HouseDistrictPrice, PriceBucket,
    ProfessionAffordability, ParkingClassPrice, DeveloperRank, DeveloperShare, ConstructionStat, LendingStat,
    PetsRentShare,
]
