from django.urls import path

from .views import AllowanceTemplateLineLookupView


urlpatterns = [
    path(
        "",
        AllowanceTemplateLineLookupView.as_view(),
        name="allowance-template-line-lookup-list",
    ),
    path(
        "<int:pk>/",
        AllowanceTemplateLineLookupView.as_view(),
        name="allowance-template-line-lookup-detail",
    ),
]
