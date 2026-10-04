"""
Susunan layar Manpower Movement.

`schema_type="dashboard"` yang sama dengan empat laporan HR lainnya,
jadi filter berjenjang, panel Advanced Filter, kotak cari, dan
paginasi sisi server tidak perlu ditulis ulang. Yang ditambahkan
laporan ini **nol runtime baru**.

Bedanya dengan Manpower Summary dan Contract Expiry di sebelah: laporan
ini **punya pemilih periode**, dan itu bukan hiasan. Manpower Movement
adalah selisih antara dua tanggal; tanpa pemilih periode ia tidak punya
arti sama sekali. Dua laporan yang lain justru sebaliknya — potret hari
ini, dan `get_period()`-nya sengaja dikosongkan supaya tidak ada
rentang mati yang terbaca seperti rentang hidup.

Delapan kartu KPI dalam dua baris. Baris pertama **adalah** identitasnya,
dibaca kiri ke kanan:

```
Opening + Join + Transfer In − Transfer Out − Exit = Closing
```

Urutan itu yang menentukan `order`-nya, dan juga urutan batang di chart
jembatan di bawahnya. Kartu yang disusun ulang menurut selera akan
membuat pembacanya kehilangan persamaan yang justru jadi inti laporan.
"""

from apps.framework.builders import dashboard


ORGANIZATION_LOOKUP = "/api/administration/organization/lookup"
HR_REFERENCE_LOOKUP = "/api/administration/references/hr/lookup"

ENDPOINT = "/api/reports/hr/manpower-movement/"


# ----------------------------------------------------------------------
# KPI
# ----------------------------------------------------------------------
#
# `trend=False` di semuanya. Laporan ini **sudah** merupakan
# perbandingan antara awal dan akhir periode; menempelkan "naik 12%
# dari bulan lalu" di bawah angka yang artinya sendiri sudah selisih
# menghasilkan dua perbandingan bertumpuk yang tidak ada yang bisa
# membacanya.

STAT_WIDGETS = [
    dashboard.stat(
        "opening_headcount",
        label="Opening Headcount",
        icon="users",
        format="number",
        trend=False,
        span=2,
        order=10,
    ),
    dashboard.stat(
        "joins",
        label="Join",
        icon="user-plus",
        format="number",
        trend=False,
        span=2,
        order=20,
    ),
    dashboard.stat(
        "transfers_in",
        label="Transfer In",
        icon="log-in",
        format="number",
        trend=False,
        span=2,
        order=30,
    ),
    dashboard.stat(
        "transfers_out",
        label="Transfer Out",
        icon="log-out",
        format="number",
        trend=False,
        span=2,
        order=40,
    ),
    dashboard.stat(
        "exits",
        label="Exit",
        icon="user-minus",
        format="number",
        trend=False,
        span=2,
        order=50,
    ),
    dashboard.stat(
        "closing_headcount",
        label="Closing Headcount",
        icon="users",
        format="number",
        trend=False,
        span=2,
        order=60,
    ),

    # Baris kedua. Net Change bisa dihitung sendiri dari dua kartu di
    # ujung baris pertama, dan justru itu gunanya berdiri sendiri:
    # yang dibawa pulang pembaca laporan pergerakan adalah satu angka
    # ini, bukan selisih yang harus dihitung di kepala.
    dashboard.stat(
        "net_change",
        label="Net Change",
        icon="trending-up",
        format="number",
        trend=False,
        span=6,
        order=70,
    ),

    # Bukan hiasan, dan bukan KPI manajemen: ini penjaga supaya
    # populasi laporan bisa direkonsiliasi dengan Manpower Summary.
    # Pegawai tanpa tanggal bergabung tidak bisa ditempatkan di periode
    # mana pun, jadi ia dikeluarkan — dan pengeluaran yang tidak
    # terlihat adalah cara paling mudah membuat dua layar berbeda angka
    # tanpa ada yang bisa menjelaskan sebabnya.
    dashboard.stat(
        "missing_join_date",
        label="No Join Date",
        icon="calendar-off",
        format="number",
        trend=False,
        span=6,
        order=80,
    ),
]


# ----------------------------------------------------------------------
# Chart
# ----------------------------------------------------------------------

CHART_WIDGETS = [
    dashboard.bar(
        "headcount_bridge",
        label="Headcount Bridge",
        description=(
            "Opening + Join + Transfer In − Transfer Out − Exit = "
            "Closing. Transfer Out dan Exit digambar negatif."
        ),
        x_label="Ethnicity",
        y_format="number",
        # Tegak, bukan mendatar. Kategorinya punya urutan alami — ini
        # sebuah persamaan yang dibaca kiri ke kanan — dan aturan yang
        # sama sudah dipakai Contract Expiry Timeline. Bawaan mendatar
        # tetap benar untuk kategori yang tidak berurutan.
        horizontal=False,
        span=7,
        order=110,
    ),
    dashboard.donut(
        "exit_by_reason",
        label="Exit by Reason",
        description=(
            "Alasan keluar pada periode ini, terbanyak dulu. Delapan "
            "teratas; sisanya dijumlahkan ke \"Lainnya\"."
        ),
        y_format="number",
        # Donut, dan yang dibawanya **komposisi**: berapa bagian dari
        # keluarnya orang yang berasal dari tiap alasan. Angka
        # tengahnya sama dengan KPI Exit, dan memang harus sama.
        span=5,
        order=120,
    ),
]


