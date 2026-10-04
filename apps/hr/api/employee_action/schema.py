"""
Schema UI dokumen Employee Action.

Satu form melayani dua belas jenis perubahan, dan yang membedakannya
`visible_when` pada `action_type` — bukan dua belas layar. Alasannya
sama dengan form cuti yang tidak dipecah antara pegawai HO dan site:
yang berbeda cuma kolom mana yang relevan, sedangkan dokumennya,
alurnya, dan riwayatnya satu.

Tiap kolom usulan didampingi kolom "current" yang read-only, jadi yang
memutuskan melihat **nilai sekarang → nilai usulan** dalam satu layar.
Angka usulan tanpa angka sekarang tidak bisa dinilai siapa pun; ia harus
membuka tab lain untuk tahu apa yang sebenarnya berubah.
"""

from apps.framework.builders import (
    action,
    field,
    permission,
    tabs,
    ui,
)

from apps.hr.models import EmployeeActionType


ACTION_TYPE_OPTIONS = [
    {"value": value, "label": label}
    for value, label in EmployeeActionType.choices
]


def when_action(*types: str) -> dict:
    """Syarat tampil: hanya untuk jenis action tertentu."""
    return {
        "field": "action_type",
        "op": "in",
        "value": [str(item) for item in types],
    }


CONTRACT_TYPES = (
    EmployeeActionType.CONTRACT_EXTENSION,
    EmployeeActionType.CONTRACT_CHANGE,
)

ORGANIZATION_TYPES = (
    EmployeeActionType.TRANSFER,
    EmployeeActionType.PROMOTION,
    EmployeeActionType.DEMOTION,
    EmployeeActionType.POSITION_CHANGE,
)

POSITION_TYPES = (
    EmployeeActionType.PROMOTION,
    EmployeeActionType.DEMOTION,
    EmployeeActionType.POSITION_CHANGE,
    EmployeeActionType.TRANSFER,
)

SEPARATION_TYPES = (
    EmployeeActionType.RESIGNATION,
    EmployeeActionType.TERMINATION,
)


def _current(label: str, order: int, **extra):
    """
    Kolom nilai sekarang.

    `display=True` wajib: generator FE membuang semua field read-only
    dari `form.ts`, dan tanpa penanda ini kolom pembanding hilang dari
    layar tanpa satu pun error — schema-nya benar, tabnya menyebutnya,
    kotaknya kosong.
    """
    return field.text(
        label=label,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=order,
        **extra,
    )


