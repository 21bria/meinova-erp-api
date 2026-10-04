"""
Schema UI baris pegawai payroll.

Dipakai dua tempat: tab Employees di dalam Payroll Run, dan layar
Payroll Review yang berdiri sendiri. Karena itu ia punya schema penuh,
bukan hanya definisi kolom grid.
"""

from apps.framework.builders import field, tabs, ui


RUN_EMPLOYEE_STATUS_OPTIONS = [
    {"label": "Pending", "value": "pending"},
    {"label": "Calculated", "value": "calculated"},
    {"label": "Excluded", "value": "excluded"},
    {"label": "Error", "value": "error"},
    {"label": "Finalized", "value": "finalized"},
]


GENERAL_FIELDS = {
    "run": field.lookup(
        tab="general",
        label="Payroll Run",
        lookup_endpoint="/api/payroll/payroll-runs/lookup/",
        display_key="run_document_number",
        disabled=True,
        table=True,
        filter=True,
        order=10,
    ),
    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        disabled=True,
        table=True,
        filter=True,
        search=True,
        overview=True,
        order=20,
    ),
    "department": field.lookup(
        tab="general",
        label="Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        display_key="department_name",
        disabled=True,
        table=True,
        filter=True,
        order=30,
    ),
    "basic_salary": field.currency(
        tab="general",
        label="Basic Salary",
        read_only=True,
        permission="payroll.view_salary",
        table=True,
        sortable=True,
        overview=True,
        order=40,
    ),
    "gross_earning": field.currency(
        tab="general",
        label="Gross Earning",
        read_only=True,
        table=True,
        sortable=True,
        overview=True,
        order=50,
    ),
    "total_deduction": field.currency(
        tab="general",
        label="Total Deduction",
        read_only=True,
        table=True,
        sortable=True,
        order=60,
    ),
    "tax_amount": field.currency(
        tab="general",
        label="Tax",
        read_only=True,
        table=True,
        sortable=True,
        order=70,
    ),
    "net_pay": field.currency(
        tab="general",
        label="Net Pay",
        read_only=True,
        table=True,
        sortable=True,
        overview=True,
        order=80,
    ),
    # Sengaja tidak `overview`: yang dicari orang di kartu ringkas
    # adalah yang diterima pegawai, dan angka biaya perusahaan yang
    # duduk sebaris dengannya terbaca sebagai bagian darinya.
    "employer_contribution": field.currency(
        tab="general",
        label="Employer Cost",
        read_only=True,
        table=False,
        sortable=True,
        order=85,
    ),
    "status": field.select(
        tab="general",
        label="Status",
        options=RUN_EMPLOYEE_STATUS_OPTIONS,
        disabled=True,
        table=True,
        filter=True,
        order=90,
    ),
    "is_excluded": field.boolean(
        tab="general",
        label="Excluded",
        default=False,
        table=True,
        filter=True,
        help_text=(
            "Dikeluarkan dari perhitungan run ini. Barisnya tetap ada "
            "supaya alasannya bisa dibaca."
        ),
        order=100,
    ),
    "exclusion_reason": field.textarea(
        tab="general",
        label="Exclusion Reason",
        rows=2,
        layout="full",
        table=False,
        visible_when={"is_excluded": True},
        order=110,
    ),
    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=2,
        layout="full",
        table=False,
        order=120,
    ),
}


