"""
Event notifikasi bawaan.

Didaftarkan dari `NotificationsConfig.ready()`. Modul lain boleh
mendaftarkan event-nya sendiri dari `AppConfig.ready()` masing-masing —
yang di sini cuma yang sudah ada pemicunya hari ini.

**Bahasa isi surat: Indonesia.** Pembacanya pengguna akhir, sama seperti
artikel Help Center. Nama tombol dan nama layar tetap ditulis persis
seperti di aplikasi (Inggris) — panduan yang menyebut "tombol Simpan"
untuk tombol berbunyi "Save" membuat pembacanya mencari tombol yang
tidak ada.

Kalimat di sini cuma **titik awal**. Begitu tenant menyimpan satu baris
`EmailTemplate`, baris itu yang dipakai. Yang tidak pernah menyimpan
apa pun tetap menerima surat yang masuk akal, bukan surat kosong.
"""

from __future__ import annotations

from .constants import Channel, RecipientType
from .registry import NotificationEvent, Placeholder, register_event

# ----------------------------------------------------------------------
# Kepegawaian: tanggal yang jatuh tempo
# ----------------------------------------------------------------------

_EMPLOYEE_PLACEHOLDERS = (
    Placeholder("employee_name", "Nama pegawai", "Budi Santoso"),
    Placeholder("employee_number", "Nomor pegawai", "SGA001"),
    Placeholder("position_name", "Jabatan", "Operator Alat Berat"),
    Placeholder("department_name", "Department", "Operations"),
    Placeholder("location_name", "Lokasi kerja", "Gebe Mine"),
)


CONTRACT_END = register_event(
    NotificationEvent(
        code="hr.contract_end",
        label="Contract Ending Soon",
        module="hr",
        category="Kepegawaian",
        description=(
            "Dikirim saat kontrak kerja memasuki ambang pengingat yang "
            "diatur di Employee Reminder Policy. Kalau lewat tanpa "
            "keputusan, pegawainya bekerja tanpa dasar kontrak."
        ),
        placeholders=_EMPLOYEE_PLACEHOLDERS
        + (
            Placeholder("end_date", "Tanggal berakhir", "30 September 2026"),
            Placeholder("days_left", "Sisa hari", "30"),
            Placeholder("contract_type", "Jenis kontrak", "PKWT"),
        ),
        default_recipients=(RecipientType.ROLE, RecipientType.SUBJECT),
        default_roles=("HR-ADMIN", "HR-MANAGER"),
        default_subject=(
            "Kontrak {{ employee_name }} berakhir {{ end_date }}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Kontrak kerja atas nama {{ employee_name }} "
            "({{ employee_number }}) akan berakhir pada "
            "{{ end_date }} — {{ days_left }} hari lagi.\n\n"
            "Jabatan: {{ position_name }}\n"
            "Department: {{ department_name }}\n"
            "Lokasi: {{ location_name }}\n\n"
            "Mohon diproses perpanjangan atau keputusan lainnya sebelum "
            "tanggal tersebut."
        ),
    ),
)


PROBATION_END = register_event(
    NotificationEvent(
        code="hr.probation_end",
        label="Probation Ending Soon",
        module="hr",
        category="Kepegawaian",
        description=(
            "Dikirim saat masa percobaan mendekati akhir. Kalau lewat "
            "tanpa keputusan, pegawainya otomatis menjadi karyawan tetap."
        ),
        placeholders=_EMPLOYEE_PLACEHOLDERS
        + (
            Placeholder("end_date", "Tanggal berakhir", "31 Agustus 2026"),
            Placeholder("days_left", "Sisa hari", "14"),
        ),
        default_recipients=(RecipientType.ROLE, RecipientType.SUBJECT),
        default_roles=("HR-ADMIN", "HR-MANAGER"),
        default_subject=(
            "Masa percobaan {{ employee_name }} berakhir {{ end_date }}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Masa percobaan atas nama {{ employee_name }} "
            "({{ employee_number }}) akan berakhir pada "
            "{{ end_date }} — {{ days_left }} hari lagi.\n\n"
            "Mohon dilakukan evaluasi dan keputusan pengangkatan sebelum "
            "tanggal tersebut."
        ),
    ),
)


