from apps.framework.builders import dashboard


# Kartu "Kinerja Tercapai" dan "Total Payroll" dari rancangan awal tidak
# ada di sini: `apps/hr/models/performance.py` masih file kosong dan
# payroll belum punya model payroll run — jadi angkanya tidak bisa
# dihitung dari data. Tempatnya diisi Lembur dan Lowongan Terbuka, yang
# datanya nyata. Tambahkan lagi begitu dua modul itu jadi.
STAT_WIDGETS = [
    dashboard.stat(
        "total_employees",
        label="Total Employees",
        icon="users",
        format="number",
        span=2,
        order=10,
    ),
    dashboard.stat(
        "attendance_rate",
        label="Attendance (Average)",
        icon="calendar-check",
        format="percent",
        precision=1,
        span=2,
        order=20,
    ),
    dashboard.stat(
        "active_leaves",
        label="Active Leave",
        icon="clock-3",
        format="number",
        span=2,
        order=30,
    ),
    dashboard.stat(
        "overtime_hours",
        label="Overtime Hours",
        icon="briefcase-business",
        format="number",
        precision=1,
        span=2,
        order=40,
    ),
    dashboard.stat(
        "turnover_rate",
        label="Turnover Rate",
        icon="trending-down",
        format="percent",
        precision=2,
        span=2,
        order=50,
    ),
    dashboard.stat(
        "open_vacancies",
        label="Open Vacancies",
        icon="user-plus",
        format="number",
        span=2,
        order=60,
    ),
]


CHART_WIDGETS = [
    # Batang bertumpuk, bukan garis persentase.
    #
    # Versi lamanya menggambar rata-rata kehadiran sebagai garis, dan di
    # perusahaan yang sehat angka itu duduk di 97–99% sepanjang tahun:
    # garis yang tidak pernah keluar dari 3% teratas sumbunya nyaris
    # tidak memberi tahu apa pun, sementara sumbu otomatis membuat riak
    # setengah persen tergambar seperti jurang. Yang ditindaklanjuti HR
    # tiap pagi adalah cacahannya — berapa orang telat, berapa tidak
    # masuk. Persentasenya tetap ada, di kartu KPI Tingkat Kehadiran.
    dashboard.bar(
        "attendance_trend",
        label="Daily Attendance",
        description=(
            "Jumlah pegawai hadir, telat, dan tidak hadir. Cuti dan "
            "hari libur tidak dihitung."
        ),
        x_label="Period",
        y_format="number",
        stacked=True,
        horizontal=False,
        span=8,
        order=110,
    ),
    dashboard.donut(
        "employees_by_unit",
        label="Employee Distribution by Work Unit",
        span=4,
        order=120,
    ),
    dashboard.bar(
        "employees_by_education",
        label="Employee Distribution by Education Level",
        x_label="Level",
        span=4,
        order=130,
    ),
]


LIST_WIDGETS = [
    dashboard.listing(
        "leave_recap",
        label="Leave Recap",
        description="Pemakaian cuti per tipe pada periode terpilih.",
        # Kolom kedua bertipe teks jadi **keterangan di bawah judul
        # baris**, bukan angka di kanan — itu aturan `MDashboardList`.
        # Dipakai di sini supaya barisnya dua tingkat, sebentuk dengan
        # Cuti Terbaru yang duduk di sebelahnya: satu kartu berbaris
        # satu tingkat dan satu lagi dua tingkat membuat keduanya
        # terbaca seperti dua komponen berbeda, padahal isinya
        # bersaudara dan memang dibaca bergantian.
        #
        # Isinya bukan hiasan: kode tipe cuti yang dipakai HR di
        # dokumen, plus **berapa orang** — angka yang selama ini tidak
        # ada di mana pun. "5 pengajuan" dari satu orang dan dari lima
        # orang adalah dua keadaan yang sangat berbeda.
        columns=[
            dashboard.column("label", label="Leave Type"),
            dashboard.column("hint", label="Remarks"),
            dashboard.column("count", label="Count", format="number"),
            dashboard.column("days", label="Days", format="number"),
        ],
        empty_text="No leave recorded for this period.",
        link="/hr/leave",
        span=4,
        order=140,
    ),

    # Rincian baris dari Rekap Cuti di sebelahnya — bukan antrian
    # approval; itu kotak masuk workflow.
    #
    # Deskripsinya **wajib** menyebut periode. Keduanya kini menyaring
    # rentang yang sama, tapi yang membacanya tetap perlu tahu bahwa
    # daftar ini bukan "lima cuti terakhir sepanjang masa" — dan satu
    # kalimat di kepala kartu jauh lebih murah daripada pertanyaan yang
    # sama diulang tiap kali ada yang membandingkan kiri dan kanan.
    dashboard.listing(
        "recent_leaves",
        label="Recent Leave",
        description="Cuti terbaru yang dicatat pada periode terpilih.",
        columns=[
            dashboard.column("name", label="Employees"),
            dashboard.column("type", label="Type"),
            dashboard.column("date", label="Date", format="date"),
            dashboard.column("days", label="Days", format="number"),
        ],
        empty_text="No leave recorded yet.",
        link="/hr/leave",
        limit=5,
        span=4,
        order=150,
    ),

    dashboard.listing(
        "upcoming_trainings",
        label="Upcoming Training",
        columns=[
            dashboard.column("name", label="Program"),
            dashboard.column("date", label="Start", format="date"),
            dashboard.column(
                "participants",
                label="Participants",
                format="number",
            ),
        ],
        empty_text="No training programme scheduled.",
        link="/hr/training",
        limit=5,
        span=4,
        order=160,
    ),

    # Tanggal kepegawaian yang mendekat. Sengaja **tidak** ikut filter
    # periode: masa percobaan yang habis pekan depan tetap harus
    # terlihat walau layarnya sedang menampilkan angka bulan lalu.
    # Ambangnya diatur di HR → Masters → Reminder Policy.
    dashboard.listing(
        "employment_reminders",
        label="Employment Reminders",
        description=(
            "Masa percobaan, kontrak, dan ulang tahun yang mendekat. "
            "Ambang harinya diatur di Reminder Policy."
        ),
        columns=[
            dashboard.column("name", label="Employees"),
            dashboard.column("kind_label", label="Type"),
            dashboard.column("date", label="Date", format="date"),
            dashboard.column("days_left", label="Days Remaining", format="number"),
        ],
        empty_text="No upcoming dates.",
        link="/hr/employees",
        limit=8,
        span=8,
        order=170,
    ),
]


