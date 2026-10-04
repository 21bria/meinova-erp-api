from apps.framework.builders import action, field, tabs, ui

from .period import ROTATION_PERIOD_RESOURCE_FIELDS


# Empat nilai operasional. Jadwal roster tidak punya alur persetujuan —
# yang disetujui adalah Travel Request per kepulangan, bukan jadwal
# setahun. DRAFT/SUBMITTED/APPROVED/REJECTED tetap ada di model tapi
# tidak ditawarkan di sini.
SITE_ROTATION_STATUS_OPTIONS = [
    {"label": "Planned", "value": "planned"},
    {"label": "Active", "value": "active"},
    {"label": "Completed", "value": "completed"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        # Bukan "TR No." — itu nama dari masa modul ini masih merangkap
        # Travel Request. Sekarang pengajuan kepulangan punya modelnya
        # sendiri (`TravelRequest`, prefix TR); yang ini jadwal setahun,
        # prefix RST. Dua nomor berbeda di dua dokumen berbeda, dan
        # menyebut keduanya "TR No." adalah sumber pertanyaan "ini yang
        # mana".
        label="Roster No.",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        help_text=(
            "Terisi otomatis dari pola penomoran hr/site_rotation. "
            "Kosong berarti pola itu belum diseed — jalankan "
            "seed_administration --only=numbering."
        ),
        order=5,
    ),

    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        # Employee Group yang Roster-nya dimatikan tidak ditawarkan di
        # sini. Penolakannya tetap ada di
        # `SiteRotationService.assert_roster_applicable()` — dropdown
        # yang menyaring bukan penjagaan, cuma supaya yang salah tidak
        # sempat dipilih.
        lookup_params={"feature": "roster"},
        display_key="employee_name",
        autofill={
            "company": "company",
            "branch": "branch",
            "location": "location",
        },
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "roster_crew": field.lookup(
        tab="general",
        label="Roster Crew",
        lookup_endpoint=(
            "/api/administration/calendar/lookup/roster-crews/"
        ),
        display_key="roster_crew_name",
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
        },
        required=False,
        # Bukan kolom tabel: rencana yang lahir dari dokumen Roster
        # Setup tidak punya crew, jadi isinya "-" di hampir semua baris.
        table=False,
        filter=True,
        search=False,
        sortable=False,
        overview=True,
        help_text=(
            "Gelombang rotasi — jalur lama. Kosong itu wajar untuk "
            "jadwal yang terbit dari dokumen Roster Setup: polanya "
            "datang dari Roster Policy, bukan dari crew."
        ),
        order=20,
    ),

    "roster_policy": field.lookup(
        tab="general",
        label="Roster Policy",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/roster-policies/"
        ),
        display_key="roster_policy_name",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Aturan yang menerbitkan jadwal ini: pola siklus, hari "
            "perjalanan, dan konversi rotation credit."
        ),
        order=25,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=SITE_ROTATION_STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),
}


