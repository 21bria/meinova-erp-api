from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollSettingViewSet


router = DefaultRouter()
router.register("", PayrollSettingViewSet, basename="payroll-setting")


urlpatterns = [path("", include(router.urls))]
