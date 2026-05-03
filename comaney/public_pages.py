"""
Public static pages rendered from Markdown files.

Configure via environment variables (see settings.py).
PUBLIC_PAGES maps slug → (md_file_path, display_label).
"""
import markdown
from django.conf import settings
from django.http import Http404
from django.shortcuts import render


def make_view(md_path: str, title: str):
    """Return a Django view that renders *md_path* as HTML."""
    def view(request):
        try:
            with open(md_path, encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            raise Http404
        html = markdown.markdown(raw, extensions=["extra", "nl2br"])
        return render(request, "public_page.html", {"content": html, "title": title})
    view.__name__ = f"public_page_{title}"
    return view


def context_processor(request):
    """Expose PUBLIC_PAGES and contact_available to every template."""
    contact_available = bool(
        getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "") and
        not getattr(settings, "DISABLE_EMAILING", False) and
        getattr(settings, "ENABLE_REGISTRATION", False)
    )
    return {
        "PUBLIC_PAGES": getattr(settings, "PUBLIC_PAGES", {}),
        "contact_available": contact_available,
        "APP_VERSION": getattr(settings, "APP_VERSION", "dev"),
    }