CYCLE_FIELDS = {
    "start_date": field.date(
        tab="cycle",
        label="Start Date",
        # Sengaja tidak wajib: dikosongkan berarti "ikut jangkar crew".
        # Dokumen tanpa crew tetap ditolak backend kalau tanggalnya
        # kosong, jadi tidak ada jalan lolos tanpa tanggal.
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Hari pertama blok kerja siklus pertama. Dikosongkan saat "
            "membuat dokumen = diambil dari jangkar siklus crew, "
            "digeser maju ke siklus terdekat."
        ),
        order=110,
    ),

    "cycle_work_days": field.integer(
        tab="cycle",
        label="Work Days",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Mis. 42 untuk pola 6 minggu kerja.",
        order=120,
    ),

    "cycle_off_days": field.integer(
        tab="cycle",
        label="Off Days",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Mis. 14 untuk pola 2 minggu off.",
        order=130,
    ),

    # Sejajar Work Days / Off Days, bukan di tab lain: ketiganya satu
    # pola yang dibaca bersamaan, dan memisahkannya membuat orang
    # mengubah salah satu tanpa melihat dua yang lain.
    "cycle_travel_days": field.integer(
        tab="cycle",
        label="Travel Days",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Total hari perjalanan pulang-pergi. 2 = sehari keluar, "
            "sehari kembali. Angka ganjil condong ke sisi keluar "
            "(3 = 2 keluar, 1 kembali). Di luar hitungan Work Days "
            "maupun Off Days — blok kerja 42 hari tetap 42 hari. "
            "0 = travel dianggap sudah termasuk blok kerja."
        ),
        order=125,
    ),

    "cycle_count": field.integer(
        tab="cycle",
        label="Cycle Count",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Berapa putaran ON+OFF yang dibuat. Tidak perlu ditebak: "
            "panjang satu siklus = Work + Off + 2 × Travel, dan "
            "kolom Cycle Length di sebelah sudah menghitungnya. "
            "Contoh 42/14/2 → 60 hari, jadi setahun butuh 7. "
            "Untuk memperpanjang nanti pakai Extend Schedule — bukan "
            "menaikkan angka ini, karena itu membangun ulang seluruh "
            "dokumen. Maksimal 24."
        ),
        order=140,
    ),

    # Menjawab "angka Cycle Count-nya dari mana". Tanpa ini pengguna
    # harus menghitung sendiri Work + Off + 2 × Travel di kepala, lalu
    # membaginya ke jumlah hari setahun — dan salah hitung menghasilkan
    # jadwal yang terlalu pendek tanpa ada yang sadar.
    "cycle_length": field.integer(
        tab="cycle",
        label="Cycle Length (days)",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        help_text=(
            "Work + Off + Travel. Setahun ≈ 365 ÷ angka ini."
        ),
        order=135,
    ),

    "cycles_per_year": field.integer(
        tab="cycle",
        label="Cycles per Year",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        help_text="Perkiraan siklus untuk menutupi 365 hari.",
        order=136,
    ),

    "end_date": field.date(
        tab="cycle",
        label="End Date",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        help_text="Terisi otomatis dari periode terakhir.",
        order=150,
    ),
}


ORGANIZATION_FIELDS = {
    "company": field.lookup(
        tab="organization",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        help_text="Terisi otomatis dari penempatan pegawai.",
        order=210,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        display_key="branch_name",
        lookup_params={"company_id": "$company"},
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=220,
    ),

    "location": field.lookup(
        tab="organization",
        label="Site / Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        overview=True,
        help_text="Lokasi kerja yang jadi tujuan travel in.",
        order=230,
    ),

    # Kepala Travel Request. Semuanya turunan dari relasi pegawai —
    # ditampilkan, tidak disimpan di dokumen, jadi tetap ikut betul kalau
    # data pegawainya dikoreksi. Karena bukan kolom model, `field.text`
    # dipakai apa adanya dan dikunci `disabled`.
    "department_name": field.text(
        tab="organization",
        label="Department",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=240,
    ),

    "section_name": field.text(
        tab="organization",
        label="Section",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=250,
    ),

    "position_name": field.text(
        tab="organization",
        label="Job Title",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=260,
    ),

    "work_email": field.text(
        tab="organization",
        label="Email Address",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        help_text="Email kantor; kosong = dipakai email pribadi.",
        order=270,
    ),

    "phone_number": field.text(
        tab="organization",
        label="Phone Number",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=280,
    ),

    "join_date": field.date(
        tab="organization",
        label="Date Of Hire",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=290,
    ),

    "point_of_hire_name": field.text(
        tab="organization",
        label="Point Of Hire",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        help_text=(
            "Kota rekrut pegawai — tujuan tiket pulang tiap blok off. "
            "Diubah dari master Employee, bukan dari sini."
        ),
        order=300,
    ),
}


