"""Wspólna warstwa REST API: uwierzytelnianie tokenem, JSON na wejściu i wyjściu, błędy.

Każdy widok API dziedziczy po `ApiView` i implementuje metody `get/post/patch/delete`
"""
from __future__ import annotations

import json

from django.forms.models import model_to_dict
from django.http import HttpResponse, JsonResponse
from django.views import View

from ..models import ApiToken, User
from ..services.negotiation import NegotiationError
from ..services.planning import PlanningError

SENDER, RECIPIENT, DRIVER = User.Role.SENDER, User.Role.RECIPIENT, User.Role.DRIVER
PARTIES = (SENDER, RECIPIENT)
ALL_ROLES = (SENDER, RECIPIENT, DRIVER)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, errors: dict | None = None):
        super().__init__(message)
        self.message, self.status, self.errors = message, status, errors or {}


def error_response(message: str, status: int, errors: dict | None = None) -> JsonResponse:
    return JsonResponse({"error": message, "errors": errors or {}}, status=status, json_dumps_params={"ensure_ascii": False})


def validate(form) -> dict:
    if not form.is_valid():
        raise ApiError("Popraw zaznaczone pola.", 400, {f: list(errs) for f, errs in form.errors.items()})
    return form.cleaned_data


def get_or_404(queryset, message="Nie znaleziono.", **lookup):
    obj = queryset.filter(**lookup).first()
    if obj is None:
        raise ApiError(message, 404)
    return obj


def merged_for_update(form_class, instance, data: dict, address_fields=(), extra: dict | None = None) -> dict:
    current = model_to_dict(instance, fields=form_class._meta.fields)
    current.update(extra or {})
    for addr, lat, lng in address_fields:
        if addr in data and lat not in data:
            current[lat] = current[lng] = None
    current.update(data)
    return current


def _authenticate(request):
    header = request.headers.get("Authorization", "")
    scheme, _, key = header.partition(" ")
    if scheme.lower() != "token" or not key.strip():
        return None, None
    token = ApiToken.objects.select_related("user").filter(key=key.strip()).first()
    if token is None or not token.user.is_active:
        raise ApiError("Sesja wygasła – zaloguj się ponownie.", 401)
    return token, (token.user.specific or token.user)


class ApiView(View):
    public = False
    roles = ALL_ROLES

    def dispatch(self, request, *args, **kwargs):
        try:
            request.token, request.account = _authenticate(request)
            if not self.public:
                if request.account is None:
                    raise ApiError("Zaloguj się.", 401)
                if request.account.role not in self.roles:
                    raise ApiError("Brak dostępu dla tego typu konta.", 403)
            request.data = self._parse_body(request)
            result = super().dispatch(request, *args, **kwargs)
        except ApiError as exc:
            return error_response(exc.message, exc.status, exc.errors)
        except (NegotiationError, PlanningError) as exc:
            return error_response(str(exc), 409)

        if isinstance(result, HttpResponse):
            return result
        data, status = result if isinstance(result, tuple) else (result, 200)
        if status == 204:
            return HttpResponse(status=204)
        return JsonResponse(data, status=status, safe=False, json_dumps_params={"ensure_ascii": False})

    @staticmethod
    def _parse_body(request) -> dict:
        if request.method not in ("POST", "PATCH", "PUT") or not request.body:
            return {}
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise ApiError("Niepoprawny JSON.", 400)
        if not isinstance(data, dict):
            raise ApiError("Oczekiwano obiektu JSON.", 400)
        return data