# `display=True` wajib menemani `read_only=True`. Tanpa penanda itu
# generator membuang seluruh field read-only dari form, dan tab ini
# terbit sebagai "No form fields configured for this section" — persis
# yang terjadi selama ini: seluruh angka hari, faktor prorata, dan
# metodenya tidak pernah terlihat di layar mana pun.
DAYS_FIELDS = {
    "period_days": field.integer(
        tab="days", label="Period Days", read_only=True, display=True, table=False, order=10,
    ),
    "working_days": field.decimal(
        tab="days", label="Eligible Days", read_only=True, display=True,
        table=False, order=20,
        help_text=(
            "Hari yang benar-benar dalam masa kerja pegawai di periode "
            "ini — pembilang prorata. Satuannya mengikuti metode: hari "
            "kalender untuk Fixed 30 dan Calendar Days, hari kerja "
            "untuk Working Days."
        ),
    ),
    "paid_days": field.decimal(
        tab="days", label="Paid Days", read_only=True, display=True, table=False, order=30,
    ),
    "attendance_days": field.decimal(
        tab="days", label="Attendance Days", read_only=True, display=True, table=False, order=40,
        help_text="Hari hadir fisik (ada tap). Hari Business Trip tanpa tap tidak termasuk.",
    ),
    "business_trip_days": field.decimal(
        tab="days", label="Business Trip Days", read_only=True, display=True, table=False, order=45,
        help_text=(
            "Hari tugas Business Trip yang dibayar tanpa hadir fisik. "
            "Bukan hari hadir: tidak menghasilkan tunjangan per hari hadir."
        ),
    ),
    "absent_days": field.decimal(
        tab="days", label="Absent Days", read_only=True, display=True, table=True, order=50,
    ),
    "leave_days": field.decimal(
        tab="days", label="Leave Days", read_only=True, display=True, table=False, order=60,
        help_text="Seluruh hari cuti, dibayar maupun tidak.",
    ),
    "unpaid_leave_days": field.decimal(
        tab="days", label="Unpaid Leave Days", read_only=True, display=True, table=True, order=70,
    ),
    "overtime_hours": field.decimal(
        tab="days", label="Overtime Hours", read_only=True, display=True, table=True, order=80,
    ),
    # Kolom kode mentahnya **disembunyikan**, bukan dibiarkan lolos.
    # Field yang tidak dideklarasikan di schema ikut terbawa lewat
    # introspeksi dengan `table=True`, dan hasilnya `fixed_30` tercetak
    # apa adanya di daftar Payroll Review — enum yang bocor ke orang
    # yang justru tidak boleh membacanya. Yang tampil label di bawah;
    # nilainya tetap ada di API untuk yang membacanya lewat kode.
    "proration_method": field.text(
        tab="days", label="Proration Method (code)", read_only=True,
        display=False, table=False, form=False, order=84,
    ),
    "attendance_deduction_method": field.text(
        tab="days", label="Attendance Deduction Method (code)",
        read_only=True, display=False, table=False, form=False, order=91,
    ),
    # Tiga kolom yang menjawab "kenapa gaji pokoknya segitu" tanpa
    # menghitung ulang: metodenya, pembaginya, dan faktornya.
    # `working_days` di atas pembilangnya.
    "proration_method_label": field.text(
        tab="days", label="Proration Method", read_only=True, display=True,
        table=False, order=85,
        help_text=(
            "Kebijakan perusahaan yang berlaku saat run ini dihitung. "
            "Dibekukan di sini, jadi mengubah kebijakan bulan depan "
            "tidak mengubah angka periode ini."
        ),
    ),
    "proration_base_days": field.decimal(
        tab="days", label="Proration Base Days", read_only=True, display=True,
        table=False, order=88,
        help_text="Pembagi hari yang dipakai metode di atas.",
    ),
    "proration_factor": field.decimal(
        tab="days", label="Proration Factor", read_only=True, display=True, table=False, order=90,
    ),
    # --- potongan ketidakhadiran (Business Decision #2) ---------------
    #
    # Enam baris yang menjawab "kenapa pegawai ini dipotong Rp600.000"
    # tanpa membuka satu pun dokumen lain: berapa harinya, dari sumber
    # yang mana, dibagi berapa, dan hasilnya berapa. Cuti dibayar ikut
    # ditampilkan justru karena angkanya nol pengaruh — pegawai yang
    # cuti tahunan lima hari lalu melihat potongan nol perlu tahu
    # bahwa lima harinya memang tercatat, bukan hilang.
    "paid_leave_days": field.decimal(
        tab="days", label="Paid Leave Days", read_only=True, display=True,
        table=False, order=62,
        help_text=(
            "Hari cuti yang tidak memotong gaji. Yang menentukan "
            "dibayar atau tidak adalah Payroll Leave Rule per jenis "
            "cuti."
        ),
    ),
    "attendance_deduction_method_label": field.text(
        tab="days", label="Attendance Deduction Method", read_only=True,
        display=True, table=True, order=92,
        help_text=(
            "Kebijakan potongan yang berlaku saat run ini dihitung, "
            "dibekukan di sini. Boleh berbeda dari metode prorata."
        ),
    ),
    "deduction_base_days": field.decimal(
        tab="days", label="Deduction Base Days", read_only=True,
        display=True, table=False, order=94,
        help_text=(
            "Pembagi hari untuk nilai sehari yang dipotong. Diambil "
            "dari periode penuh, bukan dari masa kerja pegawai — "
            "prorata gaji pokok sudah diperhitungkan sekali di atas."
        ),
    ),
    "absence_deduction": field.decimal(
        tab="days", label="Absence Deduction", read_only=True,
        display=True, table=True, order=96,
    ),
    "unpaid_leave_deduction": field.decimal(
        tab="days", label="Unpaid Leave Deduction", read_only=True,
        display=True, table=True, order=98,
    ),
}