EMPLOYEE_ACTION_FIELDS = {
    # ------------------------------------------------------------------
    # Kepala dokumen
    # ------------------------------------------------------------------

    # Nomor dan status ditentukan backend: nomornya diambil dari deret
    # `hr/employee_action` saat dokumennya dibuat, statusnya selalu
    # DRAFT. `modes` menahannya di layar create — dua kotak kosong
    # berlabel "Document No." dan "Status" terbaca seperti isian yang
    # lupa diisi, dan orang akan mencoba mengisinya.
    "document_number": field.text(
        label="Document No.",
        read_only=True,
        display=True,
        modes=["edit"],
        overview=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=10,
    ),

    "employee": field.lookup(
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        required=True,
        overview=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=20,
    ),

    # Pengusul, bukan pengetik. `created_by` menjawab pertanyaan yang
    # berbeda dan sudah dicatat sendiri oleh BaseModel.
    #
    # Wajib-tidaknya ditentukan `EmployeeActionPolicy`, bukan schema:
    # jenis yang tidak diatur siapa pun boleh dikosongkan, dan yang
    # diatur akan ditolak service dengan pesan yang menyebut siapa yang
    # seharusnya mengusulkan. Menandainya `required=True` di sini
    # membuat perpanjangan kontrak ikut menuntutnya tanpa alasan.
    "requested_by": field.lookup(
        label="Requested By",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="requested_by_name",
        help_text=(
            "Yang mengusulkan perubahan ini. Kosongkan kalau Anda "
            "sendiri yang mengusulkannya — akan terisi otomatis."
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=25,
    ),

    "action_type": field.select(
        label="Action Type",
        options=ACTION_TYPE_OPTIONS,
        required=True,
        overview=True,
        # Kolom tabel membaca versi siap-tampil dari serializer;
        # tanpa ini isinya "employment_type_change".
        display_key="action_type_label",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Menentukan kolom mana yang berlaku dan — lewat "
            "`WorkflowStep.condition` — meja mana saja yang harus "
            "menandatangani."
        ),
        order=30,
    ),

    "effective_date": field.date(
        label="Effective Date",
        required=True,
        overview=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Sejak kapan perubahannya berlaku — bukan tanggal "
            "pengajuan dan bukan tanggal persetujuan."
        ),
        order=40,
    ),

    "status": field.text(
        label="Status",
        read_only=True,
        display=True,
        modes=["edit"],
        overview=True,
        display_key="status_label",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=50,
    ),

    # ------------------------------------------------------------------
    # Employment Type
    # ------------------------------------------------------------------

    "current_employment_type_name": _current(
        "Current Employment Type",
        order=100,
        visible_when=when_action(
            EmployeeActionType.EMPLOYMENT_TYPE_CHANGE,
        ),
    ),

    "proposed_employment_type": field.lookup(
        label="Proposed Employment Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employment-types/"
        ),
        display_key="proposed_employment_type_name",
        visible_when=when_action(
            EmployeeActionType.EMPLOYMENT_TYPE_CHANGE,
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=110,
    ),

    "proposed_employee_group": field.lookup(
        label="Proposed Employee Group",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employee-groups/"
        ),
        visible_when=when_action(
            EmployeeActionType.EMPLOYMENT_TYPE_CHANGE,
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=120,
    ),

    "confirmation_date": field.date(
        label="Confirmation Date",
        visible_when=when_action(
            EmployeeActionType.EMPLOYMENT_TYPE_CHANGE,
        ),
        help_text=(
            "Tanggal pengangkatan. Diisi ke data pegawai saat action "
            "diterapkan."
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=130,
    ),

    # ------------------------------------------------------------------
    # Employment Status
    # ------------------------------------------------------------------

    "current_employment_status_name": _current(
        "Current Status",
        order=140,
        visible_when=when_action(
            EmployeeActionType.STATUS_CHANGE,
            *SEPARATION_TYPES,
        ),
    ),

    "proposed_employment_status": field.lookup(
        label="Proposed Status",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employment-statuses/"
        ),
        visible_when=when_action(
            EmployeeActionType.STATUS_CHANGE,
            *SEPARATION_TYPES,
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=150,
    ),

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    "current_contract_type_name": _current(
        "Current Contract Type",
        order=200,
        visible_when=when_action(*CONTRACT_TYPES),
    ),

    "current_contract_start": _current(
        "Current Contract Start",
        order=210,
        visible_when=when_action(*CONTRACT_TYPES),
    ),

    "current_contract_end": _current(
        "Current Contract End",
        order=220,
        visible_when=when_action(*CONTRACT_TYPES),
    ),

    "proposed_contract_type": field.lookup(
        label="Proposed Contract Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/contract-types/"
        ),
        visible_when=when_action(*CONTRACT_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=230,
    ),

    "proposed_contract_start": field.date(
        label="Proposed Contract Start",
        visible_when=when_action(*CONTRACT_TYPES),
        help_text=(
            "Kosongkan pada perpanjangan — tanggal mulai kontrak "
            "berjalan dipertahankan."
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=240,
    ),

    "proposed_contract_end": field.date(
        label="Proposed Contract End",
        visible_when=when_action(*CONTRACT_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=250,
    ),

    # ------------------------------------------------------------------
    # Probation
    # ------------------------------------------------------------------

    "current_probation_type_name": _current(
        "Current Probation Type",
        order=300,
        visible_when=when_action(
            EmployeeActionType.PROBATION_CHANGE,
        ),
    ),

    "proposed_probation_type": field.lookup(
        label="Proposed Probation Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/probation-types/"
        ),
        visible_when=when_action(
            EmployeeActionType.PROBATION_CHANGE,
        ),
        help_text=(
            "Kosongkan untuk mengakhiri masa percobaan — tanggalnya "
            "ikut dibersihkan saat diterapkan."
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=310,
    ),

    "proposed_probation_start": field.date(
        label="Proposed Probation Start",
        visible_when={
            "all": [
                when_action(EmployeeActionType.PROBATION_CHANGE),
                {"field": "proposed_probation_type", "op": "is_not_null"},
            ],
        },
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=320,
    ),

    "proposed_probation_end": field.date(
        label="Proposed Probation End",
        visible_when={
            "all": [
                when_action(EmployeeActionType.PROBATION_CHANGE),
                {"field": "proposed_probation_type", "op": "is_not_null"},
            ],
        },
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=330,
    ),

    # ------------------------------------------------------------------
    # Organisasi
    # ------------------------------------------------------------------

    "current_position_name": _current(
        "Current Position",
        order=400,
        visible_when=when_action(*POSITION_TYPES),
    ),

    "current_department_name": _current(
        "Current Department",
        order=410,
        visible_when=when_action(*ORGANIZATION_TYPES),
    ),

    "current_location_name": _current(
        "Current Location",
        order=420,
        visible_when=when_action(EmployeeActionType.TRANSFER),
    ),

    "proposed_company": field.lookup(
        label="Proposed Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        visible_when=when_action(EmployeeActionType.TRANSFER),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=430,
    ),

    "proposed_branch": field.lookup(
        label="Proposed Branch",
        lookup_endpoint=(
            "/api/administration/organization/lookup/branches/"
        ),
        depends_on=["proposed_company"],
        lookup_params={"company_id": "$proposed_company"},
        visible_when=when_action(EmployeeActionType.TRANSFER),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=440,
    ),

    "proposed_location": field.lookup(
        label="Proposed Location",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        depends_on=["proposed_company"],
        lookup_params={
            "company_id": "$proposed_company",
            "branch_id": "$proposed_branch",
        },
        visible_when=when_action(EmployeeActionType.TRANSFER),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=450,
    ),

    "proposed_division": field.lookup(
        label="Proposed Division",
        lookup_endpoint=(
            "/api/administration/organization/lookup/divisions/"
        ),
        depends_on=["proposed_company"],
        lookup_params={
            "company_id": "$proposed_company",
            "branch_id": "$proposed_branch",
            "location_id": "$proposed_location",
        },
        visible_when=when_action(*ORGANIZATION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=460,
    ),

    "proposed_department": field.lookup(
        label="Proposed Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        depends_on=["proposed_company"],
        lookup_params={
            "company_id": "$proposed_company",
            "branch_id": "$proposed_branch",
            "location_id": "$proposed_location",
            "division_id": "$proposed_division",
        },
        visible_when=when_action(*ORGANIZATION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=470,
    ),

    "proposed_section": field.lookup(
        label="Proposed Section",
        lookup_endpoint=(
            "/api/administration/organization/lookup/sections/"
        ),
        depends_on=["proposed_company"],
        lookup_params={
            "company_id": "$proposed_company",
            "branch_id": "$proposed_branch",
            "location_id": "$proposed_location",
            "division_id": "$proposed_division",
            "department_id": "$proposed_department",
        },
        visible_when=when_action(*ORGANIZATION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=480,
    ),

    "proposed_position": field.lookup(
        label="Proposed Position",
        lookup_endpoint=(
            "/api/administration/organization/lookup/positions/"
        ),
        depends_on=["proposed_company"],
        lookup_params={
            "company_id": "$proposed_company",
            "branch_id": "$proposed_branch",
            "location_id": "$proposed_location",
            "division_id": "$proposed_division",
            "department_id": "$proposed_department",
        },
        display_key="proposed_position_name",
        visible_when=when_action(*POSITION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=490,
    ),

    "proposed_job_level": field.lookup(
        label="Proposed Job Level",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/job-levels/"
        ),
        visible_when=when_action(*POSITION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=500,
    ),

    "proposed_job_grade": field.lookup(
        label="Proposed Job Grade",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/job-grades/"
        ),
        visible_when=when_action(*POSITION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=510,
    ),

    "proposed_cost_center": field.lookup(
        label="Proposed Cost Center",
        lookup_endpoint=(
            "/api/administration/organization/lookup/cost-centers/"
        ),
        depends_on=["proposed_company"],
        lookup_params={
            "company_id": "$proposed_company",
            "branch_id": "$proposed_branch",
            "location_id": "$proposed_location",
        },
        visible_when=when_action(EmployeeActionType.TRANSFER),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=520,
    ),

    "proposed_reports_to": field.lookup(
        label="Proposed Reports To",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="proposed_reports_to_name",
        visible_when=when_action(*ORGANIZATION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=530,
    ),

    # ------------------------------------------------------------------
    # Payroll
    # ------------------------------------------------------------------

    "current_basic_salary": _current(
        "Current Basic Salary",
        order=600,
        visible_when=when_action(EmployeeActionType.SALARY_CHANGE),
    ),

    "proposed_basic_salary": field.decimal(
        label="Proposed Basic Salary",
        decimal_places=2,
        max_digits=18,
        visible_when=when_action(EmployeeActionType.SALARY_CHANGE),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=610,
    ),

    "proposed_salary_grade": field.lookup(
        label="Proposed Salary Grade",
        lookup_endpoint="/api/payroll/salary-grades/lookup/",
        visible_when=when_action(EmployeeActionType.SALARY_CHANGE),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=620,
    ),

    "proposed_salary_level": field.lookup(
        label="Proposed Salary Level",
        lookup_endpoint="/api/payroll/salary-levels/lookup/",
        visible_when=when_action(EmployeeActionType.SALARY_CHANGE),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=630,
    ),

    "proposed_payroll_group": field.lookup(
        label="Proposed Payroll Group",
        lookup_endpoint="/api/payroll/payroll-groups/lookup/",
        visible_when=when_action(EmployeeActionType.SALARY_CHANGE),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=640,
    ),

    # ------------------------------------------------------------------
    # Pemutusan
    # ------------------------------------------------------------------

    "last_working_date": field.date(
        label="Last Working Date",
        visible_when=when_action(*SEPARATION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=700,
    ),

    "termination_reason": field.lookup(
        label="Termination Reason",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/termination-reasons/"
        ),
        visible_when=when_action(*SEPARATION_TYPES),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=710,
    ),

    # ------------------------------------------------------------------
    # Penutup
    # ------------------------------------------------------------------

    "reason": field.textarea(
        label="Reason",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        help_text=(
            "Alasan perubahan. Ini yang dibaca approver dan yang "
            "tersisa di riwayat bertahun-tahun kemudian."
        ),
        order=800,
    ),

    "notes": field.textarea(
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=810,
    ),

    "applied_at": field.datetime(
        label="Applied At",
        read_only=True,
        display=True,
        # Baru ada isinya setelah perubahannya benar-benar ditulis.
        # Kotak kosong berlabel "Applied At" pada dokumen yang baru
        # diketik cuma menambah baris yang harus dilewati mata.
        visible_when={"field": "applied_at", "op": "is_not_null"},
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=820,
    ),

    # Kegagalan penerapan setelah alurnya selesai. Ditampilkan di
    # dokumennya sendiri, bukan cuma di log server: yang harus
    # menindaklanjuti adalah HR yang membukanya.
    "apply_error": field.textarea(
        label="Apply Error",
        rows=2,
        layout="full",
        read_only=True,
        display=True,
        visible_when={"field": "apply_error", "op": "is_not_null"},
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=830,
    ),
}


# Kolom usulan dan pembandingnya duduk di tab kedua. Diturunkan dari
# nama, bukan didaftar ulang satu per satu: daftar kedua yang harus
# tetap sama dengan yang pertama cepat atau lambat berbeda, dan field
# yang tertinggal **tidak muncul di form tanpa satu pun pesan**.
CHANGE_FIELDS = {
    name
    for name in EMPLOYEE_ACTION_FIELDS
    if name.startswith(("current_", "proposed_"))
} | {
    "confirmation_date",
    "last_working_date",
    "termination_reason",
}

EMPLOYEE_ACTION_FIELDS = {
    name: {
        **config,
        "tab": "change" if name in CHANGE_FIELDS else "general",
    }
    for name, config in EMPLOYEE_ACTION_FIELDS.items()
}


# Kolom hasil introspeksi model yang **sengaja dimatikan**.
#
# `company`/`branch`/`location` adalah salinan cakupan untuk penyaringan
# cakupan data, bukan bacaan; serializer tidak mengirim nama
# relasinya, jadi kolomnya mencari `company_name` yang tidak pernah ada
# dan tampil "-" di **semua** baris. Kolom yang isinya selalu "-" bukan
# kolom kosong — ia terbaca seperti data yang hilang.
HIDDEN_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "tab": "general",
    }
    for name in (
        "company",
        "branch",
        "location",
        "applied_by",
        "is_active",
    )
}

# Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di kolom
# Employee. Di layar ini dua kolom berisi nama orang berdampingan —
# Employee dan Requested By — dan keduanya lazim berbunyi sama persis
# untuk usulan yang dibuat sendiri; nomor inilah yang memastikan
# dokumennya menempel ke orang yang benar.
HIDDEN_COLUMNS["employee_number"] = field.text(
    tab="general",
    # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
    # kanan tabel — lihat `column_after` di columns.mjs.
    column_after="employee",
    label="Employee No.",
    read_only=True,
    table=True,
    search=True,
    sortable=True,
    order=25,
)


def action_tab_fields(tab: str) -> list[str]:
    return [
        name
        for name, config in EMPLOYEE_ACTION_FIELDS.items()
        if config.get("tab") == tab
    ]


EMPLOYEE_ACTION_TABS = [
    # Kepala dokumen: siapa, jenis perubahannya, sejak kapan, alasannya.
    # Empat pertanyaan yang harus terjawab sebelum kolom mana pun di tab
    # sebelah masuk akal.
    tabs.form(
        key="general",
        label="Document",
        fields=action_tab_fields("general"),
        order=10,
        show_on_create=True,
    ),

    # Isi perubahannya. Kosong sampai Action Type dipilih — itu memang
    # jawabannya: tanpa jenis action, tidak ada satu kolom pun yang
    # relevan, dan menampilkan empat puluh kolom sekaligus supaya tab
    # ini "ada isinya" adalah persis keadaan yang dihindari.
    tabs.form(
        key="change",
        label="Change Details",
        fields=action_tab_fields("change"),
        order=20,
        show_on_create=True,
    ),
]


EMPLOYEE_ACTION_SCHEMA = {
    "endpoint": "/api/hr/employee-actions/",

    "ui": {
        **ui.workspace(
            size="xl",
            columns=2,
            default_tab="general",
        ),
        "export": True,
        "bulk_delete": False,
    },

    "tabs": EMPLOYEE_ACTION_TABS,

    # Bentuknya sama persis dengan `LEAVE_ACTIONS` — kontrak record
    # action memang sudah ada di codebase ini, yang belum ada sisi
    # frontendnya. `visible_when` dinilai terhadap record yang sedang
    # dibuka, jadi tombol Approve tidak muncul pada dokumen Draft.
    #
    # Ini **bukan** penjagaan: yang menolak tetap service di backend.
    # Tombol yang tampil untuk keadaan yang pasti ditolak cuma
    # memindahkan penolakannya satu klik lebih dalam.
    "actions": [
        action.save(),
        action.save_and_close(),
        action.delete(),
        action.export(),

        action.submit(
            endpoint="/api/hr/employee-actions/{id}/submit/",
            visible_when={"status": ["draft", "rejected"]},
        ),

        action.approve(
            endpoint="/api/hr/employee-actions/{id}/approve/",
            visible_when={"status": "submitted"},
            confirm={
                "title": "Setujui perubahan ini?",
                "description": (
                    "Kalau ini meja terakhir, perubahannya langsung "
                    "diterapkan ke data pegawai dan tidak bisa ditarik "
                    "kembali — yang bisa dilakukan sesudahnya cuma "
                    "membuat action kebalikannya."
                ),
            },
        ),

        action.reject(
            endpoint="/api/hr/employee-actions/{id}/reject/",
            visible_when={"status": "submitted"},
        ),

        action.withdraw(
            endpoint="/api/hr/employee-actions/{id}/withdraw/",
            visible_when={"status": "submitted"},
        ),

        # Mengulang penerapan yang gagal setelah alurnya selesai.
        # Hanya masuk akal untuk dokumen yang berhenti di APPROVED —
        # yang sudah APPLIED tidak akan berubah apa-apa lagi.
        action.record(
            "apply",
            endpoint="/api/hr/employee-actions/{id}/apply/",
            label="Retry Apply",
            icon="RefreshCw",
            visible_when={"status": "approved"},
            confirm={
                "title": "Terapkan ulang?",
                "description": (
                    "Dipakai kalau alurnya sudah selesai tapi "
                    "penulisannya gagal. Dokumen yang perubahannya "
                    "sudah masuk tidak akan diterapkan dua kali."
                ),
            },
        ),
    ],

    "permission": permission.module(
        "hr.employeeaction",
        view="hr.view_employeeaction",
        add="hr.add_employeeaction",
        change="hr.change_employeeaction",
        delete="hr.delete_employeeaction",
    ),

    "fields": {
        **EMPLOYEE_ACTION_FIELDS,
        **HIDDEN_COLUMNS,
    },
}
