"""
Susunan dashboard modul Administration.

Jangan tertukar dengan `apps/administration/api/dashboard/`: yang itu
dashboard **home** — katalog aplikasi, pintasan, dan tata letak widget
per pengguna yang disimpan di database. Yang ini dashboard **modul**,
sejajar dengan `hr/dashboard`: susunannya ditentukan kode, sama untuk
semua orang, datanya dihitung dari master dan jejak audit.

`framework_module` sengaja `administration/dashboard` walau paket
Python-nya bernama `overview` — nama module itu yang menentukan letak
berkas hasil generate di repo Nuxt (`app/modules/administration/
dashboard/`), dan halaman `app/pages/administration/index.vue` sudah
mengimpor dari sana sejak versi statisnya.
"""

from apps.framework.builders import dashboard


# Struktur organisasi tidak berubah tiap bulan, jadi kartunya
# `trend=False`: "naik 0% dari bulan lalu" di bawah setiap angka cuma
# derau. Yang bertren cuma aktivitas.
STAT_WIDGETS = [
    dashboard.stat(
        "total_companies",
        label="Company",
        icon="building-2",
        format="number",
        trend=False,
        span=2,
        order=10,
    ),
    dashboard.stat(
        "total_branches",
        label="Branch",
        icon="network",
        format="number",
        trend=False,
        span=2,
        order=20,
    ),
    dashboard.stat(
        "total_locations",
        label="Location",
        icon="map-pin",
        format="number",
        trend=False,
        span=2,
        order=30,
    ),
    dashboard.stat(
        "active_users",
        label="Active Users",
        icon="users",
        format="number",
        trend=False,
        span=2,
        order=40,
    ),
    dashboard.stat(
        "audit_events",
        label="Recorded Activity",
        icon="activity",
        format="number",
        span=2,
        order=50,
    ),
    dashboard.stat(
        "configuration_issues",
        label="Configuration Issues",
        icon="triangle-alert",
        format="number",
        trend=False,
        span=2,
        order=60,
    ),
]


CHART_WIDGETS = [
    dashboard.line(
        "activity_trend",
        label="Activity Trend",
        description=(
            "Perubahan data yang tercatat di jejak audit; satuannya "
            "mengikuti periode yang dipilih."
        ),
        x_label="Period",
        span=8,
        order=110,
    ),
    dashboard.donut(
        "activity_by_module",
        label="Activity by Module",
        span=4,
        order=120,
    ),

    # Menggantikan "Master Records Growth" yang dulu memakai deret
    # bulanan karangan. Ini bukan tren — ini bentuk organisasinya, dan
    # itu yang sebenarnya dicari di layar ini: level mana yang sudah
    # terisi, mana yang masih kosong.
    dashboard.bar(
        "organization_structure",
        label="Organization Structure",
        description="Jumlah baris master per level.",
        x_label="Level",
        span=4,
        order=130,
    ),
]


LIST_WIDGETS = [
    dashboard.listing(
        "configuration_health",
        label="Configuration Health",
        description=(
            "Pemeriksaan sungguhan terhadap master yang wajib terisi "
            "sebelum modul lain bisa dipakai."
        ),
        # Urutannya mengikuti cara `MDashboardList` merender: kolom
        # pertama jadi judul baris, kolom kedua jadi keterangan di
        # bawahnya, sisanya jadi nilai di kanan. Status ditaruh terakhir
        # supaya jatuh di kanan sebagai badge, bukan jadi subjudul —
        # dan `hint` yang panjang tidak terjepit di kolom kanan.
        columns=[
            dashboard.column("name", label="Item"),
            dashboard.column("hint", label="Remarks"),
            dashboard.column("status", label="Status", format="status"),
        ],
        empty_text="No checks to show.",
        span=4,
        order=140,
    ),

    # Sengaja di luar filter periode: libur pekan depan tetap harus
    # terlihat walau layarnya sedang menampilkan angka bulan lalu.
    dashboard.listing(
        "upcoming_holidays",
        label="Upcoming Holidays",
        description="90 hari ke depan, di luar filter periode.",
        columns=[
            dashboard.column("name", label="Name"),
            dashboard.column("scope", label="Applies To"),
            dashboard.column("date", label="Date", format="date"),
            dashboard.column("days_left", label="Days Remaining", format="number"),
        ],
        empty_text="No holidays registered in the next 90 days.",
        link="/administration/calendar",
        limit=6,
        span=4,
        order=150,
    ),

    dashboard.listing(
        "recent_audit",
        label="Recent Activity",
        description="Perubahan data terakhir beserta pelakunya.",
        # `object` di depan supaya yang terbaca lebih dulu adalah **apa**
        # yang berubah; siapa dan kapan menyusul. Daftar yang dimulai
        # dari jam memaksa pembacanya memindai ke kanan untuk tahu baris
        # itu soal apa.
        columns=[
            dashboard.column("object", label="Object"),
            dashboard.column("user", label="By"),
            dashboard.column("action", label="Action"),
            dashboard.column("module", label="Module"),
            dashboard.column("time", label="Time", format="datetime"),
        ],
        empty_text="No activity recorded yet.",
        link="/administration/audit",
        limit=8,
        span=12,
        order=160,
    ),
]


ADMINISTRATION_DASHBOARD_SCHEMA = dashboard.schema(
    module="administration/dashboard",
    label="Administration Dashboard",
    endpoint="/api/administration/overview/",
    description=(
        "Struktur organisasi, kesehatan konfigurasi, dan aktivitas sistem."
    ),
    filters=[
        dashboard.period_filter(
            mode="month",
            modes=["day", "week", "month", "quarter", "year", "custom"],
        ),
        dashboard.lookup_filter(
            "company",
            label="Company",
            lookup_endpoint=(
                "/api/administration/organization/lookup/companies/"
            ),
            # **Bercentang banyak**, sama seperti Location. Seorang GM
            # yang cakupannya tiga company harus bisa membaca ketiganya
            # sekaligus, lalu mempersempit ke dua di antaranya —
            # dropdown satu-pilihan cuma menawarkan "satu company" atau
            # "seluruh tenant", dan tidak ada di antaranya.
            #
            # Isinya sudah tersaring Organization Scope di sisi lookup
            # (`OrganizationScopedLookup.data_scope`), jadi mencentang
            # semuanya tetap tidak melebihi cakupan pemegang akun.
            multiple=True,
        ),
    ],
    widgets=[
        *STAT_WIDGETS,
        *CHART_WIDGETS,
        *LIST_WIDGETS,
    ],
)
