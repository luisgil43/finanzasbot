from django.urls import path

from . import views

app_name = "cards"

urlpatterns = [
    path("", views.card_list, name="list"),
    path("new/", views.card_create, name="create"),
    path("<int:pk>/", views.card_detail, name="detail"),
    path("<int:pk>/edit/", views.card_edit, name="edit"),
    path("<int:pk>/delete/", views.card_delete, name="delete"),
]