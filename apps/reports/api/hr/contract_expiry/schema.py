"""
Susunan layar Contract Expiry.

`schema_type="dashboard"` yang sama dengan tiga laporan HR lainnya, dan
itu yang membuat filter berjenjang, panel Advanced Filter, kotak cari,
dan paginasi sisi server tidak perlu ditulis ulang. Yang ditambahkan
laporan ini **nol runtime baru**: lima kartu KPI, dua chart, dan satu
tabel — seluruhnya tipe widget yang sudah dilayani `MDashboard.vue`
hari ini.

**Tidak ada pemilih periode dan tidak ada pemilih tanggal**, dan itu
bagian dari kontraknya. Laporan ini potret **hari ini**: sisa hari
dihitung dari tanggal saat request dilayani. Pemilih tanggal berarti
runtime frontend baru (`MDashboardFilters.vue` hanya melayani pemilih
periode dan dropdown lookup), dan memakai pemilih periode **bulan**
untuk laporan yang butuh satu tanggal berarti kotak yang terbaca
seperti konfigurasi hidup padahal tidak menggeser satu angka pun. As Of
Date yang bisa dipilih tercatat sebagai NEXT di `docs/claude/reports.md`.

Dua chart, dan sengaja **cuma** dua. Company, Location, dan Employment
Type sudah berdiri sebagai filter dan sebagai kolom tabel; menambahkan
chart untuk masing-masingnya menghasilkan layar yang harus digulir
sebelum sampai ke tabel yang justru berisi daftar orang yang harus
dihubungi.
"""

from apps.framework.builders import dashboard


ORGANIZATION_LOOKUP = "/api/administration/organization/lookup"
HR_REFERENCE_LOOKUP = "/api/administration/references/hr/lookup"

ENDPOINT = "/api/reports/hr/contract-expiry/"


# ----------------------------------------------------------------------
# KPI
# ----------------------------------------------------------------------
#
# Empat bucket mendesak + satu penyebut. `trend=False` semuanya:
# laporan ini tidak punya periode, jadi tidak ada periode pembanding —
# "naik 0% dari bulan lalu" di bawah angka yang tidak pernah
# dibandingkan cuma derau yang terbaca sebagai fakta.
#
# Kartu kelima ada karena empat angka pertama berdiri tanpa penyebut
# kalau ia tidak ada: "Expired 2" berarti sangat berbeda di tenant
# berkontrak 5 orang dan di tenant berkontrak 500. Invariant-nya
# ditulis di keterangan tabel — `Expired + ≤30 + 31–60 + 61–90 + >90 +
# Tanpa Tanggal Akhir = Total Kontrak Aktif`.

STAT_WIDGETS = [
    dashboard.stat(
        "expired",
        label="Expired",
        icon="alert-octagon",
        format="number",
        trend=False,
        span=2,
        order=10,
    ),
    dashboard.stat(
        "expiring_30",
        label="≤ 30 Days",
        icon="alert-triangle",
        format="number",
        trend=False,
        span=2,
        order=20,
    ),
    dashboard.stat(
        "expiring_60",
        label="31–60 Days",
        icon="clock",
        format="number",
        trend=False,
        span=3,
        order=30,
    ),
    dashboard.stat(
        "expiring_90",
        label="61–90 Days",
        icon="calendar-clock",
        format="number",
        trend=False,
        span=3,
        order=40,
    ),
    dashboard.stat(
        "active_contracts",
        label="Total Active Contracts",
        icon="file-signature",
        format="number",
        trend=False,
        span=2,
        order=50,
    ),
]


# ----------------------------------------------------------------------
# Chart
# ----------------------------------------------------------------------

CHART_WIDGETS = [
    dashboard.bar(
        "expiry_timeline",
        label="Contract Expiry Timeline",
        description="Kontrak yang berakhir dalam 12 bulan ke depan.",
        x_label="Ending Month",
        y_format="number",
        # Tegak, bukan mendatar. Sumbu chart ini **waktu**, dan waktu
        # yang berjalan ke bawah dibaca lebih lambat daripada yang
        # berjalan ke kanan — dua belas label bulan berurutan adalah
        # satu-satunya bar chart di sini yang kategorinya punya urutan
        # alami. Bawaan mendatar tetap benar untuk chart di sebelahnya:
        # nama department panjang dan tidak berurutan.
        horizontal=False,
        span=8,
        order=110,
    ),
    dashboard.donut(
        "expiring_by_department",
        label="Expiring by Department",
        description=(
            "Kontrak yang perlu ditindaklanjuti (Expired sampai 90 "
            "hari) per Department, terbanyak dulu. Delapan teratas; "
            "sisanya dijumlahkan ke \"Lainnya\"."
        ),
        y_format="number",
        # Donut, dan yang dibawanya **komposisi**: berapa bagian dari
        # beban tindak lanjut yang dipegang tiap department. Angka
        # tengahnya total yang perlu ditindaklanjuti — bukan Total
        # Kontrak Aktif, dan memang harus berbeda.
        #
        # Tidak ada `x_label`/`horizontal` di sini: donut tidak punya
        # sumbu, dan mencantumkannya cuma menyisakan kunci yang tidak
        # pernah dibaca siapa pun.
        span=4,
        order=120,
    ),
]


