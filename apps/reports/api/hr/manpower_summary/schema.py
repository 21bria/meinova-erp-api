"""
Susunan layar Manpower Summary.

`schema_type="dashboard"` yang sama dengan dua laporan HR lainnya, dan
itu yang membuat filter berjenjang, panel Advanced Filter, kotak cari,
dan paginasi sisi server tidak perlu ditulis ulang sama sekali. Yang
ditambahkan laporan ini **nol runtime baru**: empat kartu KPI, lima
chart, dan satu tabel — semuanya tipe widget yang sudah dilayani
`MDashboard.vue` hari ini.

**Tidak ada pemilih periode**, dan itu bagian dari kontraknya. Laporan
ini potret hari ini: yang dihitung adalah orang yang berstatus aktif
saat request dilayani, dan tidak satu pun angkanya berubah karena bulan
yang dipilih. Headcount as-of tanggal tertentu adalah laporan yang
berbeda dan butuh riwayat penempatan — dicatat sebagai NEXT di
`docs/claude/reports.md`, bukan diam-diam ditebak dari master hari ini.
"""

from apps.framework.builders import dashboard


ORGANIZATION_LOOKUP = "/api/administration/organization/lookup"
HR_REFERENCE_LOOKUP = "/api/administration/references/hr/lookup"

ENDPOINT = "/api/reports/hr/manpower-summary/"


# ----------------------------------------------------------------------
# KPI
# ----------------------------------------------------------------------
#
# Empat kartu, `trend=False` semuanya. Laporan ini tidak punya periode,
# jadi tidak ada periode pembanding — "naik 0% dari bulan lalu" di bawah
# angka yang tidak pernah dibandingkan cuma derau yang terbaca sebagai
# fakta.
#
# Kartu keempat ada karena `Permanent + Contract = Headcount` **tidak
# dijamin** master: `EmploymentType` di seed hidup berisi enam jenis
# (Permanent, Contract, Daily Worker, Intern, Outsourcing, Consultant),
# dan pegawai yang belum punya jenis kepegawaian sama sekali tidak masuk
# keduanya. Menyembunyikan sisanya membuat tiga kartu pertama tidak
# pernah bisa dijumlahkan oleh yang membacanya.

STAT_WIDGETS = [
    dashboard.stat(
        "headcount",
        label="Total Headcount",
        icon="users",
        format="number",
        trend=False,
        span=3,
        order=10,
    ),
    dashboard.stat(
        "permanent",
        label="Permanent",
        icon="user-check",
        format="number",
        trend=False,
        span=3,
        order=20,
    ),
    dashboard.stat(
        "contract",
        label="Contract",
        icon="file-signature",
        format="number",
        trend=False,
        span=3,
        order=30,
    ),
    dashboard.stat(
        "unspecified_employment_type",
        label="No Employment Type",
        icon="circle-help",
        format="number",
        trend=False,
        span=3,
        order=40,
    ),
]


# ----------------------------------------------------------------------
# Breakdown
# ----------------------------------------------------------------------
#
# Tiga batang bertumpuk untuk sebaran organisasi, dua donut untuk
# proporsi klasifikasi. Bedanya bukan selera: sebaran per company /
# location / department dibaca sebagai **jumlah** (berapa orang di
# Sagea), sedangkan Employee Group dan Employment Type dibaca sebagai
# **proporsi** (berapa bagian dari seluruh tenaga kerja).
#
# Batangnya bertumpuk Permanent/Contract supaya satu chart menjawab
# sebaran sekaligus komposisinya; tinggi tiap batang tetap sama dengan
# headcount kelompok itu.

