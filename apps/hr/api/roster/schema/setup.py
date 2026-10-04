"""
Schema layar setup roster massal.

Bentuknya workspace bertab dengan **tabel inline** untuk barisnya —
alasannya sama dengan tabel Travel Purpose di dokumen rotasi: ini
jadwal, dan menambah tiga puluh baris lewat tiga puluh modal membuat
baris yang justru harus dibandingkan tidak pernah terlihat bersamaan.

Current Cycle Start berbeda-beda di dalam satu batch, dan itu keadaan
normal di site yang gelombangnya bergantian. Karena itu ia kolom di
grid, bukan satu isian di kepala dokumen.
"""

from apps.framework.builders import action, field, tabs, ui


ROSTER_SETUP_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Pending Approval", "value": "submitted"},
    {"label": "Approved", "value": "approved"},
    {"label": "Committed", "value": "committed"},
    {"label": "Partially Committed", "value": "partial"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
]


# ----------------------------------------------------------------------
# Dokumen
# ----------------------------------------------------------------------


ROSTER_SETUP_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Document No.",
        required=False,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        modes=["edit"],
        help_text=(
            "Terisi otomatis dari pola penomoran hr/roster_setup. "
            "Kosong berarti polanya belum diseed — jalankan "
            "seed_administration --only=numbering."
        ),
        order=5,
    ),

    # Ditanyakan lebih dulu, dan itu bukan sekadar kenyamanan: master
    # lokasi lazim memuat beberapa baris "Default Location" bawaan seed
    # dari company yang berbeda-beda. Tanpa Company di kepala form,
    # dropdown Site menampilkan seluruh tenant dan yang mengisi tidak
    # punya cara membedakan mana yang miliknya.
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        display_key="company_name",
        required=True,
        table=False,
        filter=True,
        overview=True,
        # Terisi dari penempatan pembuatnya, dan terkunci kalau
        # cakupannya memang cuma satu company. Admin site tidak perlu
        # mencari perusahaannya sendiri di daftar dua belas baris, dan
        # tidak boleh salah memilih yang lain: dokumennya akan
        # tersimpan lalu seketika hilang dari layarnya sendiri.
        default="$me.placement.company",
        readonly_when={
            "field": "$me.data_scope.values.company",
            "op": "is_not_null",
        },
        help_text=(
            "Menyaring Site dan Section di bawahnya. Satu-satunya "
            "level organisasi yang wajib."
        ),
        order=8,
    ),

    "location": field.lookup(
        tab="general",
        label="Site",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        display_key="location_name",
        lookup_params={"company_id": "$company"},
        depends_on="company",
        # **Tanpa `autofill`.** `LocationLookup` tidak punya `serialize()`
        # sendiri, jadi barisnya cuma `{value, label}` — `autofill=
        # {"company": "company"}` membaca kunci yang tidak ada dan
        # menuliskan `undefined` ke field Company yang barusan dipilih.
        # Akibatnya: pilih Company → pilih Site → Company kosong lagi dan
        # Section ikut mati karena `depends_on`-nya. Arahnya memang satu
        # jalan (Company menyaring Site, tidak sebaliknya), jadi autofill
        # di sini tidak menambah apa pun selain kerusakan itu.
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        default="$me.placement.location",
        # Dikunci **hanya** kalau cakupannya memang menunjuk satu site.
        # Admin bercakupan company tetap boleh memilih site mana pun di
        # dalam company-nya — itu memang tanggung jawabnya.
        readonly_when={
            "field": "$me.data_scope.values.location",
            "op": "is_not_null",
        },
        help_text=(
            "Satu dokumen = satu site. Batch yang mencampur site "
            "membuat meja persetujuannya tidak bisa ditentukan."
        ),
        order=10,
    ),

    "department": field.lookup(
        tab="general",
        label="Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        display_key="department_name",
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
        },
        depends_on=["company", "location"],
        required=False,
        table=True,
        filter=True,
        overview=True,
        default="$me.placement.department",
        help_text=(
            "Penyaring opsional di bawah Site. Kosong = seluruh site."
        ),
        order=12,
    ),

    "section": field.lookup(
        tab="general",
        label="Section",
        lookup_endpoint=(
            "/api/administration/organization/lookup/sections/"
        ),
        display_key="section_name",
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
            "department_id": "$department",
        },
        # Induknya disebut semua, bukan cuma Company. Aturan umumnya
        # memang `depends_on="company"` karena level perantara boleh
        # dilompati — tapi di dokumen ini Site **wajib**, dan tanpa
        # menyebutnya Section tidak ikut dikosongkan saat Site atau
        # Department diganti: yang sudah terpilih tetap menempel walau
        # sudah bukan milik keduanya, dan penolakannya baru muncul saat
        # Simpan.
        #
        # `department` **tidak** ikut di sini: ia opsional, dan
        # menyebutnya berarti Section mati selama Department kosong —
        # padahal di banyak tenant Section menempel langsung ke
        # Location dan Department memang tidak dipakai.
        depends_on=["company", "location"],
        required=False,
        table=True,
        filter=True,
        overview=True,
        # Terisi, tapi **tidak** dikunci. Admin section lazim menyusun
        # roster untuk section tetangga di site yang sama, dan
        # mengosongkannya berarti seluruh site — dua hal yang harus
        # tetap bisa dipilih.
        default="$me.placement.section",
        help_text=(
            "Penyaring opsional, dan yang disaringnya adalah daftar "
            "kandidat di tombol Add Employees — bukan pengisi baris "
            "otomatis. Kosong = seluruh department."
        ),
        order=15,
    ),

    "as_of_date": field.date(
        tab="general",
        label="As Of Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Keadaan direkam per tanggal ini. Jadwal berangkat dari "
            "blok yang sedang dijalani pegawai, bukan dari awal "
            "riwayatnya."
        ),
        order=20,
    ),

    "horizon_months": field.integer(
        tab="general",
        label="Horizon (Months)",
        required=False,
        table=True,
        sortable=True,
        min=1,
        max=24,
        # Sama dengan default model. Ditulis di sini juga karena kotak
        # kosong berlabel "Horizon (Months)" terbaca sebagai wajib diisi
        # — dan orang yang menebak akan mengetik angka yang lebih besar
        # daripada yang dia butuhkan.
        default=12,
        help_text=(
            "Jadwal digenerate sampai sekian bulan ke depan. Dibatasi "
            "24 bulan; perpanjangannya nanti otomatis lewat rolling "
            "horizon."
        ),
        order=25,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        options=ROSTER_SETUP_STATUS_OPTIONS,
        display_key="status_label",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        disabled=True,
        modes=["edit"],
        order=30,
    ),

    "notes": field.textarea(
        tab="general",
        label="Notes",
        required=False,
        rows=3,
        order=40,
    ),

    "commit_error": field.textarea(
        tab="general",
        label="Commit Error",
        required=False,
        rows=3,
        read_only=True,
        display=True,
        modes=["edit"],
        # Kegagalan ditempel ke dokumennya sendiri, bukan cuma ke log
        # server: yang bisa memperbaikinya adalah orang yang membuka
        # layar ini.
        visible_when={"status": ["partial"]},
        help_text=(
            "Baris yang gagal diterbitkan. Perbaiki datanya lalu tekan "
            "Commit lagi — baris yang sudah berhasil tidak diulang."
        ),
        order=45,
    ),
}