HR_DASHBOARD_SCHEMA = dashboard.schema(
    module="hr/dashboard",
    label="HR Dashboard",
    endpoint="/api/hr/dashboard/",
    description="Ringkasan data SDM pada periode berjalan.",
    filters=[
        dashboard.period_filter(
            mode="month",
            modes=["day", "week", "month", "year", "custom"],
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
        dashboard.lookup_filter(
            "branch",
            label="Branch",
            lookup_endpoint=(
                "/api/administration/organization/lookup/branches/"
            ),
            depends_on="company",
            lookup_params={"company_id": "$company"},
        ),
        # **Tanpa `depends_on`, dan itu disengaja.** Di form, Location
        # memang menunggu Company diisi. Di sini justru kebalikannya:
        # pertanyaan yang mau dijawab manajemen adalah "bagaimana
        # Jakarta HO", dan di tenant berisi dua belas perusahaan yang
        # sama-sama berkantor di sana, mengharuskan Company dipilih
        # lebih dulu membuat pertanyaan itu tidak bisa ditanyakan sama
        # sekali. `lookup_params` tetap dikirim, jadi begitu Company
        # atau Branch dipilih daftarnya ikut menyempit.
        # **Bercentang banyak.** Dropdown satu-pilihan memaksa memilih
        # antara satu lokasi atau seluruh tenant, dan tidak ada di
        # antaranya — sementara pertanyaan yang sebenarnya lazim
        # berbunyi "bagaimana Gebe dan Halmahera".
        #
        # `depends_on="company"` menyamakan perilakunya dengan Branch:
        # dropdown mati sampai induknya diisi, dan `lookup_params`
        # mengirim **seluruh** induk yang mungkin terisi — kalau cuma
        # induk terdekat, level yang dilompati membuat penyaringannya
        # gugur dan daftarnya menampilkan lokasi seluruh tenant.
        dashboard.lookup_filter(
            "location",
            label="Location",
            lookup_endpoint=(
                "/api/administration/organization/lookup/locations/"
            ),
            depends_on="company",
            lookup_params={
                "company_id": "$company",
                "branch_id": "$branch",
            },
            multiple=True,
            # Tombol pintas: sekali tekan, dashboard menyempit ke lokasi
            # penempatan penggunanya sendiri. Dropdown Location mati
            # sampai Company dipilih (mengikuti Branch), dan tombol ini
            # yang menutup celahnya — yang cuma mengurus satu lokasi
            # tidak perlu menebak perusahaan mana dulu.
            # **Bukan lagi `$me.placement.location` langsung.** Nilainya
            # sekarang dihitung backend (`MeSerializer.get_self_filter_values`)
            # supaya satu tombol bisa berarti "lokasi penempatan saya"
            # untuk hampir semua orang dan "seluruh lokasi dalam
            # cakupan saya" untuk direksi — tanpa dua tombol, dan tanpa
            # frontend perlu tahu siapa yang direksi.
            #
            # Isinya tetap lewat `DataScopeService`, jadi tombolnya
            # tidak bisa memilih lokasi yang tidak boleh dilihat
            # pemegangnya.
            self_filter="$me.data_scope.self_filter.location",
            self_filter_label="My Location",
        ),
    ],
    widgets=[
        *STAT_WIDGETS,
        *CHART_WIDGETS,
        *LIST_WIDGETS,
    ],
)
