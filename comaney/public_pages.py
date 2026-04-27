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
    """Expose PUBLIC_PAGES to every template for footer links."""
    return {"PUBLIC_PAGES": getattr(settings, "PUBLIC_PAGES", {})}