# Ulang tahun dan hari jadi kerja: **bel saja, tanpa email**.
#
# Keduanya pengingat untuk HR supaya ada yang mengucapkan — bukan surat
# dinas. Mengirimkannya sebagai email ke kotak masuk yang sama dengan
# pemberitahuan kontrak membuat kotak itu berisi hal yang tidak perlu
# ditindaklanjuti, dan sesudah itu yang perlu ikut tidak dibaca. Tenant
# yang memang menginginkannya tinggal menyalakan Email di layar
# Notification Rules.
BIRTHDAY = register_event(
    NotificationEvent(
        code="hr.birthday",
        label="Employee Birthday",
        module="hr",
        category="Kepegawaian",
        description=(
            "Pengingat ulang tahun. Bawaannya bel saja — ini pengingat "
            "untuk HR, bukan pemberitahuan kepada orang yang sudah tahu "
            "kapan ia lahir."
        ),
        placeholders=_EMPLOYEE_PLACEHOLDERS
        + (
            Placeholder("event_date", "Tanggal", "20 Agustus 2026"),
            Placeholder("days_left", "Sisa hari", "5"),
        ),
        default_recipients=(RecipientType.ROLE,),
        default_roles=("HR-ADMIN",),
        default_channels=(Channel.IN_APP,),
        default_subject="Ulang tahun {{ employee_name }} {{ event_date }}",
        default_body=(
            "{{ employee_name }} ({{ employee_number }}) berulang tahun "
            "pada {{ event_date }}."
        ),
    ),
)


WORK_ANNIVERSARY = register_event(
    NotificationEvent(
        code="hr.work_anniversary",
        label="Work Anniversary",
        module="hr",
        category="Kepegawaian",
        description="Pengingat hari jadi kerja. Bawaannya bel saja.",
        placeholders=_EMPLOYEE_PLACEHOLDERS
        + (
            Placeholder("event_date", "Tanggal", "1 September 2026"),
            Placeholder("days_left", "Sisa hari", "7"),
            Placeholder("years", "Lama bekerja (tahun)", "5"),
        ),
        default_recipients=(RecipientType.ROLE,),
        default_roles=("HR-ADMIN",),
        default_channels=(Channel.IN_APP,),
        default_subject="Hari jadi kerja {{ employee_name }}",
        default_body=(
            "{{ employee_name }} ({{ employee_number }}) genap "
            "{{ years }} tahun bekerja pada {{ event_date }}."
        ),
    ),
)


# ----------------------------------------------------------------------
# Workflow / persetujuan
# ----------------------------------------------------------------------
#
# Ini yang menutup lubang terbesar: sebelum ini engine approval tidak
# pernah memberi tahu siapa pun. Approver tidak tahu ada dokumen di
# mejanya sampai ia kebetulan membuka kotak masuk, dan pengaju tidak
# tahu dokumennya sudah diputuskan.
#
# Empat event, bukan satu ber-parameter status: judul dan nada suratnya
# memang berbeda, dan tenant harus bisa mematikan pemberitahuan
# "disetujui" tanpa ikut mematikan "ditolak".

_DOCUMENT_PLACEHOLDERS = (
    Placeholder("document_label", "Judul dokumen", "Cuti Tahunan 5 hari"),
    Placeholder("document_number", "Nomor dokumen", "LV260014"),
    Placeholder("document_type", "Jenis dokumen", "Leave Request"),
    Placeholder("employee_name", "Pegawai yang dibicarakan", "Budi Santoso"),
    Placeholder("employee_number", "Nomor pegawai", "SGA001"),
    Placeholder("submitter_name", "Nama pengaju", "Budi Santoso"),
    Placeholder("workflow_name", "Nama alur", "Cuti Site"),
    Placeholder("step_name", "Nama tahap berjalan", "Approved By (Atasan Langsung)"),
    Placeholder("step_sequence", "Nomor tahap", "3"),
    Placeholder("step_total", "Jumlah tahap", "6"),
)