# Dua penghitung, bukan isian — dan itu tidak terbaca dari layar create,
# tempat keduanya muncul sebagai kotak kosong berlabel "Employees" dan
# "Committed" di sebelah field yang memang harus diisi. `modes=["edit"]`
# menahannya sampai dokumennya ada: sebelum itu jawabannya selalu nol,
# dan nol yang bisa diketik ulang lebih buruk daripada tidak ditampilkan.
ROSTER_SETUP_DISPLAY_FIELDS = {
    "line_count": field.integer(
        tab="general",
        label="Employees",
        read_only=True,
        display=True,
        modes=["edit"],
        table=True,
        sortable=False,
        overview=True,
        # Sesudah Status, bukan di tengah field yang harus diisi:
        # penghitung yang duduk di antara As Of Date dan Horizon
        # terbaca sebagai bagian dari isian.
        order=32,
    ),

    "committed_count": field.integer(
        tab="general",
        label="Committed",
        read_only=True,
        display=True,
        modes=["edit"],
        table=True,
        sortable=False,
        order=33,
    ),
}


# ----------------------------------------------------------------------
# Baris
# ----------------------------------------------------------------------


ROSTER_SETUP_LINE_FIELDS = {
    "employee": field.lookup(
        label="Employee",
        # Lookup pegawai biasa, bukan endpoint kandidat: `{id}` dokumen
        # tidak bisa dirakit dari dalam baris grid. Pegawai yang sudah
        # punya jadwal berjalan tetap ditolak — oleh `RosterValidator`,
        # dengan pesan yang menyebut nomor dokumen yang menabrak. Untuk
        # menambah banyak orang sekaligus, tombol Add Employees memakai
        # `POST .../add-employees/` yang memang menyaring kandidat.
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        autofill={
            "roster_policy": "roster_policy",
            "current_cycle_start": "roster_cycle_start",
        },
        required=True,
        table=True,
        search=True,
        order=10,
    ),

    "roster_policy": field.lookup(
        label="Roster Policy",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/roster-policies/"
        ),
        display_key="roster_policy_code",
        required=True,
        table=True,
        filter=True,
        help_text=(
            "Yang menentukan pola siklusnya. Policy tanpa pola siklus "
            "tidak muncul di sini — ia cuma memuat aturan site."
        ),
        order=20,
    ),

    "current_cycle_start": field.date(
        label="Current Cycle Start",
        required=True,
        table=True,
        sortable=True,
        help_text=(
            "Hari pertama blok yang **sedang** dijalani pegawai ini. "
            "Boleh tanggal lampau — justru itu yang biasa saat sistem "
            "baru dipasang."
        ),
        order=30,
    ),

    "opening_rotation_credit": field.decimal(
        label="Opening Credit",
        required=False,
        table=True,
        decimal_places=2,
        max_digits=6,
        help_text=(
            "Saldo rotation credit yang dibawa dari sistem lama. "
            "Dicatat sebagai transaksi Opening Balance, bukan diketik "
            "langsung ke saldo."
        ),
        order=40,
    ),

    "note": field.text(
        label="Note",
        required=False,
        table=True,
        order=50,
    ),

    "status": field.select(
        label="Status",
        options=[
            {"label": "Pending", "value": "pending"},
            {"label": "Committed", "value": "committed"},
            {"label": "Failed", "value": "failed"},
            {"label": "Skipped", "value": "skipped"},
        ],
        display_key="status_label",
        required=False,
        table=True,
        filter=True,
        disabled=True,
        modes=["edit"],
        order=60,
    ),

    "commit_error": field.text(
        label="Error",
        required=False,
        table=True,
        read_only=True,
        display=True,
        order=70,
    ),
}


