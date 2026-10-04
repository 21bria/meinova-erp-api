from django.urls import path

from .views import DeductionTemplateLineLookupView


urlpatterns = [
    path(
        "",
        DeductionTemplateLineLookupView.as_view(),
        name="deduction-template-line-lookup-list",
    ),
    path(
        "<int:pk>/",
        DeductionTemplateLineLookupView.as_view(),
        name="deduction-template-line-lookup-detail",
    ),
]
