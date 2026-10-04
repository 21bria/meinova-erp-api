"""
Layar setting: toleransi keterlambatan dan ambang lembur.

Bentuknya sama dengan `LeavePolicy` dan `EmployeeActionPolicy` —
sasaran (company / location / employee group) plus aturannya. Bagian
terpenting layar ini justru help text-nya: mengosongkan Company berarti
"berlaku untuk semua", **bukan** "tidak berlaku", dan itu jebakan yang
sudah berkali-kali muncul di master berjenjang lain di sistem ini.
"""

from rest_framework import serializers

from apps.administration.models import AttendancePolicy
from apps.core.services.master import BaseMasterService
from apps.framework.builders import action, field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.services.company_copy import (
    CompanyCopyMixin,
    CompanyCopyViewSetMixin,
)
from apps.framework.views.mixins import ServiceWriteMixin


class AttendancePolicyService(CompanyCopyMixin, BaseMasterService):
    model = AttendancePolicy

    copy_rule_fields = [
        "description",
        "late_tolerance_minutes",
        "late_counts_from_tolerance",
        "early_leave_tolerance_minutes",
        "overtime_threshold_minutes",
        "overtime_rounding_minutes",
        "break_minutes",
        "is_active",
        "sort_order",
    ]


class AttendancePolicySerializer(serializers.ModelSerializer):
    # Ringkasan sasaran dalam satu kolom. Tanpa ini, membedakan dua
    # aturan berarti membaca tiga kolom yang sebagian besarnya kosong —
    # dan kolom kosong terbaca seperti data yang belum diisi, bukan
    # seperti "berlaku untuk semua".
    scope_label = serializers.SerializerMethodField()

    # Skor yang benar-benar dipakai saat memilih. Ditampilkan supaya
    # pertanyaan "kenapa yang ini yang berlaku" punya jawaban di layar,
    # bukan cuma di kode.
    specificity = serializers.IntegerField(read_only=True)

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    employee_group_name = serializers.CharField(
        source="employee_group.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = AttendancePolicy
        fields = "__all__"

        read_only_fields = [
            "scope_label",
            "specificity",
            "company_name",
            "location_name",
            "employee_group_name",
        ]

    def get_scope_label(self, obj) -> str:
        parts = [
            getattr(obj.company, "name", None),
            getattr(obj.location, "name", None),
            getattr(obj.employee_group, "name", None),
        ]

        parts = [part for part in parts if part]

        # Bukan string kosong: yang berlaku untuk semua orang adalah
        # keadaan yang paling perlu terbaca jelas, bukan yang paling
        # tidak kelihatan.
        return " · ".join(parts) if parts else "Semua pegawai"


SCOPE_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
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
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "scope_label": field.text(
        tab="general",
        label="Applies To",
        read_only=True,
        display=True,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text=(
            "Ringkasan sasaran baris ini. \"Semua pegawai\" berarti "
            "aturan dasar — dipakai siapa pun yang tidak tercakup "
            "aturan yang lebih khusus."
        ),
        order=25,
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
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk SEMUA company. Isi hanya "
            "kalau satu perusahaan memang punya aturan sendiri — "
            "aturan yang menyebut company mengalahkan yang dasar, dan "
            "hanya untuk pegawai perusahaan itu."
        ),
        order=30,
    ),

    "location": field.lookup(
        tab="general",
        label="Location",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        display_key="location_name",
        depends_on=["company"],
        lookup_params={"company_id": "$company"},
        required=False,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua lokasi di company itu. "
            "Inilah pembeda yang paling sering dipakai: site yang "
            "orangnya tinggal di mess tidak perlu kelonggaran macet "
            "seperti kantor pusat. Satu lokasi selalu milik satu "
            "company, jadi Company wajib diisi lebih dulu."
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
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua golongan. Diisi kalau "
            "perlakuannya berbeda per golongan di tempat yang sama — "
            "mis. staf kantoran diberi kelonggaran, pekerja harian "
            "yang absennya menentukan upah tidak."
        ),
        order=50,
    ),

    "specificity": field.integer(
        tab="general",
        label="Priority",
        read_only=True,
        display=True,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Dihitung dari sasaran yang diisi: company 4, lokasi 2, "
            "golongan 1. Angka tertinggi yang dipakai, jadi urutan "
            "baris di tabel tidak menentukan apa pun."
        ),
        order=55,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        search=True,
        order=60,
    ),
}


