from django.conf import settings


def api_flags(request):
    """Templates and app.js read prices from /api/v2/ (new models) when USE_NEW_API is on, else /api/ (legacy)."""
    use_new = bool(settings.USE_NEW_API)
    return {"USE_NEW_API": use_new, "API_READ": "/api/v2/" if use_new else "/api/"}