WORKFLOW_PENDING = register_event(
    NotificationEvent(
        code="workflow.pending_approval",
        label="Document Awaiting Your Approval",
        module="workflow",
        category="Persetujuan",
        description=(
            "Dikirim kepada approver saat dokumen mendarat di mejanya — "
            "saat diajukan maupun saat tahap sebelumnya selesai. Tanpa "
            "ini, dokumen mengendap sampai ada yang kebetulan membuka "
            "kotak masuk."
        ),
        placeholders=_DOCUMENT_PLACEHOLDERS,
        default_recipients=(RecipientType.PENDING_APPROVER,),
        default_subject=(
            "Menunggu persetujuan Anda: {{ document_label }}"
            "{% if document_number %} ({{ document_number }}){% endif %}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Ada dokumen yang menunggu keputusan Anda.\n\n"
            "Dokumen: {{ document_label }}\n"
            "Nomor: {{ document_number }}\n"
            "Diajukan oleh: {{ submitter_name }}\n"
            "Tahap: {{ step_name }} ({{ step_sequence }} dari "
            "{{ step_total }})\n\n"
            "Silakan buka aplikasi untuk menyetujui, menolak, atau "
            "mengembalikannya untuk diperbaiki."
        ),
    ),
)


WORKFLOW_APPROVED = register_event(
    NotificationEvent(
        code="workflow.approved",
        label="Submission Approved",
        module="workflow",
        category="Persetujuan",
        description=(
            "Dikirim kepada pengaju saat seluruh tahap selesai dan "
            "dokumennya disetujui."
        ),
        placeholders=_DOCUMENT_PLACEHOLDERS,
        default_recipients=(
            RecipientType.SUBMITTER,
            # Penyiap dokumennya — yang mengisi meja pertama, dan di
            # alur site itu Admin Section, bukan pengajunya. Dialah
            # yang akan dimintai perbaikan; tanpa ini ia tidak pernah
            # tahu dokumennya sudah diputuskan. `merge()` menyatukan
            # penerima kembar, jadi alur yang meja pertamanya memang
            # pengaju sendiri tetap mengirim satu surat.
            #
            # `SUBJECT` sengaja **tidak** ikut di bawaan. Kalimat
            # bawaan ketiga event ini ditulis untuk pengaju ("Pengajuan
            # Anda sudah disetujui"), dan Employee Action pemutusan
            # hubungan kerja akan mengirimkannya kepada orang yang
            # justru tidak mengajukan apa pun. Tenant yang memang ingin
            # pegawainya ikut diberi tahu menambahkannya sebagai baris
            # di layar Notification Rules — di situ kalimatnya bisa
            # sekalian disesuaikan.
            RecipientType.PREPARER,
        ),
        default_subject="Disetujui: {{ document_label }}",
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Pengajuan Anda sudah disetujui seluruhnya.\n\n"
            "Dokumen: {{ document_label }}\n"
            "Nomor: {{ document_number }}\n\n"
            "Anda bisa membuka dokumennya untuk melihat rincian dan "
            "riwayat persetujuannya."
        ),
    ),
)


WORKFLOW_REJECTED = register_event(
    NotificationEvent(
        code="workflow.rejected",
        label="Submission Rejected",
        module="workflow",
        category="Persetujuan",
        description="Dikirim kepada pengaju saat dokumennya ditolak.",
        placeholders=_DOCUMENT_PLACEHOLDERS
        + (
            Placeholder("decided_by", "Yang memutuskan", "Siti Rahayu"),
            Placeholder("comment", "Alasan", "Tanggalnya bentrok dengan jadwal audit."),
        ),
        default_recipients=(
            RecipientType.SUBMITTER,
            # Penyiap dokumennya — yang mengisi meja pertama, dan di
            # alur site itu Admin Section, bukan pengajunya. Dialah
            # yang akan dimintai perbaikan; tanpa ini ia tidak pernah
            # tahu dokumennya sudah diputuskan. `merge()` menyatukan
            # penerima kembar, jadi alur yang meja pertamanya memang
            # pengaju sendiri tetap mengirim satu surat.
            #
            # `SUBJECT` sengaja **tidak** ikut di bawaan. Kalimat
            # bawaan ketiga event ini ditulis untuk pengaju ("Pengajuan
            # Anda sudah disetujui"), dan Employee Action pemutusan
            # hubungan kerja akan mengirimkannya kepada orang yang
            # justru tidak mengajukan apa pun. Tenant yang memang ingin
            # pegawainya ikut diberi tahu menambahkannya sebagai baris
            # di layar Notification Rules — di situ kalimatnya bisa
            # sekalian disesuaikan.
            RecipientType.PREPARER,
        ),
        default_subject="Ditolak: {{ document_label }}",
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Pengajuan Anda ditolak pada tahap {{ step_name }}.\n\n"
            "Dokumen: {{ document_label }}\n"
            "Nomor: {{ document_number }}\n"
            "Diputuskan oleh: {{ decided_by }}\n"
            "{% if comment %}Alasan: {{ comment }}{% endif %}\n\n"
            "Silakan buat pengajuan baru bila diperlukan."
        ),
    ),
)


