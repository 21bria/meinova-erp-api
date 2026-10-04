from django.urls import path

from .views import (
    HRPeriodSummaryAPIView,
    HRPeriodSummaryDrilldownAPIView,
)


urlpatterns = [
    path(
        "period-summary/",
        HRPeriodSummaryAPIView.as_view(),
        name="hr-period-summary",
    ),
    path(
        "period-summary/ui-schema/",
        HRPeriodSummaryAPIView.as_schema_view(),
        name="hr-period-summary-ui-schema",
    ),
    path(
        "period-summary/drilldown/",
        HRPeriodSummaryDrilldownAPIView.as_view(),
        name="hr-period-summary-drilldown",
    ),
]
