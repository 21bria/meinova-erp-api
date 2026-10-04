from django.urls import path

from .views import AccountLedgerView, TrialBalanceView


urlpatterns = [
    path("trial-balance/", TrialBalanceView.as_view(), name="finance-trial-balance"),
    path("account-ledger/", AccountLedgerView.as_view(), name="finance-account-ledger"),
]
