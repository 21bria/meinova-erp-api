from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollTaxBracketViewSet


router = DefaultRouter()
router.register("", PayrollTaxBracketViewSet, basename="payroll-tax-bracket")


urlpatterns = [path("", include(router.urls))]
