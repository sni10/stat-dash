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
    city = models.ForeignKey(City, on_delete=models.PROTECT)
    params = models.JSONField()
    payload_hash = models.CharField(max_length=64)
    payload = models.JSONField()

    class Meta:
        db_table = 'lun_raw'
        indexes = [models.Index(fields=['endpoint', 'city', '-fetched_at'], name='lun_raw_lookup')]
        verbose_name = 'raw response'

    def __str__(self):
        return f'{self.endpoint} {self.params} @ {self.fetched_at:%Y-%m-%d %H:%M}'


class LunPriceSnapshot(models.Model):
    """One point of flat-price-history: a date x city x contract type x room count.

    Monthly points (the 24th) plus one floating "today" point per city x contract type (is_today), replaced on
    every collection. Written by collector.service with INSERT ... ON CONFLICT, not through the ORM.
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
        db_table = 'lun_price_snapshot'
        verbose_name = 'price snapshot'


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