NOTE_FIELDS = {
    "notes": field.textarea(
        tab="notes",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=310,
    ),
}


SITE_ROTATION_FIELDS = {
    **GENERAL_FIELDS,
    **CYCLE_FIELDS,
    **ORGANIZATION_FIELDS,
    **NOTE_FIELDS,
}


# Kolom hasil introspeksi model yang tidak dipakai di daftar.
#
# Setelah jalur baru masuk, `SiteRotation` bertambah delapan belas kolom
# (aturan travel, versi, jejak persetujuan, tanggal berlaku) dan
# introspeksi memberi semuanya `table=True` — daftarnya jadi 31 kolom
# dan Status harus dicari dengan menggulir ke samping. Semuanya tetap
# ada di dokumen; yang dimatikan cuma kolom tabelnya.
#
# `roster_crew` ikut dimatikan: rencana yang lahir dari dokumen Roster
# Setup tidak punya crew, jadi kolomnya "-" di hampir semua baris. Yang
# menjawab pertanyaan yang sama — pola ini dari mana — adalah Roster
# Policy di sebelahnya.
HIDDEN_ROTATION_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        # `roster_crew` sengaja TIDAK di sini — ia field form sungguhan,
        # dan dict ini di-spread paling akhir. Kolomnya dimatikan di
        # deklarasinya sendiri (`table=False`); menyebutnya di sini
        # berarti seluruh deklarasi lookup-nya tertimpa dan field-nya
        # hilang dari form.
        "cycle_start",
        "roster_start_basis",
        "travel_out_days",
        "travel_in_days",
        "travel_day_mode",
        "travel_creates_segment",
        "travel_out_counts_as_roster_day",
        "travel_in_counts_as_roster_day",
        "effective_from",
        "effective_to",
        "horizon_end",
        "current_version",
        "baseline_version",
        "submitted_at",
        "submitted_by",
        "approved_at",
        "approved_by",
        "locked_at",
        "setup_line",
    )
}


# Field turunan hasil serializer — muncul sebagai nilai tampilan pada
# kolom lookup-nya, jadi tidak boleh jadi kolom/filter tersendiri.
SITE_ROTATION_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "employee_name",
        "company_name",
        "branch_name",
        "location_name",
        "roster_crew_name",
        "roster_policy_name",
        "status_label",
        "period_count",
        "cycle_length",
        "cycles_per_year",
        # Daftar celah/tumpang tindih antar periode. Ditampilkan sebagai
        # peringatan di dokumen, bukan kolom tabel.
        "schedule_warnings",
        # Baris tanda tangan + keadaan alur. Dirender sebagai kartu di
        # kaki dokumen dan dicetak di formulir, bukan kolom tabel.
        "approval",
    )
}

# Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di kolom
# Employee. Daftar Roster Schedule memuat satu baris per pegawai per
# era, jadi nama kembar di satu site benar-benar tidak bisa dibedakan
# tanpa nomornya.
SITE_ROTATION_DISPLAY_FIELDS["employee_number"] = field.text(
    # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
    # kanan tabel — lihat `column_after` di columns.mjs.
    column_after="employee",
    label="Employee No.",
    read_only=True,
    table=True,
    search=True,
    sortable=True,
    order=5,
)


