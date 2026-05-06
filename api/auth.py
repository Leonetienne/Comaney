from feusers.models import FeUser


def get_api_user(request):
    """Resolve the authenticated FeUser from a request.

    Accepts two auth mechanisms in priority order:
    1. Bearer token in the Authorization header (API key — for external clients).
    2. Django session cookie (feuser_id — for same-origin browser requests).
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            try:
                return FeUser.objects.get(api_key=token, is_active=True)
            except FeUser.DoesNotExist:
                return None

    feuser_id = request.session.get("feuser_id")
    if feuser_id:
        try:
            return FeUser.objects.get(pk=feuser_id, is_active=True)
        except FeUser.DoesNotExist:
            pass

    return None
