from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.reference.bank.views.bank import (
    BankViewSet,
    BankBranchViewSet,
)

router = DefaultRouter()
router.register("banks", BankViewSet, basename="master-bank")
router.register("bank-branches", BankBranchViewSet, basename="master-bank-branches")

urlpatterns = [
    path("lookup/",include("apps.administration.api.reference.bank.lookup.urls"),),
    path("", include(router.urls)),
]