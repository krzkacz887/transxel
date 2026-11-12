"""REST API pod /api/ – pełna lista w README (sekcja „API”)."""
from django.urls import path

from . import accounts, driver, maps, negotiations, packages

urlpatterns = [
    # konta
    path("auth/register/", accounts.RegisterView.as_view(), name="api_register"),
    path("auth/login/", accounts.LoginView.as_view(), name="api_login"),
    path("auth/logout/", accounts.LogoutView.as_view(), name="api_logout"),
    path("me/", accounts.MeView.as_view(), name="api_me"),
    path("contacts/", accounts.ContactsView.as_view(), name="api_contacts"),

    # paczki (nadawca / odbiorca)
    path("packages/", packages.PackageListView.as_view(), name="api_packages"),
    path("packages/<int:pk>/", packages.PackageDetailView.as_view(), name="api_package"),
    path("packages/<int:pk>/quotes/", packages.PackageQuotesView.as_view(), name="api_package_quotes"),
    path("packages/<int:pk>/negotiations/", packages.PackageNegotiationsView.as_view(),
         name="api_package_negotiations"),
    path("track/<str:code>/", packages.TrackView.as_view(), name="api_track"),

    # negocjacje (wszystkie role)
    path("negotiations/", negotiations.NegotiationListView.as_view(), name="api_negotiations"),
    path("negotiations/<int:pk>/", negotiations.NegotiationDetailView.as_view(), name="api_negotiation"),
    path("negotiations/<int:pk>/actions/", negotiations.NegotiationActionView.as_view(),
         name="api_negotiation_action"),

    # kierowca
    path("driver/route/", driver.DriverRouteView.as_view(), name="api_driver_route"),
    path("driver/pool/", driver.DriverPoolView.as_view(), name="api_driver_pool"),
    path("driver/stops/<int:pk>/complete/", driver.StopCompleteView.as_view(), name="api_stop_complete"),

    # mapy
    path("geocode/", maps.GeocodeView.as_view(), name="api_geocode"),
    path("reverse-geocode/", maps.ReverseGeocodeView.as_view(), name="api_reverse_geocode"),
]