# Rincian per komponen, sebagai teks siap baca.
#
# **Tiga jalan yang tidak bisa dipakai, dan kenapa.**
# `PayrollRunComponent` sengaja tidak punya ViewSet, jadi tab
# `resource` mustahil tanpa membuat route CRUD untuk baris
# perhitungan — persis yang tidak boleh dilakukan. Workspace belum
# punya tipe tab untuk larik bersarang. Dan `field.json` dibuang
# generator (tidak ada widget JSON di framework ini), jadi tab yang
# memakainya terbit sebagai "No form fields configured" — kolom
# `snapshot` di layar Payslip pun sebenarnya tidak pernah tampil
# karena itu.
#
# Yang tersisa dan benar-benar bekerja hari ini: textarea read-only
# berisi ringkasan yang disusun serializer. Belum secantik tabel, dan
# itu utang yang dicatat. Yang dijamin di sini bukan kecantikannya
# melainkan bahwa "kenapa tunjangan ini 800.000" bisa dijawab dari
# layar.
BREAKDOWN_FIELDS = {
    "components_summary": field.textarea(
        tab="breakdown",
        label="Component Breakdown",
        read_only=True,
        display=True,
        table=False,
        layout="full",
        rows=18,
        order=10,
        help_text=(
            "Seluruh komponen yang membentuk Gross Earning dan Total "
            "Deduction baris ini, lengkap dengan cara tiap angkanya "
            "dihitung."
        ),
    ),
}


