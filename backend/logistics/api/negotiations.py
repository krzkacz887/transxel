"""Negocjacje ekspresu: lista, szczegóły z historią, wykonanie kroku pipeline'u."""
from ..forms import NegotiationActionForm
from ..models import Negotiation
from ..services import negotiation as pipeline
from ..services import pricing
from .base import ApiError, ApiView, get_or_404, validate
from .serializers import negotiation_json


def _my_negotiation(request, pk) -> Negotiation:
    neg = get_or_404(Negotiation.objects.select_related("package", "driver", "package__sender", "package__recipient"),
                     "Nie ma takiej negocjacji.", pk=pk)
    if pipeline.role_in(neg, request.account) is None:
        raise ApiError("Nie uczestniczysz w tej negocjacji.", 403)
    return neg


class NegotiationListView(ApiView):

    def get(self, request):
        negs = [negotiation_json(n, request.account) for n in pipeline.negotiations_for(request.account)]
        return sorted(negs, key=lambda n: (not n["is_open"], not n["my_turn"]))


class NegotiationDetailView(ApiView):

    def get(self, request, pk):
        neg = _my_negotiation(request, pk)
        data = negotiation_json(neg, request.account, detailed=True)
        if data["my_role"] == pipeline.DRIVER and neg.stage == Negotiation.Stage.DRIVER:
            q = pricing.quote_for_driver(neg.package, neg.driver)
            data["live_quote"] = q.as_json()
        return data


class NegotiationActionView(ApiView):

    def post(self, request, pk):
        neg = _my_negotiation(request, pk)
        cd = validate(NegotiationActionForm(request.data))
        message = pipeline.perform(neg, request.account, cd["action"], amount=cd.get("amount"),
                                   sender_share_pct=cd.get("sender_share_pct"), note=cd.get("note") or "")
        neg.refresh_from_db()
        return {"message": message, "negotiation": negotiation_json(neg, request.account, detailed=True)}
