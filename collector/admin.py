from django.contrib import admin

from .models import ENTITIES, City, CollectRun, LunRaw


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('id', 'slug', 'name', 'enabled')
    list_editable = ('enabled',)
    search_fields = ('slug', 'name')


@admin.register(CollectRun)
class CollectRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'started_at', 'finished_at', 'status', 'rows_upserted')
    list_filter = ('status',)
    readonly_fields = [f.name for f in CollectRun._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(LunRaw)
class LunRawAdmin(admin.ModelAdmin):
    list_display = ('id', 'fetched_at', 'endpoint', 'city', 'params', 'payload_hash')
    list_filter = ('endpoint', 'city')
    readonly_fields = [f.name for f in LunRaw._meta.fields]

    def has_add_permission(self, request):
        return False


class EntityAdmin(admin.ModelAdmin):
    """The parsed LUN tables: read-only (rebuilt from lun_raw by the parsers), filterable by city, deal, date."""

    list_per_page = 100

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


FILTERS = ('city', 'district__city', 'contract_type', 'scope', 'room_count', 'housing_class', 'item', 'currency',
           'kind', 'year', 'region_id')
DATES = ('date', 'snap_date', 'month')

for model in ENTITIES:
    names = [f.name for f in model._meta.concrete_fields]
    filters = [f for f in FILTERS if f.split('__')[0] in names]
    date = next((d for d in DATES if d in names), None)
    admin.site.register(model, type(f'{model.__name__}Admin', (EntityAdmin,), {
        'list_display': [n for n in names if n not in ('id', 'updated_at')][:10],
        'list_filter': filters,
        'date_hierarchy': date,
        'list_select_related': [n for n in ('city', 'district') if n in names],
        'search_fields': [n for n in ('name', 'name_uk', 'profession_uk') if n in names],
    }))
