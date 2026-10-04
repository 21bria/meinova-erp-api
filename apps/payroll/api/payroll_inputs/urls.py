from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollInputViewSet


router = DefaultRouter()
router.register("", PayrollInputViewSet, basename="payroll-input")


urlpatterns = [path("", include(router.urls))]