# ----------------------------------------------------------------------
# Tabel
# ----------------------------------------------------------------------
#
# **Satu baris per peristiwa, bukan per pegawai.** Orang yang bergabung
# lalu pindah lokasi dalam periode yang sama muncul dua kali, dan itu
# memang yang harus terlihat: yang dicari pembacanya adalah pergerakan,
# dan menggabungkannya per orang justru menghapus salah satunya.
#
# Kronologis, bukan terbaru dulu. Tabel ini adalah buku besar yang
# menjelaskan bagaimana Opening berubah jadi Closing, dan buku besar
# yang dibaca mundur tidak menjelaskan apa-apa.

TABLE_WIDGET = dashboard.table(
    "movement_table",
    label="Manpower Movement",
    description=(
        "Satu baris per peristiwa, kronologis. Join + Transfer In − "
        "Transfer Out − Exit = Net Change. Internal Move diterbitkan "
        "tapi tidak mengubah jumlah kepala."
    ),
    empty_text="No movement for this period and filters.",
    sticky_columns=2,
    page_size=25,
    page_size_options=[25, 50, 100],
    searchable=True,
    search_placeholder="Cari nomor pegawai, nama, atau nomor dokumen",
    span=12,
    order=200,
    columns=[
        dashboard.column("employee_number", label="Employee ID", width=120),
        dashboard.column("employee_name", label="Employee Name", width=200),
        dashboard.column(
            "movement_date",
            label="Effective Date",
            format="date",
            width=130,
        ),
        dashboard.column("movement_type", label="Movement", width=130),
        dashboard.column("movement_from", label="From", width=220),
        dashboard.column("movement_to", label="To", width=220),
        dashboard.column("company", label="Company", width=180),
        dashboard.column("location", label="Location", width=160),
        dashboard.column("department", label="Department", width=160),
        dashboard.column("position", label="Position", width=170),
        dashboard.column("document_number", label="Document", width=150),
        dashboard.column("reason", label="Reason", width=220),
    ],
)


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------
#
# Kunci dan endpoint organisasi sama persis dengan tiga laporan HR
# lainnya, dan itu bukan demi keseragaman tampilan: `expand_filter_values`
# dan `DataScopeService` sudah menegakkan artinya di satu tempat untuk
# seluruh dashboard.
#
# **Yang harus disadari saat membaca hasilnya:** filter Department,
# Section, Employee Group, dan Employment Type/Status mempersempit
# Opening/Closing/Join/Exit, tapi **tidak** ikut menentukan sebuah
# mutasi masuk atau keluar. `EmployeeAction` cuma menyimpan
# company/branch/location sebagai id di kedua ujungnya; sisi lama
# department hanya ada sebagai nama di `values_before`, dan mencocokkan
# riwayat lewat nama adalah cara laporan mulai berbohong begitu ada
# master yang diganti nama. Alasannya lengkap di docstring
# `services.py`.

FILTERS = [
    dashboard.period_filter(
        mode="month",
        modes=["month", "quarter", "year", "custom"],
    ),
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


# **Tidak ada filter Movement Type**, dan itu keputusan, bukan kelalaian.
#
# Contract Expiry punya filter Expiry Status karena di sana seluruh KPI
# lahir dari baris yang sama — mempersempit barisnya mempersempit
# semuanya, konsisten. Di sini tidak: Opening dan Closing Headcount
# dihitung dari tanggal, **bukan** dari baris pergerakan. Filter yang
# menyisakan Exit saja akan mengubah lima kartu dan membiarkan dua
# lainnya, dan layarnya berhenti menjadi persamaan:
#
#     Opening + Join + Transfer In − Transfer Out − Exit ≠ Closing
#
# Persamaan itu **adalah** laporannya. Filter yang memecahkannya diam-diam
# persis jenis kegagalan yang audit sebelum laporan ini ditulis cari —
# angka yang salah tapi terbaca benar. Yang dibutuhkan orang yang cuma
# ingin melihat satu jenis sudah ada tanpa memecahkan apa pun: kolom
# Movement berdiri di tabel, dan tabelnya bisa diurutkan dan dicari.


HR_MANPOWER_MOVEMENT_SCHEMA = dashboard.schema(
    module="reports/hr/manpower-movement",
    label="Manpower Movement",
    endpoint=ENDPOINT,
    description=(
        "Perubahan jumlah tenaga kerja pada periode terpilih: join, "
        "mutasi, dan keluar, beserta Opening dan Closing Headcount-nya."
    ),
    filters=FILTERS,
    widgets=[*STAT_WIDGETS, *CHART_WIDGETS, TABLE_WIDGET],
)
