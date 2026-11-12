"""
    CORS dla REST API.
"""
from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


class CorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")
        allowed = bool(origin) and origin in settings.CORS_ALLOWED_ORIGINS \
            and request.path.startswith(settings.CORS_URL_PREFIX)

        if allowed and request.method == "OPTIONS" and "Access-Control-Request-Method" in request.headers:
            response = HttpResponse(status=204)
            response["Access-Control-Allow-Methods"] = ", ".join(settings.CORS_ALLOW_METHODS)
            response["Access-Control-Allow-Headers"] = ", ".join(settings.CORS_ALLOW_HEADERS)
            response["Access-Control-Max-Age"] = str(settings.CORS_PREFLIGHT_MAX_AGE)
        else:
            response = self.get_response(request)

        if allowed:
            response["Access-Control-Allow-Origin"] = origin
        if request.path.startswith(settings.CORS_URL_PREFIX):
            patch_vary_headers(response, ("Origin",))
        return response