RULE_FIELDS = {
    "late_tolerance_minutes": field.integer(
        tab="rules",
        label="Late Tolerance (minutes)",
        required=False,
        table=True,
        sortable=True,
        overview=True,
        help_text=(
            "Datang dalam batas ini masih dihitung hadir tepat waktu. "
            "Jam tap yang sebenarnya tetap tersimpan apa adanya."
        ),
        order=110,
    ),

    "late_counts_from_tolerance": field.switch(
        tab="rules",
        label="Count Late From Tolerance",
        required=False,
        table=False,
        help_text=(
            "Menyala: toleransi 15 dan datang menit ke-20 dihitung "
            "telat 5 menit. Mati: dihitung telat 20 menit, jadi "
            "toleransi hanya menentukan statusnya."
        ),
        order=120,
    ),

    "early_leave_tolerance_minutes": field.integer(
        tab="rules",
        label="Early Leave Tolerance (minutes)",
        required=False,
        table=True,
        sortable=True,
        help_text=(
            "Pulang lebih awal dalam batas ini tidak dihitung sebagai "
            "pulang cepat."
        ),
        order=130,
    ),

    # Ambang "dianggap ambil cuti".
    #
    # Ditaruh tepat di bawah kedua toleransinya, bukan di tab
    # tersendiri: yang membaca layar ini sedang memutuskan "berapa lama
    # masih dimaafkan", dan pertanyaan berikutnya selalu "lewat berapa
    # lama baru dianggap tidak masuk". Dua angka yang dibaca berurutan
    # tidak boleh dipisah satu klik.
    "late_leave_threshold_minutes": field.integer(
        tab="rules",
        label="Late → Leave Threshold (minutes)",
        required=False,
        table=True,
        sortable=True,
        help_text=(
            "Telat lebih dari sekian menit dianggap mengambil cuti "
            "sebesar Leave Deduction. Dihitung dari jam jadwal, bukan "
            "dari batas toleransi. Dikosongkan = tidak dipakai."
        ),
        order=132,
    ),

    "early_leave_leave_threshold_minutes": field.integer(
        tab="rules",
        label="Early Leave → Leave Threshold (minutes)",
        required=False,
        table=False,
        help_text=(
            "Pulang lebih awal dari sekian menit dianggap mengambil "
            "cuti. Dikosongkan = tidak dipakai."
        ),
        order=134,
    ),

    "leave_deduction_days": field.decimal(
        tab="rules",
        label="Leave Deduction (days)",
        required=False,
        table=True,
        sortable=True,
        help_text=(
            "Hari cuti yang harus diambil begitu salah satu ambang di "
            "atas terlampaui. Bawaannya setengah hari. Sistem hanya "
            "menandai — yang memotong saldo tetap dokumen cuti yang "
            "diajukan dan disetujui."
        ),
        order=136,
    ),

    "overtime_threshold_minutes": field.integer(
        tab="rules",
        label="Overtime Threshold (minutes)",
        required=False,
        table=True,
        sortable=True,
        overview=True,
        help_text=(
            "Lewat jadwal minimal sekian menit baru dihitung lembur. "
            "Tanpa ambang, kolom lembur terisi satu-dua menit di "
            "hampir setiap baris."
        ),
        order=140,
    ),

    "overtime_rounding_minutes": field.integer(
        tab="rules",
        label="Overtime Rounding (minutes)",
        required=False,
        table=False,
        help_text=(
            "Pembulatan ke bawah, mis. 30 berarti 95 menit dihitung "
            "90. Dikosongkan = tanpa pembulatan."
        ),
        order=150,
    ),

    "break_minutes": field.integer(
        tab="rules",
        label="Break (minutes)",
        required=False,
        table=False,
        help_text=(
            "Potongan istirahat untuk menghitung jam kerja bersih."
        ),
        order=160,
    ),

    "is_active": field.switch(
        tab="rules",
        label="Active",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Dimatikan = aturannya diabaikan, dan pegawai yang "
            "tercakup jatuh ke aturan yang lebih umum."
        ),
        order=170,
    ),

    "sort_order": field.integer(
        tab="rules",
        label="Sort Order",
        required=False,
        table=False,
        sortable=True,
        order=180,
    ),
}


ATTENDANCE_POLICY_SCHEMA = {
    "module": "hr/attendance-policies",
    "name": "AttendancePolicy",
    "label": "Attendance Policy",
    "endpoint": "/api/administration/references/hr/attendance-policies/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Attendance Policy",
            description=(
                "Toleransi keterlambatan dan ambang lembur. Isi satu "
                "aturan dasar tanpa sasaran apa pun, lalu tambahkan "
                "baris hanya untuk tempat atau golongan yang memang "
                "diperlakukan berbeda — sisanya ikut yang dasar. "
                "Sasaran yang dikosongkan berarti BERLAKU UNTUK SEMUA, "
                "bukan tidak berlaku."
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

    # Menyalin satu aturan ke perusahaan lain, tanpa mengetik ulang.
    #
    # Cakupan aturan ini memang mengikuti company — satu perusahaan
    # satu baris — dan di tenant berisi dua belas perusahaan itu berarti
    # dua belas kali mengetik angka yang sama. Yang berubah cuma
    # sasarannya, jadi yang dibutuhkan bukan konsep cakupan baru, cuma
    # tombol salin.
    "actions": [
        action.save(),
        action.save_and_close(),
        action.delete(),
        action.export(),

        action.copy_to_companies(
            endpoint=(
                "/api/administration/references/hr/attendance-policies/"
            ),
        ),
    ],

    "tabs": [
        tabs.form(
            key="general",
            label="Scope",
            fields=list(SCOPE_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="rules",
            label="Rules",
            fields=list(RULE_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
    ],

    "fields": {
        **SCOPE_FIELDS,
        **RULE_FIELDS,
    },
}


class AttendancePolicyViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    queryset = AttendancePolicy.objects.filter(is_deleted=False)
    serializer_class = AttendancePolicySerializer
    service_class = AttendancePolicyService

    framework_module = "hr/attendance-policies"
    schema = ATTENDANCE_POLICY_SCHEMA

    search_fields = ["code", "name", "description"]

    filterset_fields = [
        "company",
        "location",
        "employee_group",
        "is_active",
    ]

    ordering = ["sort_order", "code"]

    data_scope = {
        "company": "company",
        "location": "location",
    }
