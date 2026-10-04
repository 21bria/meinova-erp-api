"""
Layar setting kebijakan cuti.

Bukan `reference_schema` biasa: `LeavePolicy` punya sasaran (company /
employee group / employment type) dan aturan angka, jadi field-nya
ditulis eksplisit dengan penjelasannya masing-masing. Bagian terpenting
dari layar ini justru help text-nya — orang yang mengisinya harus tahu
bahwa mengosongkan Employee Group berarti "berlaku untuk semua", bukan
"tidak berlaku".
"""

from rest_framework import serializers

from apps.administration.models import LeavePolicy
from apps.core.services.master import BaseMasterService
from apps.framework.builders import action, field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.services.company_copy import (
    CompanyCopyMixin,
    CompanyCopyViewSetMixin,
)
from apps.framework.views.mixins import ServiceWriteMixin


class LeavePolicyService(CompanyCopyMixin, BaseMasterService):
    model = LeavePolicy

    copy_scope_fields = [
        "company",
        "employee_group",
        "leave_type",
        "employment_type",
    ]

    copy_rule_fields = [
        "description",
        "uses_balance",
        "max_days",
        "per_event",
        "document_required",
        "history_check",
        "history_action",
        "entitlement_days",
        "accrual",
        "period_basis",
        "eligible_after_months",
        "prorate_first_period",
        "allow_carry_over",
        "carry_over_max_days",
        "carry_over_expiry_months",
        "carry_over_reminder_days",
        "is_active",
    ]



class LeavePolicySerializer(serializers.ModelSerializer):
    leave_type_name = serializers.CharField(
        source="leave_type.name",
        read_only=True,
        default=None,
    )

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    employee_group_name = serializers.CharField(
        source="employee_group.name",
        read_only=True,
        default=None,
    )

    employment_type_name = serializers.CharField(
        source="employment_type.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = LeavePolicy
        fields = "__all__"

        read_only_fields = [
            "leave_type_name",
            "company_name",
            "employee_group_name",
            "employment_type_name",
        ]


TARGET_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "leave_type": field.lookup(
        tab="general",
        label="Leave Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/leave-types/"
        ),
        display_key="leave_type_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=30,
    ),

    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        display_key="company_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua company. Aturan yang "
            "menyebut company mengalahkan yang global."
        ),
        order=40,
    ),

    "employee_group": field.lookup(
        tab="general",
        label="Employee Group",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/employee-groups/"
        ),
        display_key="employee_group_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua golongan. Diisi kalau "
            "pegawai site dan pegawai kantor punya jatah berbeda."
        ),
        order=50,
    ),

    "employment_type": field.lookup(
        tab="general",
        label="Employment Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/employment-types/"
        ),
        display_key="employment_type_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua status. Mis. PKWT dan "
            "PKWTT berbeda jatahnya."
        ),
        order=60,
    ),

    # Ditaruh di tab pertama, sebelum apa pun yang bergantung
    # padanya: ia yang menentukan tab mana yang berisi dan tab mana
    # yang kosong, jadi menyembunyikannya di halaman kedua membuat
    # orang membuka tab kosong lebih dulu lalu menyimpulkan layarnya
    # rusak.
    "uses_balance": field.switch(
        tab="general",
        label="Uses Balance",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        default=True,
        help_text=(
            "Menyala: cuti punya jatah dan sisa, dan LeaveBalance "
            "terbit dari aturan ini — cuti tahunan. Mati: haknya per "
            "kejadian (menikah, melahirkan, duka) — cutinya tetap "
            "dicatat tapi tidak ada saldo yang dipotong, dan yang "
            "berlaku adalah batas di tab Event Rules."
        ),
        order=65,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),
}


# ----------------------------------------------------------------------
# Syarat tampil
# ----------------------------------------------------------------------
#
# Dua kelompok aturan yang **tidak pernah** dipakai bersamaan: yang satu
# menerbitkan saldo, yang satu menilai kejadian. Menampilkan keduanya
# sekaligus berarti setengah isian di layar ini tidak berpengaruh apa
# pun terhadap baris yang sedang disunting — dan yang mengisinya tidak
# punya cara tahu setengah yang mana.

BALANCE_ONLY = {
    "field": "uses_balance",
    "op": "is_true",
}

# Sengaja `not is_true`, **bukan** `is_false`. Yang kedua menuntut
# nilainya benar-benar `false`; nilai yang belum sempat terisi
# (`undefined`) membuat syaratnya gagal, dan field-nya hilang dari form
# tanpa satu pun pesan. Ke arah ini kegagalannya terlihat: field yang
# telanjur tampil kelihatan sendiri.
EVENT_ONLY = {
    "not": BALANCE_ONLY,
}


