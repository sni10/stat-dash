from django.utils import timezone

from .queries import collection_status

# Sidebar entries of the LUN pages (views.PAGES), with simple line icons (24x24 path data)
NAV_PAGES = [
    {'name': 'districts', 'title': 'Районы', 'icon': 'M12 21s-6.75-5.6-6.75-11.25a6.75 6.75 0 1113.5 0C18.75 15.4 12 21 12 21zM12 12.25a2.5 2.5 0 100-5 2.5 2.5 0 000 5z'},
    {'name': 'market', 'title': 'Рынок', 'icon': 'M4.75 19.25V12.5M9.5 19.25V8.75M14.25 19.25V11M19 19.25V5.75'},
    {'name': 'affordability', 'title': 'Доступность', 'icon': 'M3.75 7.75h16.5v10.5H3.75zM3.75 11h16.5M7.5 15h3'},
    {'name': 'primary', 'title': 'Новостройки', 'icon': 'M4.75 20.25V6.5l7-3.25v17M11.75 20.25V9.5l7.5 2.75v8M3.5 20.25h17'},
    {'name': 'houses', 'title': 'Дома', 'icon': 'M4.25 10.5L12 4l7.75 6.5M6.25 9v10.25h11.5V9M10 19.25v-5h4v5'},
]


def collection(request):
    """Banner data for every dashboard page (is the last successful collection too old?) and the sidebar."""
    if not request.user.is_authenticated:
        return {}
    return {'collection': collection_status(timezone.now()), 'nav_pages': NAV_PAGES}
