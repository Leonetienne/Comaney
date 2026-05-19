import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect

# Ensure modern image types are recognised on all platforms.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")


def media_serve(request, path):
    from feusers.utils import _get_session_feuser
    if not _get_session_feuser(request):
        return redirect("login")

    full_path = (settings.MEDIA_ROOT / path).resolve()
    # Prevent path traversal outside MEDIA_ROOT
    if not str(full_path).startswith(str(settings.MEDIA_ROOT.resolve()) + "/"):
        raise Http404
    if not full_path.is_file():
        raise Http404

    content_type, _ = mimetypes.guess_type(str(full_path))
    response = FileResponse(open(full_path, "rb"), content_type=content_type or "application/octet-stream")
    response["Cache-Control"] = "private, max-age=86400, immutable"
    return response
