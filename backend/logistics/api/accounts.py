"""Konta: rejestracja, logowanie tokenem, profil, lista kontrahentów."""
from django.contrib.auth import authenticate

from ..forms import SETTINGS_FORMS, SignupForm
from ..models import ROLE_MODELS, ApiToken, Recipient, Sender
from ..services.negotiation import pending_for
from .base import PARTIES, ApiError, ApiView, merged_for_update, validate
from .serializers import account_json, contact_json


def _session(account, status=200):
    token = ApiToken.objects.create(user=account)
    return {"token": token.key, "user": _me(account)}, status


def _me(account):
    return {**account_json(account), "pending_negotiations": len(pending_for(account))}


class RegisterView(ApiView):
    public = True

    def post(self, request):
        cd = validate(SignupForm(request.data))
        Model = ROLE_MODELS[cd["role"]]
        account = Model(username=cd["username"], email=cd.get("email", ""), first_name=cd.get("first_name", ""),
                        last_name=cd.get("last_name", ""), phone=cd.get("phone", ""))
        account.set_password(cd["password1"])
        account.save()
        return _session(account, 201)


class LoginView(ApiView):
    public = True

    def post(self, request):
        user = authenticate(request, username=request.data.get("username", ""),
                            password=request.data.get("password", ""))
        if user is None:
            raise ApiError("Nieprawidłowy login lub hasło.", 400)
        account = user.specific
        if account is None:
            raise ApiError("To konto nie ma roli w aplikacji (użyj panelu /admin/).", 403)
        return _session(account)


class LogoutView(ApiView):

    def post(self, request):
        request.token.delete()
        return None, 204


class MeView(ApiView):

    def get(self, request):
        return _me(request.account)

    def patch(self, request):
        FormClass = SETTINGS_FORMS[request.account.role]
        data = merged_for_update(FormClass, request.account, request.data, address_fields=FormClass.ADDRESS_FIELDS)
        form = FormClass(data, instance=request.account)
        validate(form)
        return _me(form.save())


class ContactsView(ApiView):
    roles = PARTIES

    def get(self, request):
        Model = Recipient if request.account.is_sender else Sender
        return [contact_json(u) for u in Model.objects.order_by("username")]
