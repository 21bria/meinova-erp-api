"""
Susunan layar HR Period Summary.

Bentuknya sengaja `schema_type="dashboard"` yang sama dengan HR
Dashboard: filter di kanan atas, kartu KPI sebaris, lalu grid 12 kolom.
Yang membedakan laporan dari dashboard bukan tampilannya, melainkan apa
yang ada **di bawah** chart — satu tabel lebar berisi baris per pegawai
yang bisa ditelusuri ke dokumen sumbernya.

Membuat runtime kedua untuk itu berarti dua tata letak, dua pemilih
periode, dan dua cara memuat filter yang harus dijaga tetap sama. Yang
ditambahkan justru satu tipe widget baru (`table`) di runtime yang sudah
ada.
"""

from apps.framework.builders import dashboard

from .metrics import Metric


ORGANIZATION_LOOKUP = "/api/administration/organization/lookup"
HR_REFERENCE_LOOKUP = "/api/administration/references/hr/lookup"


# ----------------------------------------------------------------------
# KPI
# ----------------------------------------------------------------------
#
# Enam kartu, mengikuti baris KPI HR Dashboard — jumlah yang sama supaya
# grid `xl:grid-cols-6` terisi penuh dan barisnya tidak menggantung.
# Metrik lain (Late, Early, Off Worked, Holiday Worked, per-jenis cuti)
# tetap ada, tempatnya di kolom tabel: kartu KPI yang berjumlah tujuh
# belas berhenti menjadi ringkasan.

STAT_WIDGETS = [
    dashboard.stat(
        "headcount",
        label="Headcount",
        icon="users",
        format="number",
        span=2,
        order=10,
    ),
    dashboard.stat(
        "attendance_rate",
        label="Attendance Rate",
        icon="calendar-check",
        format="percent",
        precision=1,
        span=2,
        order=20,
    ),
    dashboard.stat(
        "present_days",
        label="Present",
        icon="user-check",
        format="number",
        span=2,
        order=30,
    ),
    dashboard.stat(
        "absent_days",
        label="Absent",
        icon="user-x",
        format="number",
        span=2,
        order=40,
    ),
    dashboard.stat(
        "leave_days",
        label="Leave",
        icon="palmtree",
        format="number",
        precision=1,
        span=2,
        order=50,
    ),
    dashboard.stat(
        "overtime_hours",
        label="Total OT",
        icon="briefcase-business",
        format="number",
        precision=1,
        span=2,
        order=60,
    ),
]


# ----------------------------------------------------------------------
# Chart
# ----------------------------------------------------------------------

CHART_WIDGETS = [
    dashboard.bar(
        "attendance_trend",
        label="Attendance Trend",
        description=(
            "Hadir, telat, dan tidak hadir per satuan periode. Cuti, "
            "libur, dan hari off tidak dihitung sebagai peluang hadir."
        ),
        x_label="Period",
        y_format="number",
        stacked=True,
        horizontal=False,
        span=8,
        order=110,
    ),
    dashboard.donut(
        "leave_breakdown",
        label="Leave Breakdown",
        description=(
            "Annual, Sick, Other Leave, dan Unpaid adalah pengelompokan "
            "laporan; tipe cuti aslinya tetap terbaca di drill-down."
        ),
        span=4,
        order=120,
    ),
    dashboard.bar(
        "overtime_trend",
        label="Overtime Trend",
        description=(
            "Jam lembur per kategori hari — terjadwal, off, dan libur."
        ),
        x_label="Period",
        y_format="number",
        stacked=True,
        horizontal=False,
        span=8,
        order=130,
    ),
    dashboard.bar(
        "department_comparison",
        label="Department Comparison",
        description="Hadir dan tidak hadir per department.",
        x_label="Department",
        y_format="number",
        stacked=True,
        horizontal=True,
        span=4,
        order=140,
    ),
]


# ----------------------------------------------------------------------
# Employee Period Summary
# ----------------------------------------------------------------------
#
# Delapan belas kolom, dan tabel ini memang digeser mendatar. Dua kolom
# pertama terkunci: angka Total OT tanpa nama pegawai di sebelah kirinya
# tidak berarti apa-apa.
#
# `drilldown` pada kolom = nama metrik di `metrics.py`. Kolom tanpa
# `drilldown` tidak bisa ditekan, dan itu benar untuk kolom identitas.

def _metric_column(key: str, label: str, **extra):
    return dashboard.column(
        key,
        label=label,
        format="number",
        drilldown=key,
        **extra,
    )


