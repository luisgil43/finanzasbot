from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("", views.loan_list, name="list"),
    path("new/", views.loan_create, name="create"),
    path("<int:pk>/", views.loan_detail, name="detail"),
    path("<int:pk>/close/", views.loan_close, name="close"),
    path("installment/<int:pk>/pay/", views.installment_pay, name="installment_pay"),
]