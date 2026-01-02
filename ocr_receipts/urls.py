from django.urls import path

from . import views

app_name = "ocr_receipts"

urlpatterns = [
    path("ocr_receipts/upload/", views.receipt_upload, name="upload"),
    path("ocr_receipts/<int:pk>/confirm/", views.receipt_confirm, name="confirm"),
]