TABLE_WIDGET = dashboard.table(
    "employee_period_summary",
    label="Employee Period Summary",
    description=(
        "Satu baris per pegawai untuk periode dan filter yang sedang "
        "dipilih. Tekan angkanya untuk melihat catatan sumbernya."
    ),
    empty_text="No employees for this period and filters.",
    # Nomor **dan** nama ikut terkunci saat digeser mendatar. Sebelum
    # kolom Employee ID ada, satu kolom terkunci berarti namanya yang
    # tinggal; membiarkannya satu sekarang membuat yang tinggal cuma
    # nomor, dan sembilan belas kolom angka di sebelahnya jadi tidak
    # bisa dibaca milik siapa.
    sticky_columns=2,
    # Dipaginasi di server. Satu klien dengan tiga ribu pegawai berarti
    # tiga ribu baris berisi delapan belas kolom dalam satu respons —
    # dan yang lebih dulu menyerah bukan jaringannya, melainkan tabel
    # HTML yang harus dirender sekaligus.
    #
    # Yang dipotong **hanya tabelnya**: KPI, chart, dan baris Total tetap
    # menghitung seluruh pegawai yang lolos filter, jadi pindah halaman
    # tidak menggeser satu angka pun di luar tabel.
    page_size=25,
    page_size_options=[25, 50, 100],
    searchable=True,
    search_placeholder="Cari nama atau nomor pegawai",
    search_placeholder_key="employee",
    span=12,
    order=200,
    columns=[
        # Nomor pegawai lebih dulu, lalu namanya. Kuncinya
        # `employee_number` — kolom yang sudah ada di `Employee` dan
        # sudah dikirim `table_row()`; tidak ada field baru di sini.
        #
        # Yang **tidak** berubah karenanya: drill-down tetap memakai
        # `employee_id` internal (nomor pegawai boleh diketik ulang HR
        # dan boleh kosong, jadi ia bukan kunci), dan baris Total tetap
        # melewatinya — menjumlahkan nomor pegawai menghasilkan angka
        # yang tidak salah hitung, cuma tidak berarti apa pun.
        dashboard.column(
            "employee_number",
            label="Employee ID",
            # "HO001" di kotak selebar 224px bawaan meninggalkan jarak
            # kosong sampai kolom nama — terbaca seperti kolomnya salah
            # pasang. 104px memuat nomor terpanjang yang lazim
            # ("SITE-0001") tanpa memotongnya.
            width=104,
        ),
        dashboard.column("employee", label="Employee"),
        dashboard.column("location", label="Location"),

        _metric_column(Metric.SCHEDULED, "Scheduled"),
        _metric_column(Metric.PRESENT, "Present"),
        _metric_column(Metric.ABSENT, "Absent"),

        _metric_column(Metric.ANNUAL, "Annual"),
        _metric_column(Metric.SICK, "Sick"),
        _metric_column(Metric.OTHER_LEAVE, "Other Leave"),
        _metric_column(Metric.UNPAID, "Unpaid"),

        _metric_column(Metric.FIELD_BREAK, "Field Break"),

        _metric_column(Metric.OFF_WORKED, "Off Worked"),
        _metric_column(Metric.HOLIDAY_WORKED, "Holiday Worked"),

        _metric_column(Metric.LATE, "Late", suffix="x"),
        _metric_column(Metric.EARLY, "Early", suffix="x"),

        _metric_column(Metric.OT_REGULAR, "Regular OT", suffix="h"),
        _metric_column(Metric.OT_OFF, "Off OT", suffix="h"),
        _metric_column(Metric.OT_HOLIDAY, "Holiday OT", suffix="h"),
        _metric_column(Metric.OT_TOTAL, "Total OT", suffix="h"),
    ],
)


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------
#
# Period From / Period To dilayani mode "custom" pada filter periode
# yang sudah ada — pemilihnya satu tombol berisi rentang, lengkap dengan
# preset dan panah geser. Dua input tanggal terpisah berarti pemilih
# periode kedua di aplikasi ini, dengan aturan awal-minggu dan batas
# bulan yang harus dijaga tetap sama dengan yang pertama.
#
# Bawaannya bulan berjalan, sama dengan HR Dashboard.

FILTERS = [
    dashboard.period_filter(
        mode="month",
        modes=["day", "week", "month", "quarter", "year", "custom"],
    ),
    dashboard.lookup_filter(
        "company",
        label="Company",
        lookup_endpoint=f"{ORGANIZATION_LOOKUP}/companies/",
        # **Bercentang banyak**, sama seperti Location. Laporan gabungan
        # seorang GM yang memegang beberapa company tidak bisa disusun
        # dari dropdown satu-pilihan; isinya sendiri sudah tersaring
        # Organization Scope di sisi lookup.
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
        # Dihitung backend, lihat `MeSerializer.get_self_filter_values`:
        # lokasi penempatan untuk hampir semua orang, seluruh lokasi
        # dalam cakupan untuk direksi. Tetap lewat `DataScopeService`.
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
    # Dropdown pegawai memakai endpoint lookup Employee yang sudah
    # tersaring cakupan data — bukan daftar nama seluruh tenant.
    dashboard.lookup_filter(
        "employee",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        placement="advanced",
    ),
]


HR_PERIOD_SUMMARY_SCHEMA = dashboard.schema(
    module="reports/hr/period-summary",
    label="HR Period Summary",
    endpoint="/api/reports/hr/period-summary/",
    description=(
        "Rekap kehadiran, cuti, dan lembur per pegawai pada periode "
        "terpilih."
    ),
    filters=FILTERS,
    widgets=[
        *STAT_WIDGETS,
        *CHART_WIDGETS,
        TABLE_WIDGET,
    ],
)


# Rincian dilayani `<endpoint>drilldown/`, dan frontend menurunkannya
# dari `schema.endpoint` alih-alih membaca kunci tersendiri:
# `build_dashboard_schema` cuma meneruskan module/filters/widgets, jadi
# kunci tambahan di sini akan hilang diam-diam saat schema-nya
# diregenerate — konfigurasi mati yang terbaca seperti konfigurasi
# hidup.
DRILLDOWN_PATH = "drilldown/"