CHART_WIDGETS = [
    dashboard.bar(
        "company_breakdown",
        label="Headcount by Company",
        description=(
            "Tinggi batang = headcount company itu, dipecah Permanent "
            "dan Contract."
        ),
        x_label="Company",
        y_format="number",
        stacked=True,
        span=6,
        order=110,
    ),
    dashboard.bar(
        "location_breakdown",
        label="Headcount by Location",
        description=(
            "Delapan lokasi terbesar; sisanya dijumlahkan ke "
            "\"Lainnya\" supaya totalnya tetap utuh."
        ),
        x_label="Location",
        y_format="number",
        stacked=True,
        span=6,
        order=120,
    ),
    dashboard.bar(
        "department_breakdown",
        label="Headcount by Department",
        description=(
            "Department yang belum ditentukan tetap ikut sebagai "
            "kelompok tersendiri — orangnya tetap dihitung."
        ),
        x_label="Department",
        y_format="number",
        stacked=True,
        span=12,
        order=130,
    ),
    dashboard.donut(
        "employee_group_breakdown",
        label="Headcount by Employee Group",
        description=(
            "Proporsi per klasifikasi pegawai. Group yang seluruh "
            "Feature Applicability-nya mati tetap ikut — manpower "
            "adalah angka organisasi, bukan angka proses."
        ),
        span=6,
        order=140,
    ),
    dashboard.donut(
        "employment_type_breakdown",
        label="Headcount by Employment Type",
        description=(
            "Per jenis kepegawaian apa adanya dari master — bukan "
            "hanya Permanent dan Contract."
        ),
        span=6,
        order=150,
    ),
]


# ----------------------------------------------------------------------
# Tabel
# ----------------------------------------------------------------------
#
# **Agregat, bukan daftar pegawai.** Satu baris = satu kombinasi
# company → location → department. Daftar pegawai satu per satu sudah
# punya dua tempatnya sendiri (Employee Master untuk merawatnya,
# Employee Reporting Audit untuk mengauditnya); menyalinnya ke sini
# berarti tiga layar yang harus dijaga tetap sama tanpa ada yang
# meminta layar ketiga.

TABLE_WIDGET = dashboard.table(
    "manpower_table",
    label="Manpower Summary",
    description=(
        "Agregat per company, location, dan department. Headcount = "
        "jumlah pegawai aktif pada kelompok itu; Permanent + Contract "
        "+ Belum Ditentukan = Headcount."
    ),
    empty_text="No employees match these filters.",
    # Penghitung baris di kanan atas kartu menyebut **kelompok**, bukan
    # pegawai. Bawaan frontend-nya "Pegawai" — benar untuk dua laporan
    # HR lain yang satu barisnya satu orang, dan menyesatkan di sini:
    # "Pegawai 11" berdiri tepat di sebelah kartu KPI yang berbunyi 30.
    total_label="Group",
    sticky_columns=1,
    page_size=25,
    page_size_options=[25, 50, 100],
    searchable=True,
    search_placeholder="Cari company, location, atau department",
    span=12,
    order=200,
    columns=[
        dashboard.column("company", label="Company", width=200),
        dashboard.column("location", label="Location"),
        dashboard.column("department", label="Department"),
        dashboard.column("headcount", label="Headcount", format="number"),
        dashboard.column("permanent", label="Permanent", format="number"),
        dashboard.column("contract", label="Contract", format="number"),
        dashboard.column(
            "unspecified",
            label="Unspecified",
            format="number",
        ),
    ],
)


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------
#
# Kunci dan endpoint-nya sama persis dengan HR Period Summary dan
# Employee Reporting Audit. Bukan demi keseragaman tampilan:
# `expand_filter_values` dan `DataScopeService` sudah menegakkan artinya
# di satu tempat untuk seluruh dashboard, jadi filter yang ditulis
# dengan kunci yang sama otomatis berperilaku sama — dan filter yang
# ditulis sendiri adalah cara satu tombol Location berperilaku berbeda
# di tiga layar tanpa ada yang menyadarinya.
#
# Tidak ada filter Employee di sini. Laporan agregat yang disaring ke
# satu orang cuma menghasilkan satu baris berisi angka 1 — pertanyaannya
# sudah dijawab Employee Master.

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
        placement="quick",
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
        "employment_status",
        label="Employment Status",
        lookup_endpoint=f"{HR_REFERENCE_LOOKUP}/employment-statuses/",
        multiple=True,
        placement="advanced",
    ),
]


HR_MANPOWER_SUMMARY_SCHEMA = dashboard.schema(
    module="reports/hr/manpower-summary",
    label="Manpower Summary",
    endpoint=ENDPOINT,
    description=(
        "Jumlah dan komposisi tenaga kerja per struktur organisasi dan "
        "jenis kepegawaian. Potret hari ini, bukan laporan periode."
    ),
    filters=FILTERS,
    widgets=[*STAT_WIDGETS, *CHART_WIDGETS, TABLE_WIDGET],
)
