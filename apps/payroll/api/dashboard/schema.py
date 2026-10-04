"""
Susunan Payroll Dashboard — pusat kendali **operasional** payroll.

Bukan layar konfigurasi. Tidak ada satu pun form di sini: kebijakan,
template tunjangan/potongan, kelompok lembur, dan pajak tetap diubah di
Payroll Configuration/Master. Yang dijawab layar ini cuma enam
pertanyaan yang ditanyakan orang payroll tiap bulan — di mana posisi
payroll bulan ini, berapa totalnya, sudah sampai tahap apa, siapa yang
bermasalah, ke mana harus menekan, dan bagaimana bentuknya dibanding
periode lalu.

Filternya **bukan** rentang tanggal
-----------------------------------
Seluruh dashboard lain di sistem ini disaring `period_filter()` — satu
rentang tanggal bebas. Payroll tidak bisa: yang menentukan angka bukan
"1–31 Agustus" melainkan `PayrollPeriod` dan `PayrollRun` yang memang
memuat perhitungannya. Dua run di rentang tanggal yang sama menghasilkan
dua angka yang berbeda dan keduanya benar. Karena itu tiga filternya
lookup ke dokumen aslinya, dan `get_period()` di view-nya dikosongkan —
lihat alasannya di sana.

Tidak ada `depends_on` pada Period dan Run
------------------------------------------
`depends_on` **mematikan** dropdown turunannya sampai induknya diisi
(lihat `MDashboardFilters.isDisabled`). Kalau dipasang, orang yang
cuma mau membuka run terakhir harus memilih company dulu, lalu period,
baru run — tiga klik untuk layar yang seharusnya sudah benar saat
dibuka. `lookup_params` tetap dikirim, jadi daftarnya tetap menyempit
begitu induknya dipilih; yang hilang cuma penguncian yang tidak
dibutuhkan di sini.

Yang **tidak** ada di sini, dan sengaja
---------------------------------------
Kartu **Employee BPJS** dan kolom BPJS di tabel. Hari ini BPJS cuma
baris `DeductionTemplateLine` yang kebetulan diberi kode "BPJS-*";
tidak ada `PayrollComponentSource` untuk itu, jadi satu-satunya cara
memisahkannya adalah mencocokkan nama komponen — persis yang dilarang.
Angka yang lahir dari tebakan nama lebih berbahaya daripada kartu yang
tidak ada, karena ia terbaca sebagai angka resmi. Begitu #5 memberi
BPJS sumber yang authoritative, kartunya tinggal ditambahkan di sini
dan satu kategori di `services.COMPOSITION`.

**Employer Contribution** dan **Total Payroll Cost** juga tidak ada,
dengan alasan yang sama: kontribusi pemberi kerja belum dihitung di
mana pun, dan kartu berisi nol akan terbaca sebagai "perusahaan tidak
menanggung apa-apa". Tempatnya sudah disiapkan — begitu angkanya ada,
`Total Payroll Cost = Gross + Employer Contribution`, bukan Net.
"""

from apps.framework.builders import dashboard


ORGANIZATION_LOOKUP = "/api/administration/organization/lookup/companies/"
PERIOD_LOOKUP = "/api/payroll/payroll-periods/lookup/"
RUN_LOOKUP = "/api/payroll/payroll-runs/lookup/"


FILTERS = [
    # Bercentang banyak, sebentuk dengan Company di HR Dashboard.
    #
    # Tidak ada yang dicentang = **seluruh company yang boleh dilihat
    # pemegang akun**, bukan seluruh tenant. Yang menegakkan itu
    # `DataScopeService` di tiap queryset resolver, bukan daftar ini;
    # isi dropdown-nya sendiri sudah tersaring di sisi lookup.
    dashboard.lookup_filter(
        "company",
        label="Company",
        lookup_endpoint=ORGANIZATION_LOOKUP,
        multiple=True,
    ),
    # Kuncinya `payroll_period`, bukan `period`, dan itu bukan gaya
    # penamaan. `BaseDashboardAPIView.get_context` menaruh rentang
    # tanggalnya sendiri di `context["period"]` lebih dulu, lalu
    # menimpanya dengan nilai filter bernama sama — filter ber-kunci
    # "period" akan menabrak kunci milik framework, dan yang rusak
    # bukan dashboard ini melainkan siapa pun yang kelak membaca
    # `context["period"]` menyangka isinya rentang tanggal.
    dashboard.lookup_filter(
        "payroll_period",
        label="Payroll Period",
        lookup_endpoint=PERIOD_LOOKUP,
        lookup_params={"company_id": "$company"},
    ),
    dashboard.lookup_filter(
        "payroll_run",
        label="Payroll Run",
        lookup_endpoint=RUN_LOOKUP,
        lookup_params={
            "company_id": "$company",
            "period_id": "$payroll_period",
        },
    ),
]


