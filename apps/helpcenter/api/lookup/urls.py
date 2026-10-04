from django.urls import path

from .views import HelpCenterLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        HelpCenterLookupView.as_view(),
        name="helpcenter-lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        HelpCenterLookupView.as_view(),
        name="helpcenter-lookup-detail",
    ),
]
