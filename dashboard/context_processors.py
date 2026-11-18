from django.utils import timezone

from .queries import collection_status


def collection(request):
    """Banner data for every dashboard page: is the last successful collection too old?"""
    if not request.user.is_authenticated:
        return {}
    return {'collection': collection_status(timezone.now())}
