from django.urls import path

from . import views

app_name = "owner_panel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("users/", views.users, name="users"),      # clientes (suscritos)
    path("staff/", views.staff, name="staff"),      # soporte/finanzas/owner
    path("logout/", views.owner_logout, name="logout"),
]