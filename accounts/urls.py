from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
     path("set-language/", views.set_language, name="set_language"),

    path("signup/", views.signup, name="signup"),
    path("verify/<str:uidb64>/<str:token>/", views.verify_email, name="verify_email"),

    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    path("telegram/link/", views.telegram_link, name="telegram_link"),
]