SNAPSHOT_FIELDS = {
    "payroll_group": field.lookup(
        tab="snapshot", label="Payroll Group",
        lookup_endpoint="/api/payroll/payroll-groups/lookup/",
        disabled=True, table=False, order=10,
    ),
    "salary_grade": field.lookup(
        tab="snapshot", label="Salary Grade",
        lookup_endpoint="/api/payroll/salary-grades/lookup/",
        disabled=True, table=False, order=20,
    ),
    "salary_level": field.lookup(
        tab="snapshot", label="Salary Level",
        lookup_endpoint="/api/payroll/salary-levels/lookup/",
        disabled=True, table=False, order=30,
    ),
    "tax_status": field.lookup(
        tab="snapshot", label="Tax Status",
        lookup_endpoint="/api/payroll/tax-statuses/lookup/",
        disabled=True, table=False, order=40,
    ),
    "overtime_group": field.lookup(
        tab="snapshot", label="Overtime Group",
        lookup_endpoint="/api/payroll/overtime-groups/lookup/",
        disabled=True, table=False, order=50,
    ),
    "allowance_template": field.lookup(
        tab="snapshot", label="Allowance Template",
        lookup_endpoint="/api/payroll/allowance-templates/lookup/",
        disabled=True, table=False, order=60,
    ),
    "deduction_template": field.lookup(
        tab="snapshot", label="Deduction Template",
        lookup_endpoint="/api/payroll/deduction-templates/lookup/",
        disabled=True, table=False, order=70,
    ),
    # Kebijakan yang berlaku waktu run ini dihitung. Kolom kodenya
    # (`pay_basis`) disembunyikan supaya `monthly`/`daily` tidak bocor
    # apa adanya lewat introspeksi; yang tampil labelnya.
    "payroll_policy": field.lookup(
        tab="snapshot", label="Payroll Policy",
        lookup_endpoint="/api/payroll/payroll-policies/lookup/",
        disabled=True, table=False, order=72,
        help_text=(
            "Kosong berarti pegawai ini mengikuti Payroll Setting "
            "perusahaannya."
        ),
    ),
    "pay_basis": field.text(
        tab="snapshot", label="Pay Basis (code)", read_only=True,
        display=False, table=False, form=False, order=73,
    ),
    "payroll_policy_label": field.text(
        tab="snapshot", label="Calculation Policy", read_only=True,
        display=True, table=True, order=74,
        help_text=(
            "Kebijakan yang dibekukan bersama snapshot ini. Mengganti "
            "kebijakan bulan depan tidak mengubah angka periode ini."
        ),
    ),
    "daily_rate": field.decimal(
        tab="snapshot", label="Upah Sehari", read_only=True,
        display=True, table=False, order=76,
        help_text=(
            "Hanya untuk dasar Harian. Ditampilkan enam desimal karena "
            "tarif yang diturunkan dari gaji sebulan jarang bulat, dan "
            "angka yang sudah dibulatkan tidak menghasilkan upah yang "
            "dibayar."
        ),
    ),
    "join_date": field.date(
        tab="snapshot", label="Join Date", disabled=True, table=False, order=80,
    ),
    "termination_date": field.date(
        tab="snapshot", label="Termination Date", disabled=True,
        table=False, order=90,
    ),
}


DISPLAY_FIELDS = {
    "components": field.json(
        label="Components", read_only=True, table=False, order=200,
    ),
    "findings": field.json(
        label="Findings", read_only=True, table=False, order=210,
    ),
    "snapshot": field.json(
        label="Snapshot", read_only=True, table=False, order=220,
    ),
}


PAYROLL_RUN_EMPLOYEE_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
    ),
    tabs.form(
        key="days",
        label="Days & Hours",
        fields=list(DAYS_FIELDS.keys()),
        order=20,
    ),
    tabs.form(
        key="breakdown",
        label="Component Breakdown",
        fields=list(BREAKDOWN_FIELDS.keys()),
        order=25,
    ),
    tabs.form(
        key="snapshot",
        label="Payroll Snapshot",
        fields=list(SNAPSHOT_FIELDS.keys()),
        order=30,
    ),
]


PAYROLL_RUN_EMPLOYEE_SCHEMA = {
    "module": "payroll/payroll-run-employees",
    "name": "PayrollRunEmployee",
    "label": "Payroll Review",
    "endpoint": "/api/payroll/payroll-run-employees/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Payroll Review",
            description=(
                "Hasil perhitungan per pegawai, lengkap dengan rincian "
                "per komponen."
            ),
            size="full",
            columns=2,
            create=False,
            edit=True,
            delete=False,
            bulk_delete=False,
            export=True,
        ),
    },

    "tabs": PAYROLL_RUN_EMPLOYEE_TABS,
    "fields": {
        **GENERAL_FIELDS,
        **DAYS_FIELDS,
        **BREAKDOWN_FIELDS,
        **SNAPSHOT_FIELDS,
        **DISPLAY_FIELDS,
    },
}
