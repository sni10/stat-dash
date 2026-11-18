from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('', views.overview, name='overview'),
    path('rooms/', views.rooms, name='rooms'),
    path('api/prices', views.api_prices, name='api-prices'),
    path('api/monthly', views.api_monthly, name='api-monthly'),
    path('login/', auth_views.LoginView.as_view(template_name='dashboard/login.html',
                                                redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