ROSTER_SETUP_LINE_DISPLAY_FIELDS = {
    "employee_number": field.text(
        # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
        # kanan tabel — lihat `column_after` di columns.mjs.
        column_after="employee",
        label="Employee No.",
        read_only=True,
        display=True,
        table=True,
        search=True,
        order=5,
    ),
}


# ----------------------------------------------------------------------
# Tab & aksi
# ----------------------------------------------------------------------


ROSTER_SETUP_TABS = [
    tabs.form(
        "general",
        label="Document",
        fields=[
            "document_number",
            "company",
            "location",
            "department",
            "section",
            "as_of_date",
            "horizon_months",
            "status",
            "line_count",
            "committed_count",
            "notes",
            "commit_error",
        ],
    ),

    tabs.resource(
        "lines",
        label="Employees",
        endpoint="/api/hr/roster-setup-lines/",
        module="hr/roster-setup-lines",
        foreign_key="request",
        fields=ROSTER_SETUP_LINE_FIELDS,
        # Disunting langsung di tabel: tiga puluh baris lewat tiga puluh
        # dialog membuat Current Cycle Start yang justru harus
        # dibandingkan tidak pernah terlihat bersamaan.
        inline=True,
    ),
]


ROSTER_SETUP_ACTIONS = [
    # Inti fitur bulk, dan sempat tidak punya tombol sama sekali:
    # endpointnya jalan, tapi satu-satunya jalan menambah pegawai adalah
    # mengetik baris satu per satu di grid — persis pekerjaan yang mau
    # dihindari. Daftarnya dari `candidates/`, yang sudah membuang
    # pegawai yang punya jadwal berjalan dan yang sudah berhenti, serta
    # menandai yang sudah ada di dokumen ini lewat `already_added`.
    action.custom(
        "add_employees",
        label="Add Employees",
        icon="UserPlus",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/roster-setups/{id}/add-employees/",
        method="post",
        refresh=True,
        visible_when={"status": ["draft", "rejected"]},
        fields=[
            {
                "key": "employee_ids",
                "type": "multilookup",
                "label": "Employees",
                "required": True,
                "endpoint": "/api/hr/roster-setups/{id}/candidates/",
                "label_key": "label",
                "value_key": "value",
                "disabled_key": "already_added",
                "placeholder": "Pilih pegawai…",
                "help_text": (
                    "Roster Policy dan Current Cycle Start diambil dari "
                    "penempatan masing-masing, dan bisa dikoreksi per "
                    "baris sesudahnya — justru di situ perbedaannya: "
                    "satu batch, banyak jangkar."
                ),
            },
        ],
    ),

    action.custom(
        "preview",
        label="Preview Schedule",
        icon="CalendarSearch",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/roster-setups/{id}/preview/",
        method="get",
        refresh=False,
        # Preview wajib bisa dibuka kapan saja, termasuk setelah
        # disetujui — yang ditinjau approver dan yang dilihat pembuatnya
        # harus jadwal yang sama.
    ),

    action.submit(
        endpoint="/api/hr/roster-setups/{id}/submit/",
        visible_when={"status": ["draft", "rejected"]},
        confirm={
            "title": "Ajukan setup roster?",
            "description": (
                "Seluruh baris diajukan sebagai satu dokumen. Setelah "
                "disetujui, jadwalnya langsung diterbitkan dan dikunci "
                "sebagai baseline."
            ),
        },
    ),

    action.withdraw(
        endpoint="/api/hr/roster-setups/{id}/withdraw/",
        visible_when={"status": ["submitted"]},
    ),

    action.custom(
        "commit",
        label="Retry Commit",
        icon="RefreshCw",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/roster-setups/{id}/commit/",
        method="post",
        refresh=True,
        # Hanya muncul saat ada yang gagal. Commit ulang melewati baris
        # yang sudah berhasil, jadi aman ditekan berkali-kali.
        visible_when={"status": ["approved", "partial"]},
        confirm={
            "title": "Terbitkan ulang baris yang gagal?",
            "description": (
                "Baris yang sudah berhasil tidak diulang."
            ),
        },
    ),
]


