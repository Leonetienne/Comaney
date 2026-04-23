from django.urls import path

from . import views

urlpatterns = [
    path("", views.hello_world, name="hello_world"),
    path("register/", views.register, name="register"),
    path("register/success/", views.register_success, name="register_success"),
    path("confirm/<str:token>/", views.confirm_email, name="confirm_email"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("confirm-email-change/<str:token>/", views.confirm_email_change, name="confirm_email_change"),
    path("password-forgot/", views.password_forgot, name="password_forgot"),
    path("password-forgot/sent/", views.password_forgot_sent, name="password_forgot_sent"),
    path("password-reset/done/", views.password_reset_done, name="password_reset_done"),
    path("password-reset/<str:token>/", views.password_reset, name="password_reset"),
]
