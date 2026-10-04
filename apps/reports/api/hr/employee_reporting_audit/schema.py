"""
Susunan layar Employee Reporting Audit.

`schema_type="dashboard"` yang sama dengan HR Period Summary, dan itu
yang membuat filter berjenjang, panel Advanced Filter, kotak cari, dan
paginasi sisi server tidak perlu ditulis ulang sama sekali. Yang
berbeda cuma isinya: **tidak ada KPI, tidak ada chart, dan tidak ada
pemilih periode**.

Ketiadaan pemilih periode bukan kelalaian. Laporan ini membaca master
— penempatan, garis pelaporan, akun — dan tidak satu pun angkanya
berubah karena bulan yang dipilih. Pemilih periode yang tetap dipasang
"supaya seragam" mengajari pembacanya bahwa hasilnya bergantung pada
bulan, lalu membuat mereka menyimpulkan salah tepat saat datanya tidak
berubah. Frontend menyembunyikan pemilihnya sendiri kalau schema tidak
menyebut filter bertipe `period` (`MDashboard.vue`), jadi cukup dengan
tidak mendeklarasikannya.
"""

from apps.framework.builders import dashboard


ORGANIZATION_LOOKUP = "/api/administration/organization/lookup"
HR_REFERENCE_LOOKUP = "/api/administration/references/hr/lookup"

ENDPOINT = "/api/reports/hr/employee-reporting-audit/"

# Dropdown Reporting Status dilayani laporan ini sendiri — dua pilihan
# tetap, tanpa model dan tanpa baris database. Lihat `views.py`.
REPORTING_STATUS_LOOKUP = f"{ENDPOINT}reporting-status/"


# ----------------------------------------------------------------------
# Tabel
# ----------------------------------------------------------------------
#
# Sembilan belas kolom, dan tabel ini memang digeser mendatar. Dua
# kolom pertama terkunci: "demo.gm" di kolom paling kanan tanpa nama
# pegawai di sebelah kiri tidak memberi tahu siapa pun apa-apa.
#
# Labelnya sengaja ditulis utuh. Versi command-line laporan ini
# (`audit_employee_reporting`) memakai ACC/RPT/STATUS karena terminal
# 80 kolom memaksanya; layar tidak punya batasan itu, dan singkatan
# yang cuma dipahami penulisnya adalah cara kolom dibaca terbalik.

TABLE_WIDGET = dashboard.table(
    "employee_reporting_audit",
    label="Employee Reporting Audit",
    description=(
        "Satu baris per pegawai aktif: penempatan organisasi, garis "
        "pelaporan, dan akun login yang menempel padanya. Isi master "
        "apa adanya — tidak ada periode dan tidak ada angka transaksi."
    ),
    empty_text="No employees match these filters.",
    sticky_columns=2,
    page_size=25,
    page_size_options=[25, 50, 100],
    searchable=True,
    search_placeholder=(
        "Cari nomor/nama pegawai, akun, email, atau atasannya"
    ),
    span=12,
    order=10,
    columns=[
        # Kolom terkunci wajib menyebut lebarnya sendiri — `left` kolom
        # kedua dijumlahkan dari lebar kolom pertama, dan bawaannya
        # 224px menyisakan jarak kosong selebar setengah kolom di
        # belakang "HO001".
        dashboard.column("employee_number", label="Employee ID", width=104),
        dashboard.column("employee_name", label="Employee Name", width=208),

        dashboard.column("company", label="Company"),
        dashboard.column("location", label="Location"),
        dashboard.column("department", label="Department"),
        dashboard.column("section", label="Section"),
        dashboard.column("position", label="Position"),

        dashboard.column("employee_group", label="Employee Group"),
        dashboard.column("employment_type", label="Employment Type"),
        dashboard.column("join_date", label="Join Date", format="date"),
        dashboard.column("tenure", label="Length of Service"),

        dashboard.column("report_to_number", label="Report To ID"),
        dashboard.column("report_to_name", label="Report To Name"),

        dashboard.column("account", label="Account"),
        dashboard.column("account_email", label="Account Email"),
        dashboard.column("report_account", label="Report To Account"),
        dashboard.column(
            "report_account_email",
            label="Report To Account Email",
        ),

        dashboard.column("account_status", label="Account Status"),
        dashboard.column("reporting_status", label="Reporting Status"),
    ],
)


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------
#
# Susunannya sama persis dengan HR Period Summary, tanpa periodenya.
# Bukan demi keseragaman tampilan: `expand_filter_values` dan
# `DataScopeService` sudah menegakkan artinya di satu tempat untuk
# seluruh dashboard, jadi filter yang ditulis dengan kunci dan
# endpoint yang sama otomatis berperilaku sama — dan filter yang
# ditulis sendiri adalah cara satu tombol Location berperilaku berbeda
# di dua layar tanpa ada yang menyadarinya.

FILTERS = [
    dashboard.lookup_filter(
        "company",
        label="Company",
        lookup_endpoint=f"{ORGANIZATION_LOOKUP}/companies/",
        multiple=True,
        placement="quick",
    ),
    dashboard.lookup_filter(
        "branch",
        label="Branch",
        lookup_endpoint=f"{ORGANIZATION_LOOKUP}/branches/",
        depends_on="company",
        lookup_params={"company_id": "$company"},
        placement="advanced",
    ),
    dashboard.lookup_filter(
        "location",
        label="Location",
        lookup_endpoint=f"{ORGANIZATION_LOOKUP}/locations/",
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        multiple=True,
        placement="quick",
        self_filter="$me.data_scope.self_filter.location",
        self_filter_label="My Location",
    ),
    dashboard.lookup_filter(
        "department",
        label="Department",
        lookup_endpoint=f"{ORGANIZATION_LOOKUP}/departments/",
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
            "location_id": "$location",
        },
        multiple=True,
        placement="advanced",
    ),
    dashboard.lookup_filter(
        "section",
        label="Section",
        lookup_endpoint=f"{ORGANIZATION_LOOKUP}/sections/",
        depends_on="department",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
            "location_id": "$location",
            "department_id": "$department",
        },
        multiple=True,
        placement="advanced",
    ),
    dashboard.lookup_filter(
        "employee_group",
        label="Employee Group",
        lookup_endpoint=f"{HR_REFERENCE_LOOKUP}/employee-groups/",
        multiple=True,
        placement="advanced",
    ),
    dashboard.lookup_filter(
        "employment_type",
        label="Employment Type",
        lookup_endpoint=f"{HR_REFERENCE_LOOKUP}/employment-types/",
        multiple=True,
        placement="advanced",
    ),
    dashboard.lookup_filter(
        "employee",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        placement="advanced",
    ),
    # Satu-pilihan, bukan bercentang: dua pilihannya saling meniadakan,
    # dan mencentang keduanya berarti tidak menyaring sama sekali —
    # kontrol yang menawarkan keadaan yang sama dengan keadaan
    # kosongnya cuma menambah cara membingungkan diri sendiri.
    dashboard.lookup_filter(
        "reporting_status",
        label="Reporting Status",
        lookup_endpoint=REPORTING_STATUS_LOOKUP,
        placement="advanced",
    ),
]


HR_EMPLOYEE_REPORTING_AUDIT_SCHEMA = dashboard.schema(
    module="reports/hr/employee-reporting-audit",
    label="Employee Reporting Audit",
    endpoint=ENDPOINT,
    description=(
        "Struktur pegawai, garis pelaporan, dan akun login dalam satu "
        "tabel."
    ),
    filters=FILTERS,
    widgets=[TABLE_WIDGET],
)