SITE_ROTATION_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="cycle",
        label="Cycle",
        fields=list(CYCLE_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="organization",
        label="Organization",
        fields=list(ORGANIZATION_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),
    tabs.form(
        key="notes",
        label="Notes",
        fields=list(NOTE_FIELDS.keys()),
        order=40,
        show_on_create=True,
    ),

    # Tabel dinamis baris ON/OFF. `requires_record=True` karena periode
    # menempel ke dokumen — barisnya baru bisa muncul setelah dokumennya
    # tersimpan (dan saat itu generator sudah mengisinya).
    # Dua tabel sejajar, mengikuti bentuk form Travel Request: "Travel
    # Purpose" (blok kerja/off) dan "Travel Arrangement" (mobilisasinya).
    # Travel sengaja tidak disarangkan ke dalam baris periode walau
    # relasinya memang ke periode — di formulir aslinya keduanya tabel
    # sebelah-menyebelah, dan orang yang mengisinya memang membaca
    # keduanya bersamaan.
    #
    # `inline=True`: barisnya disunting langsung di tabel. Ini jadwal —
    # menambah lima baris tanggal lewat lima dialog membuat baris-baris
    # yang justru harus dibandingkan tidak pernah terlihat bersamaan.
    tabs.resource(
        key="periods",
        # **Schedule**, bukan "Travel Purpose". Nama lama itu sisa dari
        # masa `SiteRotation` masih merangkap Travel Request — sama
        # asalnya dengan kolom "TR No." yang sudah lebih dulu dibetulkan
        # jadi "Roster No.". Isinya blok kerja, field break, dan hari
        # perjalanan; tab bernama Travel Purpose di layar yang justru
        # dipakai menyusun jadwal kerja membuat orang mencarinya di
        # tempat lain.
        label="Schedule",
        endpoint="/api/hr/rotation-periods/",
        module="hr/rotation-periods",
        foreign_key="rotation",
        fields=ROTATION_PERIOD_RESOURCE_FIELDS,
        inline=True,
        requires_record=True,
        order=50,
    ),

]


