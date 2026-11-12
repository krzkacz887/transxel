"""Walidacja danych wejściowych API.

"""
from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Driver, Package, Recipient, Sender, User
from .services import geo


def _geocode_into(cleaned, addr_field, lat_field, lng_field, errors, required=True):
    if cleaned.get(lat_field) is not None and cleaned.get(lng_field) is not None:
        return
    address = cleaned.get(addr_field)
    if not address:
        return
    try:
        res = geo.geocode(address, limit=1)
    except geo.GeoError:
        res = []
    if not res:
        if required:
            errors[addr_field] = "Nie znaleziono adresu – popraw go lub wskaż punkt na mapie."
        return
    cleaned[lat_field], cleaned[lng_field] = res[0].lat, res[0].lng


class _GeocodingMixin:
    ADDRESS_FIELDS: tuple = ()   # (adres, lat, lng)

    def clean(self):
        cleaned = super().clean()
        errors = {}
        for addr, lat, lng in self.ADDRESS_FIELDS:
            _geocode_into(cleaned, addr, lat, lng, errors)
        for f, msg in errors.items():
            self.add_error(f, msg)
        return cleaned


# ------------------------------------------------------------------ konta
class SignupForm(UserCreationForm):
    role = forms.ChoiceField(choices=User.Role.choices)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")


class _AccountSettingsForm(_GeocodingMixin, forms.ModelForm):
    lat = forms.FloatField(required=False)
    lng = forms.FloatField(required=False)
    COMMON = ["first_name", "last_name", "email", "phone", "address", "lat", "lng"]
    ADDRESS_FIELDS = (("address", "lat", "lng"),)


class SenderSettingsForm(_AccountSettingsForm):
    class Meta:
        model = Sender
        fields = _AccountSettingsForm.COMMON + ["company"]


class RecipientSettingsForm(_AccountSettingsForm):
    class Meta:
        model = Recipient
        fields = _AccountSettingsForm.COMMON


class DriverSettingsForm(_AccountSettingsForm):
    class Meta:
        model = Driver
        fields = _AccountSettingsForm.COMMON + ["vehicle_name", "vehicle_capacity_kg"]

    def clean_vehicle_capacity_kg(self):
        c = self.cleaned_data["vehicle_capacity_kg"]
        if c is None or c <= 0:
            raise forms.ValidationError("Ładowność musi być większa od zera.")
        return c


SETTINGS_FORMS = {User.Role.SENDER: SenderSettingsForm, User.Role.RECIPIENT: RecipientSettingsForm,
                  User.Role.DRIVER: DriverSettingsForm}


# ------------------------------------------------------------------ paczki
class PackageForm(_GeocodingMixin, forms.ModelForm):

    pickup_lat = forms.FloatField(required=False)
    pickup_lng = forms.FloatField(required=False)
    delivery_lat = forms.FloatField(required=False)
    delivery_lng = forms.FloatField(required=False)
    ADDRESS_FIELDS = (("pickup_address", "pickup_lat", "pickup_lng"),
                      ("delivery_address", "delivery_lat", "delivery_lng"))

    class Meta:
        model = Package
        fields = ["description", "weight_kg", "pickup_address", "pickup_lat", "pickup_lng", "pickup_contact",
                  "delivery_address", "delivery_lat", "delivery_lng", "delivery_contact", "notes"]

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user.is_sender:
            self.counterpart_field = "recipient"
            self.fields["recipient"] = forms.ModelChoiceField(Recipient.objects.all(),
                                                              error_messages={"invalid_choice": "Wybierz odbiorcę z listy."})
        else:
            self.counterpart_field = "sender"
            self.fields["sender"] = forms.ModelChoiceField(Sender.objects.all(),
                                                           error_messages={"invalid_choice": "Wybierz nadawcę z listy."})

    def clean_weight_kg(self):
        w = self.cleaned_data["weight_kg"]
        if w is None or w <= 0:
            raise forms.ValidationError("Waga musi być większa od zera.")
        return w

    def save(self, commit=True):
        pkg = super().save(commit=False)
        if self.user.is_sender:
            pkg.sender, pkg.recipient = self.user, self.cleaned_data["recipient"]
        else:
            pkg.sender, pkg.recipient = self.cleaned_data["sender"], self.user
        if pkg.created_by_id is None:
            pkg.created_by = self.user
        if commit:
            pkg.save()
        return pkg


# ------------------------------------------------------------------ kierowca
class PlanRouteForm(forms.Form):
    start_lat = forms.FloatField(required=False, min_value=-90, max_value=90)
    start_lng = forms.FloatField(required=False, min_value=-180, max_value=180)
    capacity_kg = forms.FloatField(required=False, min_value=1)
    shift_hours = forms.FloatField(required=False, min_value=0.5, max_value=14)
    max_new = forms.IntegerField(required=False, min_value=0)
    take_new = forms.BooleanField(required=False)


# ------------------------------------------------------------------ negocjacje
class ExpressStartForm(forms.Form):
    driver = forms.IntegerField()
    amount = forms.DecimalField(required=False, min_value=1, max_digits=8, decimal_places=2)
    sender_share_pct = forms.IntegerField(min_value=0, max_value=100)
    note = forms.CharField(max_length=300, required=False)


class NegotiationActionForm(forms.Form):
    action = forms.CharField(max_length=10)
    amount = forms.DecimalField(required=False, min_value=1, max_digits=8, decimal_places=2)
    sender_share_pct = forms.IntegerField(required=False, min_value=0, max_value=100)
    note = forms.CharField(max_length=300, required=False)
