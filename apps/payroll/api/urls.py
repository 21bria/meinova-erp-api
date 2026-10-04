from django.urls import include, path


urlpatterns = [
    # --- Operasional -------------------------------------------------
    #
    # Di atas master supaya `payroll/dashboard/` tidak tertutup pola
    # lain, dan supaya jelas ia bukan salah satu layar konfigurasi.
    path(
        "",
        include("apps.payroll.api.dashboard.urls"),
    ),

    # --- Master (existing, tidak berubah) ---------------------------
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
        "overtime-group-tiers/",
        include("apps.payroll.api.overtime_group_tiers.urls"),
    ),
    path(
        "allowance-templates/",
        include("apps.payroll.api.allowance_templates.urls"),
    ),
    path(
        "deduction-templates/",
        include("apps.payroll.api.deduction_templates.urls"),
    ),

    # --- Konfigurasi tambahan di atas master existing ----------------
    path(
        "allowance-template-lines/",
        include("apps.payroll.api.allowance_template_lines.urls"),
    ),
    path(
        "deduction-template-lines/",
        include("apps.payroll.api.deduction_template_lines.urls"),
    ),
    path(
        "leave-rules/",
        include("apps.payroll.api.leave_rules.urls"),
    ),
    path(
        "tax-brackets/",
        include("apps.payroll.api.tax_brackets.urls"),
    ),

    path(
        "payroll-settings/",
        include("apps.payroll.api.payroll_settings.urls"),
    ),
    path(
        "payroll-policies/",
        include("apps.payroll.api.payroll_policies.urls"),
    ),

    # --- BPJS (Business Decision #3A) --------------------------------
    #
    # Konsep kelas satu, bukan lagi baris Deduction Template ber-kode
    # "BPJS-*". Tarifnya di BPJS Rules yang bertanggal berlaku,
    # komposisi dasarnya bervariasi versi, kepesertaannya per pegawai.
    path(
        "bpjs-programs/lookup/",
        include("apps.payroll.api.bpjs_programs.lookup.urls"),
    ),
    path(
        "bpjs-programs/",
        include("apps.payroll.api.bpjs_programs.urls"),
    ),
    path(
        "bpjs-risk-classes/lookup/",
        include("apps.payroll.api.bpjs_risk_classes.lookup.urls"),
    ),
    path(
        "bpjs-risk-classes/",
        include("apps.payroll.api.bpjs_risk_classes.urls"),
    ),
    path(
        "bpjs-base-definitions/lookup/",
        include("apps.payroll.api.bpjs_base_definitions.lookup.urls"),
    ),
    path(
        "bpjs-base-definitions/",
        include("apps.payroll.api.bpjs_base_definitions.urls"),
    ),
    path(
        "bpjs-base-components/",
        include("apps.payroll.api.bpjs_base_components.urls"),
    ),
    path(
        "bpjs-rules/",
        include("apps.payroll.api.bpjs_rules.urls"),
    ),
    path(
        "bpjs-enrollments/",
        include("apps.payroll.api.bpjs_enrollments.urls"),
    ),

    # --- Transaksi ---------------------------------------------------
    path(
        "payroll-periods/",
        include("apps.payroll.api.payroll_periods.urls"),
    ),
    path(
        "payroll-runs/",
        include("apps.payroll.api.payroll_runs.urls"),
    ),
    path(
        "payroll-run-employees/",
        include("apps.payroll.api.payroll_run_employees.urls"),
    ),
    path(
        "payroll-inputs/",
        include("apps.payroll.api.payroll_inputs.urls"),
    ),
    path(
        "payslips/",
        include("apps.payroll.api.payslips.urls"),
    ),
]