SITE_ROTATION_UI = {
    **ui.workspace(
        title="Roster Schedule",
        description=(
            "Jadwal roster setahun per pegawai: blok kerja, field "
            "break, jendela travel, dan shift normal tiap blok kerja "
            "(tombol Set Shift Pattern). Terbit dari dokumen Roster "
            "Setup; kepulangannya diajukan lewat Travel Request."
        ),
        size="full",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


SITE_ROTATION_ACTIONS = [
    action.save(),
    action.save_and_close(),
    action.delete(),
    action.export(),

    action.custom(
        "generate_periods",
        label="Generate Periods",
        icon="CalendarSync",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/generate-periods/",
        method="post",
        payload={"force": False},
        refresh=True,
        confirm={
            "title": "Generate ulang periode?",
            "description": (
                "Seluruh baris ON/OFF dokumen ini beserta baris "
                "travel-nya dibuat ulang dari pola siklus. Periode yang "
                "sudah disunting tangan atau punya travel yang diisi "
                "tangan akan menolak ditimpa — pakai Regenerate "
                "(Overwrite) kalau memang itu yang diinginkan."
            ),
        },
    ),

    # Menyambung jadwal tanpa membangun ulang. Ini yang dipakai saat
    # rosternya diperpanjang — bukan menaikkan Cycle Count, karena itu
    # menghapus setiap penyesuaian lapangan yang sudah dibuat.
    action.custom(
        "extend_periods",
        label="Extend Schedule",
        icon="CalendarPlus",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/extend-periods/",
        method="post",
        fields=[
            {
                "key": "cycles",
                "type": "integer",
                "label": "Add Cycles",
                "required": False,
                "help_text": (
                    "Berapa putaran ON+OFF disambung di ujung jadwal. "
                    "Kosongkan kalau memakai tanggal di bawah."
                ),
            },
            {
                "key": "until",
                "type": "date",
                "label": "Extend Until",
                "required": False,
                "help_text": (
                    "Alternatif: sambung sampai tanggal ini. Jumlah "
                    "siklusnya dihitung sendiri."
                ),
            },
        ],
        refresh=True,
    ),

    # Jalur **utama** rencana shift: dibaca dari urutan perputaran milik
    # Roster Policy, tanpa satu isian pun. Dipasang lebih dulu daripada
    # Set Shift Pattern karena inilah yang dipakai sehari-hari — yang di
    # bawahnya jalan keluar untuk satu pegawai yang polanya memang
    # berbeda dari crew-nya.
    #
    # Sebetulnya tombol ini **tidak wajib ditekan**: keempat mutasi
    # roster sudah memanggil sinkronisasi yang sama sendiri. Ia ada
    # untuk policy yang perputarannya baru dikonfigurasi sesudah
    # rosternya terbit, dan untuk memastikan — dua keadaan yang tidak
    # punya jawaban lain selain "buat ulang rencananya".
    action.custom(
        "sync_shift_baseline",
        label="Generate Shift Baseline",
        icon="CalendarSync",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/sync-shift-baseline/",
        method="post",
        refresh=True,
        confirm={
            "title": "Susun ulang rencana shift dari policy?",
            "description": (
                "Rencana shift disusun ulang mengikuti blok kerja "
                "dokumen ini dan urutan perputaran shift di Roster "
                "Policy. Penyesuaian (adjustment) tidak disentuh, dan "
                "tidak satu pun tanggal roster bergeser."
            ),
        },
    ),

    # Pola **satu kali** untuk satu pegawai, di luar konfigurasi
    # policy-nya. Dipakai saat seseorang memang menjalani pola yang
    # berbeda dari crew-nya.
    #
    # Batasnya harus disebutkan, dan disebutkan di layar: hasilnya
    # **bertahan sampai rosternya berubah**. Mutasi roster berikutnya
    # menyusun ulang rencana dari urutan perputaran policy, karena
    # itulah satu-satunya tempat pola yang tersimpan. Pola yang harus
    # bertahan ditulis di Roster Policy, bukan di sini.
    action.custom(
        "apply_shift_pattern",
        label="Set Shift Pattern (Manual)",
        icon="Clock",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/apply-shift-pattern/",
        method="post",
        refresh=True,
        fields=[
            {
                "key": "shifts",
                "type": "multilookup",
                "label": "Shift Rotation",
                "required": True,
                "endpoint": (
                    "/api/administration/references/hr/lookup/shifts/"
                ),
                "label_key": "label",
                "value_key": "value",
                "placeholder": "Pilih shift…",
                "help_text": (
                    "Urutan pilihan = urutan perputaran. Satu shift "
                    "saja berarti blok kerjanya memakai shift itu "
                    "terus. Jamnya tetap milik master Shift."
                ),
            },
            {
                "key": "rotation_days",
                "type": "integer",
                "label": "Change Shift Every (days)",
                "required": False,
                "default": 7,
                "help_text": (
                    "7 = berganti tiap minggu. Dihitung dari awal "
                    "blok kerja, jadi hasilnya sama berapa kali pun "
                    "tombol ini ditekan."
                ),
            },
            {
                "key": "start",
                "type": "date",
                "label": "From",
                "required": False,
                "help_text": (
                    "Kosong = seluruh rentang jadwal dokumen ini."
                ),
            },
            {
                "key": "until",
                "type": "date",
                "label": "Until",
                "required": False,
                "help_text": (
                    "Kosong = sampai akhir horizon jadwal."
                ),
            },
        ],
        confirm={
            "title": "Susun rencana shift manual?",
            "description": (
                "Rencana shift lama pada rentang ini digantikan pola "
                "yang dipilih. Penyesuaian (adjustment) tidak disentuh, "
                "dan tidak satu pun tanggal roster bergeser. "
                "Perhatikan: pola ini bertahan sampai rosternya berubah "
                "— sesudah itu rencana disusun ulang dari urutan "
                "perputaran di Roster Policy."
            ),
        },
    ),

    # Ganti pola mulai satu titik. Baris sebelumnya adalah sejarah —
    # sudah dijalani dan sudah dibelikan tiket.
    action.custom(
        "regenerate_from",
        label="Rebuild From Period",
        icon="CalendarCog",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/regenerate-from/",
        method="post",
        fields=[
            {
                "key": "from_sequence",
                "type": "integer",
                "label": "From Period #",
                "required": True,
                "help_text": (
                    "Blok pertama yang dibuat ulang dengan pola yang "
                    "berlaku sekarang. Blok sebelumnya tidak disentuh."
                ),
            },
            {
                "key": "cycles",
                "type": "integer",
                "label": "Cycles",
                "required": False,
                "help_text": "Kosongkan = sebanyak yang digantikan.",
            },
        ],
        refresh=True,
        confirm={
            "title": "Bangun ulang dari periode ini?",
            "description": (
                "Blok dari nomor yang disebut ke bawah dibuat ulang "
                "dengan pola sekarang. Blok sebelumnya, termasuk yang "
                "sudah disesuaikan, tidak disentuh."
            ),
        },
    ),

    # Penyesuaian lapangan: kapal ditunda, pesawat dimajukan. Bukan
    # generate ulang — polanya tidak berubah, cuma seluruh sisa
    # jadwalnya bergeser sekian hari.
    action.custom(
        "shift_periods",
        label="Shift Schedule",
        icon="CalendarArrowDown",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/shift-periods/",
        method="post",
        # Dua-duanya diketik pengguna, jadi tidak ada `payload` tetap.
        # Kunci `fields` ini belum dibaca generator FE mana pun —
        # ditulis sekarang supaya kontraknya sudah ada di satu tempat
        # saat renderer action-nya dibuat, bukan ditebak ulang nanti.
        fields=[
            {
                "key": "from_sequence",
                "type": "integer",
                "label": "Dari Periode #",
                "required": True,
                "help_text": (
                    "Nomor urut periode pertama yang bergeser. "
                    "Periode sebelumnya tidak disentuh."
                ),
            },
            {
                "key": "days",
                "type": "integer",
                "label": "Geser (hari)",
                "required": True,
                "help_text": (
                    "Positif memundurkan, negatif memajukan. "
                    "Mis. -2 untuk kapal yang berangkat dua hari "
                    "lebih cepat."
                ),
            },
        ],
        refresh=True,
        confirm={
            "title": "Geser sisa jadwal?",
            "description": (
                "Periode yang dipilih dan seluruh periode sesudahnya "
                "bergeser, termasuk tanggal travel dan akomodasinya. "
                "Semuanya ditandai disunting tangan, jadi tidak akan "
                "ditimpa Generate Periods."
            ),
        },
    ),

    # Jalur `force`. Dibuat sebagai tombol tersendiri, bukan centang di
    # dalam dialog: tombol pertama sengaja tidak bisa menghapus tiket
    # yang sudah dipesan, dan satu-satunya cara melewatinya harus
    # berupa tindakan yang dipilih sadar, dengan namanya sendiri.
    action.custom(
        "regenerate_periods_force",
        label="Regenerate (Overwrite)",
        icon="TriangleAlert",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/site-rotations/{id}/generate-periods/",
        method="post",
        payload={"force": True},
        refresh=True,
        confirm={
            "title": "Timpa seluruh jadwal?",
            "description": (
                "Termasuk periode yang sudah disunting tangan dan baris "
                "travel yang sudah berisi nomor tiket atau bookingan "
                "hotel. Semuanya dibuat ulang dari pola siklus dan "
                "isian manualnya hilang."
            ),
        },
    ),
]


SITE_ROTATION_SCHEMA = {
    "module": "hr/site-rotations",
    "name": "SiteRotation",
    "label": "Roster Schedule",
    "endpoint": "/api/hr/site-rotations/",
    "schema_type": "crud",

    "ui": SITE_ROTATION_UI,
    "tabs": SITE_ROTATION_TABS,
    "actions": SITE_ROTATION_ACTIONS,
    "fields": {
        **SITE_ROTATION_FIELDS,
        **SITE_ROTATION_DISPLAY_FIELDS,
        **HIDDEN_ROTATION_COLUMNS,
    },
}