WORKFLOW_RETURNED = register_event(
    NotificationEvent(
        code="workflow.returned",
        label="Submission Returned for Revision",
        module="workflow",
        category="Persetujuan",
        description=(
            "Dikirim kepada pengaju saat dokumennya dikembalikan — bukan "
            "ditolak. Ini yang membedakan satu tanggal salah ketik dari "
            "pengajuan yang memang tidak disetujui."
        ),
        placeholders=_DOCUMENT_PLACEHOLDERS
        + (
            Placeholder("decided_by", "Yang mengembalikan", "Siti Rahayu"),
            Placeholder("comment", "Catatan perbaikan", "Mohon lampirkan surat dokter."),
        ),
        default_recipients=(
            RecipientType.SUBMITTER,
            # Penyiap dokumennya — yang mengisi meja pertama, dan di
            # alur site itu Admin Section, bukan pengajunya. Dialah
            # yang akan dimintai perbaikan; tanpa ini ia tidak pernah
            # tahu dokumennya sudah diputuskan. `merge()` menyatukan
            # penerima kembar, jadi alur yang meja pertamanya memang
            # pengaju sendiri tetap mengirim satu surat.
            #
            # `SUBJECT` sengaja **tidak** ikut di bawaan. Kalimat
            # bawaan ketiga event ini ditulis untuk pengaju ("Pengajuan
            # Anda sudah disetujui"), dan Employee Action pemutusan
            # hubungan kerja akan mengirimkannya kepada orang yang
            # justru tidak mengajukan apa pun. Tenant yang memang ingin
            # pegawainya ikut diberi tahu menambahkannya sebagai baris
            # di layar Notification Rules — di situ kalimatnya bisa
            # sekalian disesuaikan.
            RecipientType.PREPARER,
        ),
        default_subject="Perlu diperbaiki: {{ document_label }}",
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Pengajuan Anda dikembalikan untuk diperbaiki pada tahap "
            "{{ step_name }}.\n\n"
            "Dokumen: {{ document_label }}\n"
            "Nomor: {{ document_number }}\n"
            "Dikembalikan oleh: {{ decided_by }}\n"
            "{% if comment %}Catatan: {{ comment }}{% endif %}\n\n"
            "Silakan perbaiki lalu ajukan kembali."
        ),
    ),
)


# ----------------------------------------------------------------------
# Travel Request
# ----------------------------------------------------------------------
#
# Di luar jalur approval. Yang lewat approval sudah ditangani empat
# event di atas — dua di bawah ini kejadian yang tidak punya tombol
# setuju: tiketnya terbit, dan hari keberangkatannya mendekat.

_TRAVEL_PLACEHOLDERS = (
    Placeholder("document_number", "Nomor TR", "TR260031"),
    Placeholder("employee_name", "Nama pegawai", "Budi Santoso"),
    Placeholder("employee_number", "Nomor pegawai", "SGA001"),
    Placeholder("departure_date", "Tanggal berangkat", "14 September 2026"),
    Placeholder("return_date", "Tanggal kembali", "28 September 2026"),
    Placeholder("origin", "Dari", "Gebe"),
    Placeholder("destination", "Ke", "Makassar"),
    Placeholder("days_left", "Sisa hari sampai berangkat", "7"),
)


