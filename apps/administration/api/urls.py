from django.urls import include, path

urlpatterns = [
    path("dashboard/", include("apps.administration.api.dashboard.urls")),
    path("organization/", include("apps.administration.api.organization.urls")),

    path("security/", include("apps.administration.api.security.urls")),
    path("calendar/", include("apps.administration.api.calendar.urls")),
    path("currency/", include("apps.administration.api.currency.urls")),
    path("notifications/", include("apps.administration.api.notification.urls")),
    path("numbering/", include("apps.administration.api.numbering.urls")),
    path("audit/", include("apps.administration.api.audit.urls")),
    path("settings/", include("apps.administration.api.settings.urls")),
    path("workflow/", include("apps.administration.api.workflow.urls")),

    # references
    path("references/organization/", include("apps.administration.api.reference.organization.urls")),
    path("references/geography/", include("apps.administration.api.reference.geography.urls")),
    path("references/bank/", include("apps.administration.api.reference.bank.urls")),
    path("references/hr/", include("apps.administration.api.reference.hr.urls")),

]    