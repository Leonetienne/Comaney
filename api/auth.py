from feusers.models import FeUser


def get_api_user(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        return FeUser.objects.get(api_key=token, is_active=True)
    except FeUser.DoesNotExist:
        return None