RULE_FIELDS = {
    "entitlement_days": field.decimal(
        tab="rule",
        label="Entitlement per Period (days)",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Mis. 12 hari setahun.",
        visible_when=BALANCE_ONLY,
        order=110,
    ),

    "eligible_after_months": field.integer(
        tab="rule",
        label="Waiting Period (months)",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Dihitung sejak Join Date. 12 = cuti tahunan baru terbit "
            "setelah setahun bekerja. 0 = berlaku sejak hari pertama."
        ),
        visible_when=BALANCE_ONLY,
        order=120,
    ),

    "prorate_first_period": field.switch(
        tab="rule",
        label="Prorate First Period",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Menyala: pegawai yang mulai berhak bulan Agustus dapat "
            "5/12 jatah untuk tahun itu. Mati: langsung penuh."
        ),
        visible_when=BALANCE_ONLY,
        order=130,
    ),

    "accrual": field.select(
        tab="rule",
        label="Accrual",
        options=[
            {"label": "Upfront", "value": "upfront"},
            {"label": "Monthly Accrual", "value": "monthly"},
        ],
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        visible_when=BALANCE_ONLY,
        order=140,
    ),

    "period_basis": field.select(
        tab="rule",
        label="Period Basis",
        options=[
            {"label": "Calendar Year", "value": "calendar"},
            {"label": "Employment Anniversary", "value": "join_date"},
        ],
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Tahun Kalender = 1 Jan–31 Des untuk semua orang. Ulang "
            "Tahun Masa Kerja = mengikuti tanggal masuk masing-masing."
        ),
        visible_when=BALANCE_ONLY,
        order=150,
    ),
}


CARRY_OVER_FIELDS = {
    "allow_carry_over": field.switch(
        tab="carry_over",
        label="Allow Carry Over",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        visible_when=BALANCE_ONLY,
        order=210,
    ),

    "carry_over_max_days": field.decimal(
        tab="carry_over",
        label="Carry Over Limit (days)",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = tanpa batas. Hanya berlaku kalau saklar di "
            "atas menyala."
        ),
        visible_when=BALANCE_ONLY,
        order=220,
    ),

    "carry_over_expiry_months": field.integer(
        tab="carry_over",
        label="Expires After (months)",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Sisa bawaan hangus setelah sekian bulan periode baru "
            "berjalan. Dikosongkan = tidak hangus. Dihitung dari 1 "
            "Januari tahun bawaannya, bukan dari tanggal perintah "
            "carry over dijalankan."
        ),
        visible_when=BALANCE_ONLY,
        order=230,
    ),

    "carry_over_reminder_days": field.text(
        tab="carry_over",
        label="Reminder Days Before Expiry",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        # Dua syarat, dan yang kedua tidak boleh hilang: pengingat
        # kedaluwarsa hanya berarti kalau ada carry over untuk
        # kedaluwarsa, dan carry over hanya ada pada cuti bersaldo.
        visible_when={
            "all": [
                BALANCE_ONLY,
                {"field": "allow_carry_over", "op": "is_true"},
            ],
        },
        help_text=(
            "Sisa hari saat pegawai diingatkan cuti bawaannya akan "
            "hangus, dipisah koma — mis. 30,14,7. Dikosongkan = tidak "
            "ada pengingat."
        ),
        order=240,
    ),
}


