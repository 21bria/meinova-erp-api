from apps.framework.builders import action, field, ui
from apps.framework.services.company_copy import CompanyCopyViewSetMixin
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.models import PayrollProrationMethod
from apps.payroll.services import PayrollSettingService

from .serializers import PayrollSettingSerializer


# Label yang dibaca orang HR, bukan nilai enumnya. "FIXED_30" tidak
# menjelaskan apa pun kepada yang harus memilihnya.
PRORATION_OPTIONS = [
    {
        "label": "Fixed 30 days per month",
        "value": PayrollProrationMethod.FIXED_30,
    },
    {
        "label": "Calendar days in the month (28-31)",
        "value": PayrollProrationMethod.CALENDAR_DAYS,
    },
    {
        "label": "Working days in the month",
        "value": PayrollProrationMethod.WORKING_DAYS,
    },
]


# "Belum ditentukan" **tidak** ditulis sebagai opsi bernilai string
# kosong, walaupun itu memang nilai yang disimpan. `SelectItem` reka-ui
# melempar error untuk nilai kosong — itu nilai yang ia pakai sendiri
# untuk mengosongkan pilihan — dan seluruh dialog Payroll Setting akan
# mati begitu dibuka.
#
# Keadaan "belum memilih" karena itu disampaikan lewat placeholder:
# selama belum dipilih, yang terbaca di layar adalah kalimatnya, bukan
# kotak kosong. Nilainya sendiri tetap string kosong di database, dan
# itu yang membedakan perusahaan yang memilih Calendar Days dari
# perusahaan yang belum memutuskan apa pun.
ATTENDANCE_DEDUCTION_OPTIONS = list(PRORATION_OPTIONS)

ATTENDANCE_DEDUCTION_PLACEHOLDER = (
    "Belum ditentukan - memakai hari kerja periode payroll"
)


PAYROLL_SETTING_SCHEMA = {
    "module": "payroll/payroll-settings",
    "name": "PayrollSetting",
    "label": "Payroll Setting",
    "endpoint": "/api/payroll/payroll-settings/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Payroll Settings",
            description=(
                "Kebijakan penggajian per perusahaan. Satu baris untuk "
                "satu perusahaan; pegawai mengikutinya, tidak diatur "
                "satu per satu."
            ),
            size="lg",
            columns=1,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "actions": [
        action.copy_to_companies(
            endpoint="/api/payroll/payroll-settings/",
            help_text=(
                "Kebijakan prorata dan potongan ketidakhadiran disalin "
                "apa adanya. Kalender kerja dan hari libur tiap "
                "perusahaan tetap miliknya sendiri."
            ),
        ),
    ],

    "fields": {
        "company": field.lookup(
            label="Company",
            lookup_endpoint=(
                "/api/administration/organization/lookup/companies/"
            ),
            display_key="company_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=10,
        ),
        "proration_method": field.select(
            label="Salary Proration Method",
            options=PRORATION_OPTIONS,
            default=PayrollProrationMethod.CALENDAR_DAYS,
            required=True,
            table=True,
            # Kolomnya membaca label, bukan nilainya. "calendar_days"
            # di tabel adalah enum yang bocor ke orang yang justru
            # harus memilihnya.
            display_key="proration_method_label",
            filter=True,
            layout="full",
            help_text=(
                "Cara gaji sebulan dipecah jadi hak harian untuk "
                "pegawai yang masuk atau berhenti di tengah periode. "
                "Fixed 30: nilai sehari sama sepanjang tahun. Calendar "
                "days: mengikuti panjang bulannya. Working days: "
                "mengikuti kalender kerja dan hari libur pegawai."
            ),
            order=20,
        ),
        "prorate_on_join": field.boolean(
            label="Prorate New Joiners",
            default=True,
            table=True,
            filter=True,
            help_text=(
                "Pegawai yang masuk di tengah periode dibayar sejak "
                "tanggal masuknya. Dimatikan berarti ia menerima gaji "
                "sebulan penuh."
            ),
            order=30,
        ),
        "prorate_on_termination": field.boolean(
            label="Prorate Leavers",
            default=True,
            table=True,
            filter=True,
            help_text=(
                "Pegawai yang berhenti di tengah periode dibayar "
                "sampai hari terakhirnya. Dimatikan berarti ia "
                "menerima gaji sebulan penuh."
            ),
            order=40,
        ),
        # --- Attendance Deduction (Business Decision #2) --------------
        "attendance_deduction_method": field.select(
            label="Attendance Deduction Method",
            options=ATTENDANCE_DEDUCTION_OPTIONS,
            placeholder=ATTENDANCE_DEDUCTION_PLACEHOLDER,
            default="",
            required=False,
            table=True,
            display_key="attendance_deduction_method_label",
            filter=True,
            layout="full",
            help_text=(
                "Pembagi yang dipakai menghitung nilai sehari untuk "
                "potongan absen dan cuti tidak dibayar. Boleh berbeda "
                "dari metode prorata di atas — prorata menentukan hak "
                "gaji, ini menentukan berapa yang hilang per hari "
                "tidak masuk."
            ),
            order=50,
        ),
        "deduct_absence": field.boolean(
            label="Deduct Absence",
            default=True,
            table=True,
            filter=True,
            help_text=(
                "Hari yang tercatat alpa di absensi memotong gaji. "
                "Dimatikan berarti harinya tetap tercatat tapi tidak "
                "memotong."
            ),
            order=60,
        ),
        "deduct_unpaid_leave": field.boolean(
            label="Deduct Unpaid Leave",
            default=True,
            table=True,
            filter=True,
            help_text=(
                "Hari cuti tidak dibayar memotong gaji. Jenis cuti mana "
                "yang tidak dibayar tetap ditentukan Payroll Leave "
                "Rule, bukan di sini."
            ),
            order=70,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}


class PayrollSettingViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Satu baris per perusahaan, mengikuti pola `TenantSetting` dan
    `PrintSetting`: layar CRUD dialog, bukan layar `setting` tunggal.
    Layar tunggal hanya bisa menyunting satu baris (`.first()`), dan
    tenant berisi dua belas perusahaan akan punya sebelas kebijakan yang
    tidak punya jalan masuk sama sekali.
    """

    serializer_class = PayrollSettingSerializer
    service_class = PayrollSettingService

    framework_module = "payroll/payroll-settings"
    schema = PAYROLL_SETTING_SCHEMA

    data_scope = {"company": "company"}

    # Model ini tidak punya kolom `code`/`name`; bawaan base akan
    # membalas 500 begitu kotak pencarian diketik.
    search_fields = ["company__name", "company__code"]

    filterset_fields = [
        "company",
        "proration_method",
        "prorate_on_join",
        "prorate_on_termination",
        "attendance_deduction_method",
        "deduct_absence",
        "deduct_unpaid_leave",
        "is_active",
    ]

    ordering = ["company__name"]

    ordering_fields = ["company__name", "proration_method", "is_active"]

    def get_queryset(self):
        return PayrollSettingService.get_queryset()