TRAVEL_ISSUED = register_event(
    NotificationEvent(
        code="hr.travel_request_issued",
        label="Travel Request Issued",
        module="hr",
        category="Perjalanan",
        description=(
            "Dikirim saat Travel Request selesai disetujui dan "
            "penerbitannya dijalankan — pegawainya perlu tahu jadwalnya "
            "sudah pasti, bukan cuma bahwa dokumennya disetujui."
        ),
        placeholders=_TRAVEL_PLACEHOLDERS,
        default_recipients=(RecipientType.SUBJECT, RecipientType.ROLE),
        default_roles=("HRGA",),
        default_subject=(
            "Travel Request {{ document_number }} diterbitkan"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Travel Request {{ document_number }} atas nama "
            "{{ employee_name }} sudah diterbitkan.\n\n"
            "Berangkat: {{ departure_date }}\n"
            "Kembali: {{ return_date }}\n"
            "Rute: {{ origin }} → {{ destination }}\n\n"
            "Rincian etape dan nomor tiket bisa dilihat di dokumennya."
        ),
    ),
)


TRAVEL_DEPARTURE = register_event(
    NotificationEvent(
        code="hr.travel_departure_reminder",
        label="Departure Reminder",
        module="hr",
        category="Perjalanan",
        description=(
            "Pengingat H-N sebelum tanggal berangkat. Ambang harinya "
            "diatur di Roster Policy (Notify Lead Days)."
        ),
        placeholders=_TRAVEL_PLACEHOLDERS,
        default_recipients=(RecipientType.SUBJECT,),
        default_subject=(
            "Keberangkatan {{ days_left }} hari lagi — "
            "{{ document_number }}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Pengingat: keberangkatan Anda dijadwalkan "
            "{{ departure_date }}, {{ days_left }} hari lagi.\n\n"
            "Nomor TR: {{ document_number }}\n"
            "Rute: {{ origin }} → {{ destination }}\n\n"
            "Mohon pastikan dokumen perjalanan dan tiket sudah di tangan."
        ),
    ),
)


# ----------------------------------------------------------------------
# Saldo cuti
# ----------------------------------------------------------------------

LEAVE_EXPIRING = register_event(
    NotificationEvent(
        code="hr.leave_balance_expiring",
        label="Leave Balance Expiring",
        module="hr",
        category="Cuti",
        description=(
            "Dikirim saat saldo cuti yang punya masa berlaku mendekati "
            "tanggal hangusnya — sisa bawaan tahun lalu maupun saldo "
            "awal migrasi. Jatah tahun berjalan tidak punya tanggal "
            "hangus, jadi tidak pernah memicu pengingat ini."
        ),
        placeholders=(
            Placeholder("employee_name", "Nama pegawai", "Budi Santoso"),
            Placeholder("employee_number", "Nomor pegawai", "SGA001"),
            Placeholder("leave_type_name", "Jenis cuti", "Cuti Tahunan"),
            Placeholder("expiring_days", "Sisa hari cuti yang akan hangus", "4.0"),
            Placeholder("expiry_date", "Tanggal hangus", "31 Maret 2027"),
            Placeholder("days_left", "Sisa hari sampai hangus", "30"),
            Placeholder("remaining", "Total sisa saldo", "16.0"),
            Placeholder("year", "Tahun saldo", "2026"),
            # Kantong mana yang akan hangus. Perlu disebut karena
            # kalimatnya berbeda artinya: "sisa tahun lalu" adalah hak
            # yang sudah pernah dibawa, "saldo awal" adalah bawaan dari
            # sistem lama yang baru sekali ini muncul di layar.
            Placeholder("pocket_label", "Kantong yang akan hangus", "Sisa tahun lalu"),
        ),
        default_recipients=(RecipientType.SUBJECT,),
        default_subject=(
            "{{ expiring_days }} hari {{ leave_type_name }} hangus "
            "{{ expiry_date }}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "{{ pocket_label }} untuk {{ leave_type_name }} tahun "
            "{{ year }} sebanyak {{ expiring_days }} hari akan hangus "
            "pada {{ expiry_date }} — {{ days_left }} hari lagi.\n\n"
            "Total sisa saldo Anda saat ini: {{ remaining }} hari.\n\n"
            "Silakan ajukan cuti sebelum tanggal tersebut bila ingin "
            "menggunakannya."
        ),
    ),
)