# Enam kartu, dan tidak satu pun membawa tren.
#
# Tren pada kartu KPI berarti membandingkan run terpilih dengan sesuatu,
# dan tidak ada pembanding yang jujur: satu periode bisa berisi run
# reguler, run off-cycle THR, dan run koreksi sekaligus, dan run
# berikutnya bisa memuat separuh pegawai yang berbeda. "Naik 34%" yang
# lahir dari run yang isinya bukan orang yang sama adalah angka yang
# terbaca seperti temuan padahal cuma perbedaan cakupan. Perbandingan
# antar periode dijawab chart Payroll Cost Trend, yang menyebutkan
# periodenya dengan nama.
STAT_WIDGETS = [
    dashboard.stat(
        "employees",
        label="Employees",
        icon="users",
        format="number",
        trend=False,
        span=2,
        order=10,
    ),
    dashboard.stat(
        "gross_payroll",
        label="Gross Payroll",
        icon="wallet",
        format="currency",
        trend=False,
        span=2,
        order=20,
    ),
    dashboard.stat(
        "total_deduction",
        label="Total Deductions",
        icon="minus-circle",
        format="currency",
        trend=False,
        span=2,
        order=30,
    ),
    dashboard.stat(
        "net_payroll",
        label="Net Payroll",
        icon="banknote",
        format="currency",
        trend=False,
        span=2,
        order=40,
    ),
    dashboard.stat(
        "overtime",
        label="Overtime",
        icon="timer",
        format="currency",
        trend=False,
        span=2,
        order=50,
    ),
    dashboard.stat(
        "absence_unpaid",
        label="Absent / Unpaid Leave",
        icon="calendar-x",
        format="currency",
        trend=False,
        span=2,
        order=60,
    ),
    dashboard.stat(
        "employer_contribution",
        label="Employer Cost",
        icon="building-2",
        format="currency",
        trend=False,
        span=3,
        order=70,
    ),
    dashboard.stat(
        "total_payroll_cost",
        label="Total Payroll Cost",
        icon="coins",
        format="currency",
        trend=False,
        span=3,
        order=80,
    ),
]


PROGRESS_WIDGET = dashboard.listing(
    "run_progress",
    label="Payroll Run Progress",
    description=(
        "Tahapan run terpilih, dibaca dari stempel waktu dokumennya "
        "sendiri."
    ),
    # Kolom kedua bertipe teks jadi keterangan di bawah judul baris —
    # aturan `MDashboardList`. Di sini isinya stempel waktu dan
    # pelakunya, dua hal yang selalu ditanyakan saat orang bertanya
    # "kenapa run ini belum jalan".
    columns=[
        dashboard.column("label", label="Stage"),
        dashboard.column("hint", label="Remarks"),
        dashboard.column("count", label="Employees", format="number"),
        dashboard.column("status", label="Status", format="status"),
    ],
    empty_text="No payroll run for this period.",
    span=4,
    order=110,
)


ATTENTION_WIDGET = dashboard.listing(
    "attention",
    label="Needs Follow-Up",
    description=(
        "Temuan validasi run terpilih, dikelompokkan per jenis. "
        "Error mengunci Finalize; peringatan boleh dilanjutkan setelah "
        "diakui."
    ),
    columns=[
        dashboard.column("label", label="Findings"),
        dashboard.column("hint", label="Remarks"),
        dashboard.column("count", label="Count", format="number"),
        dashboard.column("level", label="Level", format="status"),
    ],
    empty_text="No findings for this run.",
    limit=12,
    span=8,
    order=120,
)


RUN_TABLE_WIDGET = dashboard.table(
    "run_employees",
    label="Running Payroll Run",
    description=(
        "Hasil perhitungan per pegawai pada run terpilih. Dasar Upah "
        "adalah angka yang benar-benar terbentuk — untuk pegawai "
        "harian itu tarif x hari yang dibayar, bukan gaji sebulan."
    ),
    columns=[
        dashboard.column("employee", label="Employees", width=220),
        dashboard.column("employee_number", label="NIK"),
        dashboard.column("policy", label="Policy"),
        dashboard.column("pay_basis", label="Basis"),
        dashboard.column(
            "base_earning",
            label="Wage Basis",
            format="currency",
        ),
        # Tunjangan template **dan** input variabel dalam satu kolom,
        # dan namanya menyebut keduanya. Bukan karena keduanya sama
        # jenisnya, melainkan supaya identitasnya tetap utuh di setiap
        # baris: Dasar Upah + kolom ini + Lembur = Gross. Kolom yang
        # diam-diam menghilangkan input variabel membuat pembacanya
        # mencari selisih yang tidak ada sebabnya di layar.
        dashboard.column(
            "allowance",
            label="Allowances & Inputs",
            format="currency",
        ),
        dashboard.column("overtime", label="Overtime", format="currency"),
        dashboard.column("deduction", label="Deductions", format="currency"),
        dashboard.column("net_pay", label="Net Pay", format="currency"),
        dashboard.column("status", label="Status", format="status"),
    ],
    empty_text="No employees in this run.",
    sticky_columns=1,
    page_size=25,
    searchable=True,
    search_placeholder="Cari nama atau NIK…",
    span=12,
    order=130,
)


