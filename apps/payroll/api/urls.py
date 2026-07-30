from django.urls import include, path


urlpatterns = [
    path(
        "payroll-groups/",
        include("apps.payroll.api.payroll_groups.urls"),
    ),
    path(
        "salary-grades/",
        include("apps.payroll.api.salary_grades.urls"),
    ),
    path(
        "salary-levels/",
        include("apps.payroll.api.salary_levels.urls"),
    ),
    path(
        "tax-statuses/",
        include("apps.payroll.api.tax_statuses.urls"),
    ),
    path(
        "overtime-groups/",
        include("apps.payroll.api.overtime_groups.urls"),
    ),
    path(
        "allowance-templates/",
        include("apps.payroll.api.allowance_templates.urls"),
    ),
    path(
        "deduction-templates/",
        include("apps.payroll.api.deduction_templates.urls"),
    ),
]