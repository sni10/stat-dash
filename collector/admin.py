from django.contrib import admin

from .models import City, CollectRun, LunRaw


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
