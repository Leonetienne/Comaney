from django.urls import path

from . import views

urlpatterns = [
    path("", views.hello_world, name="hello_world"),
    path("registrieren/", views.register, name="register"),
    path("registrieren/erfolg/", views.register_success, name="register_success"),
    path("bestaetigen/<str:token>/", views.confirm_email, name="confirm_email"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("passwort-vergessen/", views.password_forgot, name="password_forgot"),
    path("passwort-vergessen/gesendet/", views.password_forgot_sent, name="password_forgot_sent"),
    path("passwort-zuruecksetzen/erledigt/", views.password_reset_done, name="password_reset_done"),
    path("passwort-zuruecksetzen/<str:token>/", views.password_reset, name="password_reset"),
]