EVENT_FIELDS = {
    "max_days": field.decimal(
        tab="event",
        label="Maximum Days",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        visible_when=EVENT_ONLY,
        help_text=(
            "Batas hari untuk satu pengajuan. Dikosongkan = tanpa "
            "batas — dipakai cuti yang lamanya ditentukan surat dokter "
            "atau jadwal resmi (sakit, melahirkan, haji), bukan oleh "
            "perusahaan. Dibandingkan dengan jumlah hari yang tertulis "
            "di dokumennya, yaitu hari kerja yang hilang."
        ),
        order=310,
    ),

    "per_event": field.switch(
        tab="event",
        label="Per Event",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        visible_when=EVENT_ONLY,
        help_text=(
            "Menyala: hak melekat pada kejadian, jadi riwayat "
            "diperiksa seumur bekerja — kelahiran anak kedua berhak "
            "penuh lagi. Mati: riwayat yang diperiksa hanya tahun yang "
            "sama, mis. cuti sakit."
        ),
        order=320,
    ),

    "document_required": field.switch(
        tab="event",
        label="Document Required",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        visible_when=EVENT_ONLY,
        help_text=(
            "Pengajuan wajib melampirkan dokumen pendukung. "
            "Diperiksa saat Submit, bukan saat draft disimpan — surat "
            "dokter lazim baru ada sesudah orangnya pulang berobat."
        ),
        order=330,
    ),

    "history_check": field.switch(
        tab="event",
        label="History Check",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        visible_when=EVENT_ONLY,
        help_text=(
            "Menampilkan riwayat pemakaian jenis cuti ini saat "
            "pengajuan dibuat, dan riwayat itu ikut terbaca approver "
            "sampai meja terakhir."
        ),
        order=340,
    ),

    "history_action": field.select(
        tab="event",
        label="History Action",
        options=[
            {"label": "None", "value": "none"},
            {"label": "Warning", "value": "warn"},
            {"label": "Warning + Review", "value": "review"},
            {"label": "Block", "value": "block"},
        ],
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        visible_when=EVENT_ONLY,
        help_text=(
            "Warning = ditampilkan saja. Warning + Review = ikut "
            "menandai dokumennya sebagai perlu diperiksa. Block = "
            "pengajuannya ditolak — pakai hanya untuk hak yang memang "
            "sekali seumur bekerja, karena orang bisa menikahkan anak "
            "keduanya dan bisa berduka dua kali dalam setahun."
        ),
        order=350,
    ),
}


LEAVE_POLICY_SCHEMA = {
    "module": "hr/leave-policies",
    "name": "LeavePolicy",
    "label": "Leave Policy",
    "endpoint": "/api/administration/references/hr/leave-policies/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Leave Policy",
            description=(
                "Aturan jatah cuti: berapa hari, sejak kapan, dan "
                "untuk siapa. Saldo pegawai diterbitkan dari sini "
                "lewat generate_leave_balances."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },

    # Menyalin baris ini ke perusahaan lain, tanpa mengetik
    # ulang. Cakupannya tetap per company — yang ditambahkan
    # cuma cara membuatnya.
    "actions": [
        action.save(),
        action.save_and_close(),
        action.delete(),
        action.export(),
        action.copy_to_companies(
            endpoint="/api/administration/references/hr/leave-policies/",
        ),
    ],

    "tabs": [
        tabs.form(
            key="general",
            label="Scope",
            fields=list(TARGET_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="rule",
            label="Entitlement",
            fields=list(RULE_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
        tabs.form(
            key="carry_over",
            label="Carry Over",
            fields=list(CARRY_OVER_FIELDS.keys()),
            order=30,
            show_on_create=True,
        ),
        tabs.form(
            key="event",
            label="Event Rules",
            fields=list(EVENT_FIELDS.keys()),
            order=40,
            show_on_create=True,
        ),
    ],

    "fields": {
        **TARGET_FIELDS,
        **RULE_FIELDS,
        **CARRY_OVER_FIELDS,
        **EVENT_FIELDS,
        **{
            name: {
                "table": False,
                "filter": False,
                "search": False,
                "sortable": False,
            }
            for name in (
                "leave_type_name",
                "company_name",
                "employee_group_name",
                "employment_type_name",
            )
        },
    },
}


class LeavePolicyViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = LeavePolicySerializer
    service_class = LeavePolicyService

    framework_module = "hr/leave-policies"
    schema = LEAVE_POLICY_SCHEMA

    search_fields = [
        "code",
        "name",
        "description",
        "leave_type__code",
        "leave_type__name",
    ]

    filterset_fields = [
        "leave_type",
        "company",
        "employee_group",
        "employment_type",
        "accrual",
        "period_basis",
        "allow_carry_over",
        # Wajib disebut di sini juga: `filter=True` pada schema hanya
        # menampilkan filternya di UI, dan parameter yang tidak
        # terdaftar diterima lalu diabaikan diam-diam.
        "uses_balance",
        "per_event",
        "document_required",
        "history_check",
        "history_action",
    ]

    ordering_fields = [
        "code",
        "name",
        "entitlement_days",
        "max_days",
        "eligible_after_months",
        "created_at",
    ]

    ordering = ["leave_type__code", "code"]

    def get_queryset(self):
        return (
            LeavePolicy.objects
            .select_related(
                "leave_type",
                "company",
                "employee_group",
                "employment_type",
            )
            .filter(is_deleted=False)
        )
