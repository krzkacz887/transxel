"""Paczki (CRUD), publiczne śledzenie, wycena ekspresu i start negocjacji."""
from django.db.models import Q

from ..forms import ExpressStartForm, PackageForm
from ..models import Driver, Package
from ..services import negotiation as pipeline
from ..services import pricing
from .base import PARTIES, ApiError, ApiView, get_or_404, merged_for_update, validate
from .serializers import negotiation_json, package_json, quote_json, tracking_json


def _my_package(request, pk) -> Package:
    pkg = get_or_404(Package.objects.select_related("sender", "recipient", "driver"), "Nie ma takiej paczki.", pk=pk)
    if not pkg.is_party(request.account):
        raise ApiError("To nie Twoja paczka.", 403)
    return pkg


class PackageListView(ApiView):
    roles = PARTIES

    def get(self, request):
        me = request.account
        qs = Package.objects.filter(Q(sender_id=me.pk) | Q(recipient_id=me.pk)).select_related(
            "sender", "recipient", "driver")
        direction = request.GET.get("direction")
        if direction == "sent":
            qs = qs.filter(sender_id=me.pk)
        elif direction == "received":
            qs = qs.filter(recipient_id=me.pk)
        status = request.GET.get("status")
        if status:
            if status not in Package.Status.values:
                raise ApiError(f"Nieznany status: {status}.", 400)
            qs = qs.filter(status=status)
        return [package_json(p, me) for p in qs]

    def post(self, request):
        form = PackageForm(request.data, user=request.account)
        validate(form)
        return package_json(form.save(), request.account), 201


class PackageDetailView(ApiView):
    roles = PARTIES

    def get(self, request, pk):
        pkg = _my_package(request, pk)
        negs = pkg.negotiations.select_related("driver", "package__sender", "package__recipient")
        return {**package_json(pkg, request.account),
                "negotiations": [negotiation_json(n, request.account) for n in negs]}

    def _editable(self, request, pk) -> Package:
        pkg = _my_package(request, pk)
        if pkg.created_by_id != request.account.pk:
            raise ApiError("Zmieniać paczkę może tylko osoba, która ją utworzyła.", 403)
        if pkg.status != Package.Status.NEW:
            raise ApiError("Paczka nie czeka już w puli – nie można jej zmienić.", 409)
        return pkg

    def patch(self, request, pk):
        pkg = self._editable(request, pk)
        counterpart = "recipient" if request.account.is_sender else "sender"
        data = merged_for_update(PackageForm, pkg, request.data, address_fields=PackageForm.ADDRESS_FIELDS,
                                 extra={counterpart: getattr(pkg, f"{counterpart}_id")})
        form = PackageForm(data, instance=pkg, user=request.account)
        validate(form)
        return package_json(form.save(), request.account)

    def delete(self, request, pk):
        pkg = self._editable(request, pk)
        if pkg.negotiations.exists():      # historia negocjacji zostaje – paczka tylko znika z puli
            pkg.status = Package.Status.CANCELLED
            pkg.save(update_fields=["status"])
        else:
            pkg.delete()
        return None, 204


class TrackView(ApiView):
    public = True

    def get(self, request, code):
        pkg = get_or_404(Package.objects.select_related("driver"), f"Nie znaleziono przesyłki {code}.",
                         tracking_code=code.strip().upper())
        return tracking_json(pkg)


class PackageQuotesView(ApiView):
    roles = PARTIES

    def get(self, request, pk):
        pkg = _my_package(request, pk)
        if pkg.status != Package.Status.NEW:
            raise ApiError("Ta paczka nie czeka już w puli – ekspres jest niedostępny.", 409)
        return [quote_json(q) for q in pricing.quotes_for_package(pkg)]


class PackageNegotiationsView(ApiView):
    roles = PARTIES

    def post(self, request, pk):
        pkg = _my_package(request, pk)
        cd = validate(ExpressStartForm(request.data))
        driver = get_or_404(Driver.objects.all(), "Nie ma takiego kierowcy.", pk=cd["driver"])
        neg = pipeline.start(pkg, driver, request.account, sender_share_pct=cd["sender_share_pct"],
                             amount=cd.get("amount"), note=cd.get("note", ""))
        return negotiation_json(neg, request.account, detailed=True), 201
