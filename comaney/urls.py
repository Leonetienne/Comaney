from django.conf import settings
from django.contrib import admin
from django.urls import path, include

from .public_pages import make_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("budget/", include("budget.urls")),
    path("", include("feusers.urls")),
]

for _slug, (_md_path, _label) in getattr(settings, "PUBLIC_PAGES", {}).items():
    urlpatterns.append(path(f"{_slug}/", make_view(_md_path, _label), name=f"public_{_slug}"))
