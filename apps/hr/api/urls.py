from django.urls import include, path


urlpatterns = [
    path("", include("apps.hr.api.employee.urls")),
    path("", include("apps.hr.api.employee_bank.urls")),
    path("", include("apps.hr.api.employee_family.urls")),
    path("", include("apps.hr.api.employee_education.urls")),
    path("", include("apps.hr.api.employee_experience.urls")),
    path("", include("apps.hr.api.employee_certificate.urls")),
    path("", include("apps.hr.api.employee_document.urls")),
    path("", include("apps.hr.api.employee_medical.urls")),
    path("",include("apps.hr.api.employee_training.urls")),
]