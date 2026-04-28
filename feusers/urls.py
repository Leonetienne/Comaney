from django.urls import path

from . import views

urlpatterns = [
    path("", views.front_page, name="front_page"),
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
    path("account/delete/", views.account_delete, name="account_delete"),
    path("account/export/", views.account_export, name="account_export"),
    path("totp/setup/",            views.totp_setup,            name="totp_setup"),
    path("totp/disable/",          views.totp_disable,          name="totp_disable"),
    path("totp/verify/",           views.totp_verify,           name="totp_verify"),
    path("totp/verify/recovery/",  views.totp_verify_recovery,  name="totp_verify_recovery"),
    path("api-key/generate/", views.api_key_generate, name="api_key_generate"),
    path("api-key/revoke/",   views.api_key_revoke,   name="api_key_revoke"),
    path("contact/",          views.contact,           name="contact"),
]
