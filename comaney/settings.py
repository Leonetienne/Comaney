import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-in-production")

DEBUG = os.environ.get("DEBUG", "").upper() == "TRUE"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "feusers",
    "budget",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "comaney.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "feusers.context_processors.current_feuser",
                "comaney.public_pages.context_processor",
            ],
        },
    },
]

WSGI_APPLICATION = "comaney.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "comaney"),
        "USER": os.environ.get("DB_USER", "comaney"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "comaney"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DISABLE_EMAILING = os.environ.get("DISABLE_EMAILING", "").upper() in ("1", "TRUE", "YES")

if DISABLE_EMAILING:
    EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
else:
    if not os.environ.get("EMAIL_HOST") or not os.environ.get("EMAIL_PORT"):
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "Set DISABLE_EMAILING=true to run without email, "
            "or provide both EMAIL_HOST and EMAIL_PORT."
        )
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 1025))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "").upper() == "TRUE"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@comaney.local")

SITE_URL = os.environ.get("SITE_URL", "http://localhost:8080")

ENABLE_REGISTRATION = os.environ.get("ENABLE_REGISTRATION", "").upper() == "TRUE"

AI_TRIAL_API_KEY      = os.environ.get("AI_TRIAL_API_KEY", "")
AI_TRIAL_USAGE_LIMIT  = float(os.environ.get("AI_TRIAL_USAGE_LIMIT", "0"))  # cents
AI_TRIAL_DISABLED_FLAG = os.environ.get("AI_TRIAL_DISABLED_FLAG", str(BASE_DIR / "ai_trial_disabled.flag"))
ADMIN_NOTIFICATION_EMAIL = os.environ.get("ADMIN_NOTIFICATION_EMAIL", "")

# Public static pages rendered from Markdown files.
# Map URL slug → (md_path, display_label).
PUBLIC_PAGES = {}
if _p := os.environ.get("PUBLIC_PAGE_IMPRINT_MD"):
    PUBLIC_PAGES["impressum"] = (_p, "Impressum")
if _p := os.environ.get("PUBLIC_PAGE_EUDATENSCHUTZ_MD"):
    PUBLIC_PAGES["datenschutzerklaerung"] = (_p, "Datenschutzerklärung")
