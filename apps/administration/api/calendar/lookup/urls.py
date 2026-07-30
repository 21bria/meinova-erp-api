from django.urls import path

from .views import CalendarLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        CalendarLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        CalendarLookupView.as_view(),
        name="lookup-detail",
    ),
]