# ----------------------------------------------------------------------
# Tabel
# ----------------------------------------------------------------------
#
# **Daftar orang, bukan agregat.** Bedanya dengan tabel Manpower
# Summary bukan selera: yang dicari pembaca laporan ini adalah nama
# yang harus dihubungi minggu ini, dan agregat per department justru
# menghapusnya. Agregatnya sudah ada — dua chart di atasnya.
#
# Urutan bawaan yang paling mendesak lebih dulu (Expired → terdekat →
# terjauh) ditegakkan service, bukan frontend: tabel yang harus
# diurutkan sendiri oleh pembacanya sebelum berguna adalah tabel yang
# sebagian pembacanya tidak pernah urutkan.

TABLE_WIDGET = dashboard.table(
    "contract_table",
    label="Contract Expiry",
    description=(
        "Satu baris per kontrak berjalan, yang paling mendesak lebih "
        "dulu. Expired + ≤30 + 31–60 + 61–90 + >90 + Tanpa Tanggal "
        "Akhir = Total Kontrak Aktif."
    ),
    empty_text="No active contracts match these filters.",
    sticky_columns=2,
    page_size=25,
    page_size_options=[25, 50, 100],
    searchable=True,
    search_placeholder="Cari nomor atau nama pegawai",
    span=12,
    order=200,
    columns=[
        dashboard.column("employee_number", label="Employee ID", width=120),
        dashboard.column("employee_name", label="Employee Name", width=200),
        dashboard.column("company", label="Company", width=180),
        dashboard.column("location", label="Location", width=160),
        dashboard.column("department", label="Department", width=160),
        dashboard.column("section", label="Section", width=150),
        dashboard.column("position", label="Position", width=170),
        dashboard.column("employee_group", label="Employee Group", width=150),
        dashboard.column("employment_type", label="Employment Type", width=150),
        dashboard.column(
            "employment_status",
            label="Employment Status",
            width=150,
        ),
        dashboard.column("contract_type", label="Contract Type", width=140),
        dashboard.column(
            "contract_start",
            label="Contract Start",
            format="date",
            width=130,
        ),
        dashboard.column(
            "contract_end",
            label="Contract End",
            format="date",
            width=130,
        ),
        dashboard.column(
            "days_remaining",
            label="Days Remaining",
            format="number",
            width=130,
        ),
        dashboard.column("expiry_status", label="Expiry Status", width=140),
        dashboard.column("renewal_status", label="Renewal Status", width=150),
        dashboard.column(
            "renewal_document",
            label="Renewal Doc",
            width=150,
        ),
        dashboard.column("report_to_name", label="Report To", width=180),
    ],
)


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------
#
# Kunci dan endpoint organisasi sama persis dengan tiga laporan HR
# lainnya. Bukan demi keseragaman tampilan: `expand_filter_values` dan
# `DataScopeService` sudah menegakkan artinya di satu tempat untuk
# seluruh dashboard, jadi filter yang ditulis dengan kunci yang sama
# otomatis berperilaku sama — dan filter yang ditulis sendiri adalah
# cara satu tombol Location berperilaku berbeda di empat layar tanpa
# ada yang menyadarinya.
#
# Dua filter terakhir menunjuk endpoint milik laporan ini sendiri:
# Expiry Status **dihitung** dari tanggal dan Renewal Status dibacakan
# dari dokumen — keduanya tidak punya tabel master, dan membuatkan
# tabel referensi untuk nilai yang ditentukan kode berarti master yang
# bisa disunting sampai tidak lagi cocok dengan yang dibaca laporannya.

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
    dashboard.lookup_filter(
        "expiry_status",
        label="Expiry Status",
        lookup_endpoint=f"{ENDPOINT}expiry-status/",
        placement="advanced",
    ),
    dashboard.lookup_filter(
        "renewal_status",
        label="Renewal Status",
        lookup_endpoint=f"{ENDPOINT}renewal-status/",
        placement="advanced",
    ),
]


HR_CONTRACT_EXPIRY_SCHEMA = dashboard.schema(
    module="reports/hr/contract-expiry",
    label="Contract Expiry",
    endpoint=ENDPOINT,
    description=(
        "Kontrak yang sudah atau akan habis, beserta status "
        "perpanjangannya. Potret hari ini, bukan laporan periode."
    ),
    filters=FILTERS,
    widgets=[*STAT_WIDGETS, *CHART_WIDGETS, TABLE_WIDGET],
)
