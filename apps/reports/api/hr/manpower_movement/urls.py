from django.urls import path

from .views import HRManpowerMovementAPIView


urlpatterns = [
    path(
        "manpower-movement/",
        HRManpowerMovementAPIView.as_view(),
        name="hr-manpower-movement",
    ),
    path(
        "manpower-movement/ui-schema/",
        HRManpowerMovementAPIView.as_schema_view(),
        name="hr-manpower-movement-ui-schema",
    ),
]