CHART_WIDGETS = [
    dashboard.line(
        "cost_trend",
        label="Payroll Cost Trend",
        description=(
            "Enam periode payroll terakhir dalam cakupan yang sama. "
            "Kontribusi pemberi kerja belum termasuk — belum dihitung "
            "di mana pun."
        ),
        x_label="Period",
        y_format="currency",
        horizontal=False,
        span=6,
        order=140,
    ),

    # Batang, **bukan** donat, dan ini bukan selera.
    #
    # Donat menyatakan bagian-dari-keseluruhan. Komposisi ini memuat
    # sisi penghasilan dan sisi potongan sekaligus, dan jumlah keduanya
    # bukan angka yang berarti apa pun — bukan gross, bukan net, bukan
    # biaya. Irisan "23% dari total" di situ adalah persentase dari
    # bilangan yang tidak punya nama.
    dashboard.bar(
        "composition",
        label="Payroll Composition",
        description=(
            "Dikelompokkan dari sumber komponen yang tercatat di tiap "
            "baris perhitungan, bukan dari pencocokan nama."
        ),
        y_format="currency",
        # Ringkasan "Total" di kanan judul dimatikan, dan itu bukan
        # kosmetik: jumlah kategori di kartu ini adalah penghasilan
        # ditambah potongan — bukan gross, bukan net, bukan biaya.
        # Angka itu tidak punya nama, dan tercetak besar di sebelah
        # judul ia terbaca sebagai angka utama kartunya.
        summary=False,
        span=6,
        order=150,
    ),
]


def _breakdown(key: str, *, label: str, dimension: str, order: int, span: int):
    return dashboard.table(
        key,
        label=label,
        columns=[
            # Kolom identitas terkunci saat digeser, jadi lebarnya
            # ditentukan di sini. Yang berbagi baris (span 6) mendapat
            # jatah lebih sempit — empat kolom rupiah di sebelahnya
            # yang harus muat lebih dulu.
            dashboard.column(
                dimension,
                label=label.replace("Per ", ""),
                width=200 if span >= 12 else 150,
            ),
            dashboard.column("employees", label="Employees", format="number"),
            dashboard.column("gross", label="Gross", format="currency"),
            dashboard.column("deduction", label="Deductions", format="currency"),
            dashboard.column("net", label="Net", format="currency"),
        ],
        empty_text="No data for this run.",
        total_label="Rows",
        sticky_columns=1,
        span=span,
        order=order,
    )


# Lebarnya 12 lalu 6 + 6, bukan tiga kali 4.
#
# Framework ini tidak punya widget bertab, jadi "By Policy | By
# Department | By Location" jadi tiga kartu. Bertiga sebaris masing-
# masing selebar 4 kolom, tiap kartu menampung lima kolom yang empat di
# antaranya rupiah — dan yang terlihat "Rp 1…" di tiap sel. Tabelnya
# memang bisa digulir mendatar, tapi rincian yang harus digulir untuk
# membaca kolom Net berhenti berguna sebagai rincian sekilas.
#
# Per Kebijakan mendapat baris penuh karena ia yang diminta pertama dan
# nama kebijakannya paling panjang; dua sumbu organisasi berbagi baris
# di bawahnya, dan 6 + 6 memang selalu berpasangan pas (lihat
# `spanClass`) — tidak ada setengah baris yang melompong.
BREAKDOWN_WIDGETS = [
    _breakdown(
        "by_policy",
        label="By Policy",
        dimension="policy",
        order=160,
        span=12,
    ),
    _breakdown(
        "by_department",
        label="By Department",
        dimension="department",
        order=170,
        span=6,
    ),
    _breakdown(
        "by_location",
        label="By Location",
        dimension="location",
        order=180,
        span=6,
    ),
]


PAYROLL_DASHBOARD_SCHEMA = dashboard.schema(
    module="payroll/dashboard",
    label="Payroll Dashboard",
    endpoint="/api/payroll/dashboard/",
    description=(
        "Posisi payroll periode berjalan: total, progress run, temuan "
        "yang perlu ditindaklanjuti, dan bentuk biayanya."
    ),
    filters=FILTERS,
    widgets=[
        *STAT_WIDGETS,
        PROGRESS_WIDGET,
        ATTENTION_WIDGET,
        RUN_TABLE_WIDGET,
        *CHART_WIDGETS,
        *BREAKDOWN_WIDGETS,
    ],
)
