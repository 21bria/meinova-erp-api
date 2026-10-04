from django.urls import include, path


urlpatterns = [
    path("", include("apps.hr.api.employee.urls")),

    path("", include("apps.hr.api.payroll_assignment.urls")),

    path("", include("apps.hr.api.employee_bank.urls")),
    path("", include("apps.hr.api.employee_family.urls")),
    path("", include("apps.hr.api.employee_education.urls")),
    path("", include("apps.hr.api.employee_experience.urls")),
    path("", include("apps.hr.api.employee_certificate.urls")),
    path("", include("apps.hr.api.employee_document.urls")),
    path("", include("apps.hr.api.employee_medical.urls")),
    path("", include("apps.hr.api.employee_training.urls")),

    # Rute path-tetap harus di atas router viewset supaya tidak
    # tertelan rute `<str:pk>` milik router.
    path("", include("apps.hr.api.dashboard.urls")),

    # Rute spesifik harus di atas router viewset umum.
    path(
        "reminder-policy/",
        include("apps.hr.api.reminder_policy.urls"),
    ),
    path("lookup/", include("apps.hr.api.lookup.urls")),

    # Attendance — route khusus harus lebih dulu
    path("", include("apps.hr.api.attendance_sync.urls")),
    path("", include("apps.hr.api.attendance_permission.urls")),
    path("", include("apps.hr.imports.api.urls")),

    # Modul HR lain
    path("", include("apps.hr.api.employee_action.urls")),
    path("", include("apps.hr.api.leave.urls")),
    path("", include("apps.hr.api.leave_opening.urls")),
    path("", include("apps.hr.api.leave_go_live.urls")),
    path("", include("apps.hr.api.overtime.urls")),
    path("", include("apps.hr.api.roster.urls")),
    path("", include("apps.hr.api.shift_calendar.urls")),
    path("", include("apps.hr.api.site_rotation.urls")),
    path("", include("apps.hr.api.travel_request.urls")),
    path("", include("apps.hr.api.business_trip.urls")),
    path("", include("apps.hr.api.visitor.urls")),
    path("", include("apps.hr.api.training.urls")),
    path("", include("apps.hr.api.recruitment.urls")),

    # Router/viewset umum paling akhir
    path("", include("apps.hr.api.attendance.urls")),
]
