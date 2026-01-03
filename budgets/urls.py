# budgets/urls.py
from django.urls import path

from . import views

app_name = "budgets"

urlpatterns = [
    path("", views.budget_list, name="list"),
    path("create/", views.budget_create, name="create"),
    path("<int:pk>/edit/", views.budget_edit, name="edit"),
    path("<int:pk>/delete/", views.budget_delete, name="delete"),

    # categorías (MVP)
    path("categories/create/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
]