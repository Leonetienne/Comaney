from django.conf import settings
from django.contrib import admin
from django.urls import path, re_path, include
from django.views.static import serve

from .public_pages import make_view
from budget.admin_views import ai_trial_admin_view

_DOCS_ROOT = settings.BASE_DIR / "docs" / "build" / "site"


def _serve_docs(request, path):
    # Resolve directory URLs to their index.html so /docs/ and /docs/foo/ work.
    if not path or (_DOCS_ROOT / path).is_dir():
        path = path.rstrip("/") + "/index.html"
    return serve(request, path, document_root=_DOCS_ROOT)


urlpatterns = [
    path("admin/ai-trial/", admin.site.admin_view(ai_trial_admin_view), name="admin_ai_trial"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("budget/", include("budget.urls")),
    re_path(r"^docs/(?P<path>.*)$", _serve_docs, name="docs"),
    path("", include("feusers.urls")),
]

for _slug, (_md_path, _label) in getattr(settings, "PUBLIC_PAGES", {}).items():
    urlpatterns.append(path(f"{_slug}/", make_view(_md_path, _label), name=f"public_{_slug}"))

handler400 = "django.views.defaults.bad_request"
handler403 = "django.views.defaults.permission_denied"
handler404 = "django.views.defaults.page_not_found"
handler500 = "django.views.defaults.server_error"