# ----------------------------------------------------------------------
# Presensi
# ----------------------------------------------------------------------
#
# Penandanya sendiri sudah lama dihitung `AttendancePolicyResolver`, tapi
# tersimpan di kolom yang tidak dibuka siapa pun sampai ada yang
# kebetulan membuka layar Attendance. Dua event di bawah yang membuatnya
# sampai ke orangnya.
#
# **Tidak** memicu pemotongan saldo apa pun. Yang memotong tetap dokumen
# cuti yang diajukan dan disetujui — lihat `AttendanceObligationService`.

ATTENDANCE_EXCEPTION = register_event(
    NotificationEvent(
        code="hr.attendance_exception",
        label="Attendance Exception",
        module="hr",
        category="Presensi",
        description=(
            "Dikirim saat keterlambatan atau pulang cepat melewati "
            "ambang di Attendance Policy. Penerima bawaannya pegawainya "
            "sendiri dan **atasan langsung** (`Reports To`), karena "
            "atasannya yang meninjau apakah pengecualiannya sah."
        ),
        placeholders=(
            Placeholder("employee_name", "Nama pegawai", "Budi Santoso"),
            Placeholder("employee_number", "Nomor pegawai", "SGA001"),
            Placeholder("work_date", "Tanggal presensi", "14 Agustus 2026"),
            Placeholder("late_minutes", "Menit keterlambatan", "135"),
            Placeholder("early_leave_minutes", "Menit pulang cepat", "0"),
            Placeholder("reason_label", "Sebabnya", "Terlambat"),
            Placeholder(
                "leave_days",
                "Hari cuti yang seharusnya diambil",
                "1.00",
            ),
        ),
        default_recipients=(
            RecipientType.SUBJECT,
            RecipientType.MANAGER,
        ),
        default_subject=(
            "Pengecualian presensi {{ employee_name }} — {{ work_date }}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Presensi {{ employee_name }} ({{ employee_number }}) pada "
            "{{ work_date }} melewati ambang yang berlaku: "
            "{{ reason_label }}.\n\n"
            "Menurut aturan, hari itu setara {{ leave_days }} hari "
            "cuti.\n\n"
            "**Saldo cuti belum berkurang.** Atasan langsung meninjau "
            "dulu: kalau pengecualiannya sah, baris ini dibebaskan "
            "beserta alasannya; kalau tidak, pegawainya diminta "
            "mengajukan cuti lewat modul Cuti seperti biasa."
        ),
    ),
)


ATTENDANCE_LEAVE_REQUIRED = register_event(
    NotificationEvent(
        code="hr.attendance_leave_required",
        label="Asked to Submit Leave",
        module="hr",
        category="Presensi",
        description=(
            "Dikirim saat atasan menilai pengecualian presensinya tidak "
            "sah, sehingga pegawainya harus mengajukan cuti. Yang "
            "memotong saldo tetap dokumen cutinya sendiri setelah "
            "disetujui."
        ),
        placeholders=(
            Placeholder("employee_name", "Nama pegawai", "Budi Santoso"),
            Placeholder("employee_number", "Nomor pegawai", "SGA001"),
            Placeholder("work_date", "Tanggal presensi", "14 Agustus 2026"),
            Placeholder("late_minutes", "Menit keterlambatan", "135"),
            Placeholder("early_leave_minutes", "Menit pulang cepat", "0"),
            Placeholder("reason_label", "Sebabnya", "Terlambat"),
            Placeholder("leave_days", "Hari cuti yang harus diajukan", "1.00"),
            Placeholder("review_notes", "Catatan atasan", "Tanpa kabar"),
        ),
        default_recipients=(RecipientType.SUBJECT,),
        default_subject=(
            "Ajukan cuti {{ leave_days }} hari untuk {{ work_date }}"
        ),
        default_body=(
            "Halo {{ recipient_first_name }},\n\n"
            "Presensi Anda pada {{ work_date }} ({{ reason_label }}) "
            "sudah ditinjau, dan Anda diminta mengajukan cuti sebanyak "
            "{{ leave_days }} hari untuk tanggal tersebut.\n\n"
            "Catatan atasan: {{ review_notes }}\n\n"
            "Silakan buat pengajuan lewat menu Cuti."
        ),
    ),
)
