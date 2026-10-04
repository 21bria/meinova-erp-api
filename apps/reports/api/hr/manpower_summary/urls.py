from django.urls import path

from .views import HRManpowerSummaryAPIView


urlpatterns = [
    path(
        "manpower-summary/",
        HRManpowerSummaryAPIView.as_view(),
        name="hr-manpower-summary",
    ),
    path(
        "manpower-summary/ui-schema/",
        HRManpowerSummaryAPIView.as_schema_view(),
        name="hr-manpower-summary-ui-schema",
    ),
]