# Kolom hasil introspeksi model yang tidak dipakai di tabel.
#
# Yang paling menyesatkan `company`/`location`/`section`: introspeksi
# memberinya `table=True` dan generator memetakannya ke `<field>_name`,
# sementara serializer mengirim `company_name`/`location_name` — kolomnya
# ada, isinya "-" di semua baris. Kolom yang memang ditampilkan
# dideklarasikan eksplisit di atas dengan `display_key` yang benar.
HIDDEN_SETUP_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "is_active",
        # `company` sengaja TIDAK di sini: ia field form sungguhan yang
        # dideklarasikan di atas, dan dict ini di-spread paling akhir —
        # menyebutnya berarti seluruh deklarasinya tertimpa jadi kolom
        # mati, dan field Company-nya hilang lagi dari layar.
        "submitted_at",
        "submitted_by",
        "committed_at",
        "workflow",
        "status_label",
        "company_name",
        "location_name",
        "department_name",
        "section_name",
    )
}


HIDDEN_SETUP_LINE_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "is_active",
        "request",
        "status_label",
        "employee_name",
        "roster_policy_code",
    )
}


ROSTER_SETUP_SCHEMA = {
    "module": "hr/roster-setups",
    "name": "RosterSetupRequest",
    "label": "Roster Setup",
    "endpoint": "/api/hr/roster-setups/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Roster Setup",
            description=(
                "Menetapkan jadwal roster awal per site: pilih pegawai, "
                "policy, dan blok yang sedang dijalani masing-masing."
            ),
            size="full",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },
    "tabs": ROSTER_SETUP_TABS,
    "actions": ROSTER_SETUP_ACTIONS,
    "fields": {
        **ROSTER_SETUP_FIELDS,
        **ROSTER_SETUP_DISPLAY_FIELDS,
        **HIDDEN_SETUP_COLUMNS,
    },
}


ROSTER_SETUP_LINE_SCHEMA = {
    "module": "hr/roster-setup-lines",
    "name": "RosterSetupLine",
    "label": "Roster Setup Line",
    "endpoint": "/api/hr/roster-setup-lines/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Roster Setup Line",
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=False,
        ),
    },
    "fields": {
        **ROSTER_SETUP_LINE_FIELDS,
        **ROSTER_SETUP_LINE_DISPLAY_FIELDS,
        **HIDDEN_SETUP_LINE_COLUMNS,
    },
}
