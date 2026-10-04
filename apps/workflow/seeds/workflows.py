"""
Alur persetujuan bawaan.

Ditulis sebagai alur **global** (tanpa company) supaya berlaku di semua
company yang belum punya alurnya sendiri. Tenant yang butuh alur berbeda
tinggal menyalin barisnya dan mengisi cakupannya — pencarian di
`WorkflowDefinitionResolver` memenangkan yang lebih khusus, tanpa siapa
pun perlu mengatur prioritas manual.

Yang diseed, dan yang bercakupan lokasi menang atas yang tidak:

* ``HR-LEAVE-STD``        — cuti, berlaku untuk semua pegawai
* ``HR-TRAVEL-REQUEST``   — Travel Request, mengikuti kotak tanda tangan
  di formulir yang dipakai klien tambang
* ``HR-HO-LEAVE``         — cuti pegawai Head Office
* ``HR-LEAVE-SITE`` / ``HR-TR-SITE`` — cuti dan Travel Request pegawai
  site, enam meja yang sama untuk kedua dokumen (lihat ``SITE_STEPS``)
* ``HR-VISITOR-REQUEST``, ``HR-EMPLOYEE-ACTION``,
  ``HR-ROSTER-SETUP``, ``HR-ROSTER-ADJUSTMENT``

Cakupan Head Office diikat ke **Location**, bukan ke nama company atau
ke tebakan "pegawai tanpa roster": Location adalah tempat orang bekerja,
dan itu kolom yang memang sudah dipakai kalender kerja serta perhitungan
hari cuti. Lokasi HO-nya dicari dari master; kalau tidak ketemu, alur
HO-nya dilewati dengan pesan, bukan dibuatkan lokasi karangan.
"""

from django.db import transaction

from apps.accounts.models import Role
from apps.administration.models import Location
from apps.workflow.models import (
    ApprovalMode,
    ApproverScope,
    ApproverType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepFallback,
)


# Role yang dibutuhkan step non-komando. Diseed di sini, bukan
# diandaikan sudah ada: alur yang menunjuk role tidak ada akan gagal
# saat Submit ditekan, jauh dari layar tempat alurnya dikonfigurasi.
REQUIRED_ROLES = [
    ("HR-ADMIN", "HR Admin"),
    ("HR-MANAGER", "HR Manager"),

    # Bagian umum yang mengurus tiket dan akomodasi.
    ("HRGA", "HR & General Affairs"),

    # Meja pertama alur perjalanan site: admin yang mengetikkan
    # dokumennya untuk pegawai di section-nya.
    ("ADMIN-SECTION", "Admin Section"),

    # Satu tingkat di atas Admin Section. Ada supaya turunan meja
    # pertama alur site pasti: section → department → HR, bukan
    # section → langsung melompat ke HR kantor pusat.
    ("ADMIN-DEPARTMENT", "Admin Department"),

    # Meja kedua alur payroll. Payroll adalah dokumen keuangan: HR
    # menyatakan angkanya benar, Finance menyatakan uangnya tersedia.
    # Satu meja saja membuat keduanya jadi keputusan yang sama.
    ("FINANCE-MANAGER", "Finance Manager"),

    # Meja kedua alur jurnal, untuk dokumen bernilai besar. Ia yang
    # menyiapkan bagan akun dan kebijakannya, jadi ia pula yang paling
    # bisa menilai apakah sebuah ayat mendarat di akun yang benar.
    ("FINANCE-ADMIN", "Finance Administrator"),

    # Otoritas tertinggi di site. Meja terakhir alur perjalanan site —
    # penerbitan tiket menunggu tanda tangannya.
    #
    # Kodenya `KTT`, bukan `KTT-SITE`: akhiran itu dulu menandai role
    # yang cakupannya "ikut penempatan pemegang", dan cakupan sudah tidak
    # tinggal di `Role` lagi. Yang membuat meja ini per-site
    # `approver_scope=LOCATION` pada step-nya, bukan nama role-nya.
    ("KTT", "Kepala Teknik Tambang"),

    # Boleh mengubah konfigurasi alur tanpa harus jadi superuser —
    # yang artinya bisa mengubah apa pun di seluruh sistem.
    ("WORKFLOW-ADMIN", "Workflow Administrator"),

    # Boleh mengelola user, role, dan hak akses. Wewenang paling
    # berbahaya di sistem: pemegangnya bisa memberi dirinya role apa
    # pun. Diseed kosong — harus ada yang menugaskannya sadar.
    ("SECURITY-ADMIN", "Security Administrator"),
]


# Kode lokasi yang dianggap Head Office. Beberapa ejaan sekaligus
# karena master tiap tenant berbeda — yang pertama ketemu yang dipakai.
HEAD_OFFICE_CODES = ["HO", "JKT-HO", "HEAD-OFFICE", "HO-JKT", "JAKARTA HO"]


LEAVE_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
    },
    {
        "sequence": 2,
        "name": "Verified By (HR)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        "fallback_role": "HR-MANAGER",
    },
]


HEAD_OFFICE_LEAVE_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
    },
    # **Meja #2 (Kepala Departemen) dihapus** atas keputusan pemilik
    # aturannya (21 Ags 2026): rantai cuti kantor pusat adalah pegawai
    # mengajukan → Atasan Langsung → HR Manager, dua meja saja. Baris
    # lamanya dinonaktifkan `_retire_extra_steps` begitu seed ini
    # dijalankan ulang — soft delete, jadi kotak tanda tangan dokumen
    # yang sudah berjalan tetap bisa dibaca.
    {
        # **Nomornya sengaja tetap 3, bukan dirapatkan jadi 2.**
        # `_write` mencocokkan step lewat `(definition, sequence)`, jadi
        # menomorinya ulang berarti menulis ulang baris milik Kepala
        # Departemen menjadi HR Manager — dan kotak masuk membaca
        # `step.name` yang **hidup** (`WorkflowApprovalSerializer`),
        # bukan salinan beku di barisnya. Dokumen lama akan berubah
        # bunyinya belakangan. Lompatan angkanya kosmetik; riwayat yang
        # bergeser tidak.
        "sequence": 3,
        "name": "Approved By (HR Manager)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-MANAGER",
        # Per lokasi, supaya cuti pegawai kantor pusat tidak nyasar ke
        # HR Manager site — keduanya memegang role yang sama, dan tanpa
        # ini yang menandatangani ditentukan urutan `employee_number`.
        "approver_scope": ApproverScope.LOCATION,
        "fallback_role": "HR-ADMIN",
        # **Tanpa syarat: seluruh cuti kantor pusat naik sampai sini.**
        #
        # Dulu meja ini bersyarat `total_days >= 5`, dan syarat itu
        # dicabut atas keputusan pemilik aturannya (20 Ags 2026) — HR
        # Manager menandatangani semua cuti HO, bukan yang panjang saja.
        #
        # Yang perlu diingat kalau suatu saat syaratnya mau
        # dikembalikan: syarat menentukan apakah mejanya **ada**, dan
        # `is_required` menentukan apa yang terjadi kalau approver-nya
        # tidak ketemu. Keduanya menjawab pertanyaan berbeda, dan
        # `is_required=True` di sini tidak pernah menghalangi syarat
        # melewatkan step — itu yang sempat membuat cuti dua hari
        # terbaca seolah approver-nya hilang.
    },
]


# Enam meja alur site, dipakai **dua kali**: untuk Travel Request dan
# untuk Cuti. Pegawai site yang pulang cuti tetap harus dibelikan tiket,
# jadi dua dokumen itu melewati meja yang sama — dan menyalin rantainya
# jadi dua daftar berarti dua daftar yang harus dijaga tetap sama.
#
#     Admin Section (atau Admin Department kalau section-nya belum
#     punya) → HR Admin Site → Atasan Langsung → HR Manager Site →
#     KTT Site → HRGA
#
# **Pembuatnya tidak menandatangani dokumennya sendiri.** Pegawai
# mengajukan, lalu enam meja memutuskan.
#
# **Hanya meja #1 yang punya cadangan**, dan cadangan itu satu tingkat
# saja. Lima sisanya sengaja kosong: meja yang tidak ada pemegangnya
# berarti datanya belum lengkap, dan pengajuan yang ditolak dengan
# menyebut kolomnya jauh lebih murah daripada dokumen yang lolos lewat
# meja yang diisi orang yang salah. Kebocoran seperti itu tidak
# berbunyi — dokumennya tetap jalan, cuma ditandatangani orang yang
# tidak berwenang atasnya.
#
# Cakupan tiap meja sengaja dicampur, dan itu inti konfigurasinya: lima
# meja pertama dicari **di site pegawainya** (section/location), HRGA
# per **company** karena ia duduk di kantor pusat dan melayani seluruh
# site. Tanpa `approver_scope`, keenamnya menarik pemegang role
# se-company dan pengajuan Sagea ikut mendarat di kotak masuk site lain.
#
# **HRGA sengaja meja terakhir.** `WorkflowStep` tidak punya efek
# samping sendiri — satu-satunya callback adalah `on_complete` yang
# jalan saat seluruh alur selesai. Di posisi mana pun selain terakhir,
# step bernama "Issued By" akan berbohong: approver menekan tombol,
# giliran pindah, dan status dokumennya belum bergerak. Di posisi #6
# tombolnya benar-benar menutup alur, `TravelRequestStatus` jadi
# APPROVED, dan tiketnya memang terbit saat itu — setelah KTT setuju,
# bukan sebelum.
SITE_STEPS = [
    {
        "sequence": 1,
        "name": "Prepared By (Admin Section / Department)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "ADMIN-SECTION",
        "approver_scope": ApproverScope.SECTION,
        # **Satu meja, dua kemungkinan pengisi — bukan dua step.**
        # Admin Section yang mengetik; Admin Department hanya menerima
        # pekerjaan itu kalau section pegawainya memang belum punya
        # adminnya sendiri. Menjadikannya dua step terpisah berarti
        # dokumen yang section-nya lengkap tetap menunggu tanda tangan
        # department, dan yang mengetiknya diminta menyetujui
        # ketikannya sendiri satu meja kemudian.
        #
        # Turunannya berhenti di sini. Tingkat HR yang dulu ada
        # (`HR-ADMIN` di location lalu di company) sudah **dicabut**:
        # ia memindahkan pekerjaan mengetik dokumen site ke meja yang
        # tidak mengenal orangnya, dan pindahnya diam-diam — dokumennya
        # tetap jalan, cuma disiapkan orang yang tidak tahu siapa yang
        # sedang di site. Sekarang section dan department sama-sama
        # kosong berarti pengajuannya ditolak dengan menyebut kedua
        # tingkat yang sudah dicoba, dan yang memperbaiki tahu persis
        # baris mana yang harus diisi.
        "fallbacks": [
            ("ADMIN-DEPARTMENT", ApproverScope.DEPARTMENT),
        ],
    },
    {
        "sequence": 2,
        "name": "HR Admin Site Review",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        "approver_scope": ApproverScope.LOCATION,
        # **Tanpa cadangan, dan itu bukan kelalaian.** Cadangan lamanya
        # HR Manager — orang yang sama yang memegang meja #4. Begitu ia
        # mengisi meja #2, engine menandai meja #4 SKIPPED sebagai
        # "sudah terwakili", dan dua meja yang sengaja dipisah runtuh
        # jadi satu tanpa satu pun pesan. Site yang belum punya HR Admin
        # sendiri: itu yang harus diisi.
        "fallback_role": None,
    },
    {
        "sequence": 3,
        "name": "Direct Supervisor Approval",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        # **Tanpa cadangan.** Yang dicari atasan langsung pegawainya
        # sendiri (`OrganizationAssignment.reports_to`), bukan "siapa
        # pun yang jabatannya supervisor" dan bukan kepala departemen.
        # Cadangan HR Manager yang dulu ada membuat `reports_to` kosong
        # gagal ke arah yang paling merugikan: dokumennya lolos, meja
        # atasan diisi orang yang tidak pernah membawahi pegawainya,
        # dan tidak ada yang tahu garis pelaporannya belum diisi.
        # Sekarang pengajuannya ditolak dengan menyebut kolomnya.
        "fallback_role": None,
    },
    {
        "sequence": 4,
        "name": "HR Manager Site Approval",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-MANAGER",
        # Per site, bukan per company: HR Manager kantor pusat tidak
        # ikut menandatangani kepulangan pegawai Sagea. Kalau site-nya
        # belum punya HR Manager sendiri, itu yang harus diisi — bukan
        # dilonggarkan diam-diam ke kantor pusat.
        "approver_scope": ApproverScope.LOCATION,
        "fallback_role": None,
    },
    {
        "sequence": 5,
        "name": "KTT Site Approval",
        "approver_type": ApproverType.ROLE,
        "approver_role": "KTT",
        "approver_scope": ApproverScope.LOCATION,
        # Otoritas tertinggi di site dan persetujuan bisnis terakhir.
        # Tanpa cadangan: kalau tidak ada KTT di site itu, yang salah
        # datanya, bukan dokumennya. Melompatinya ke HRGA berarti tiket
        # terbit tanpa satu pun keputusan lapangan.
        "fallback_role": None,
    },
    {
        "sequence": 6,
        "name": "Issued By (HRGA)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HRGA",
        # Lintas site — HRGA di kantor pusat membelikan tiket untuk
        # semua orang, jadi Company, bukan Location.
        "approver_scope": ApproverScope.COMPANY,
        # Tidak ada cadangan yang masuk akal: kalau tidak ada yang
        # memegang HRGA, tidak ada yang membeli tiketnya — dan dokumen
        # yang lolos sampai "issued" tanpa tiket lebih berbahaya
        # daripada pengajuan yang ditolak dengan alasan jelas.
        #
        # HRGA **bukan pengganti** persetujuan KTT: ia memproses apa
        # yang sudah diputuskan, bukan memutuskannya.
        "fallback_role": None,
    },
]


# Perubahan data kepegawaian: kontrak, jenis, penempatan, gaji.
#
# **Satu definisi untuk dua belas jenis action**, bukan dua belas
# definisi. Yang membedakan tiap jenis cuma sejauh mana dokumennya naik,
# dan itu urusan `condition` pada step — bukan alasan untuk menyalin
# rantai yang sama dua belas kali dan menjaganya tetap sama.
#
# `action_type` dibaca dari `WorkflowInstance.context` yang dibekukan
# saat pengajuan, jadi mengganti jenis di tengah alur tidak mengubah
# meja yang sudah terbentuk.
EMPLOYEE_ACTION_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        # Garis pelaporan adalah data yang paling sering bolong di
        # tenant baru, dan meja ini tidak boleh mengunci dokumennya.
        "fallback_role": "HR-MANAGER",
    },
    {
        "sequence": 2,
        "name": "Verified By (HR)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        "fallback_role": "HR-MANAGER",
    },
    {
        "sequence": 3,
        "name": "Approved By (HR Manager)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-MANAGER",
        # Per lokasi: HR Manager kantor pusat tidak menandatangani
        # pengangkatan pegawai site, dan sebaliknya. Role yang sama
        # dipegang dua orang di dua tempat.
        "approver_scope": ApproverScope.LOCATION,
        "fallback_role": "HR-ADMIN",
        # Perpanjangan kontrak dan koreksi status berhenti di HR.
        # Yang mengubah biaya perusahaan atau mengakhiri hubungan
        # kerja naik satu meja lagi — aturannya ditulis di sini, bukan
        # ditanam di kode modul.
        "condition": {
            "field": "action_type",
            "op": "in",
            "value": [
                "employment_type_change",
                "salary_change",
                "promotion",
                "demotion",
                "resignation",
                "termination",
            ],
        },
    },
]


# Setup roster massal. **Tiga meja**, dan yang di tengah bertipe
# per-pegawai.
#
# Dokumennya dibuat dan diajukan Admin Department / Admin Section —
# pembuat tidak menandatangani dokumennya sendiri, jadi ia tidak punya
# meja di sini. Lalu: HR Admin Site memeriksa datanya, **atasan
# langsung** menyetujui jadwal timnya, dan HR Manager Site menutup
# alurnya; sesudah itu dokumennya commit sendiri lewat `on_complete`.
#
# Meja #2 dulu **dilarang**: satu dokumen memuat puluhan pegawai, jadi
# "atasan langsung" dianggap tidak menunjuk satu orang. Larangan itu
# terlalu keras — yang benar bukan membuang mejanya, melainkan
# mensyaratkan batch-nya memang punya satu atasan.
# `RosterSetupService.batch_approver_findings` memeriksanya lewat
# resolver yang sama dengan engine, dan dokumen yang atasannya
# berbeda-beda ditolak **di preview** dengan menyebut siapa membawahi
# siapa — supaya dipecah per atasan, bukan dijatuhkan diam-diam ke satu
# nama.
#
# Cakupan meja Role-nya Location, bukan Company: dokumen setup Gebe
# tidak boleh mendarat di kotak masuk HR site lain. Ini yang menjaga
# satu batch = satu site tetap punya arti.
ROSTER_SETUP_STEPS = [
    {
        "sequence": 1,
        "name": "Reviewed By (HR Admin Site)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        "approver_scope": ApproverScope.LOCATION,
        "fallback_role": "HR-MANAGER",
    },
    {
        # Atasan langsung pegawai yang dijadwalkan
        # (`OrganizationAssignment.reports_to`), bukan kepala
        # departemen dan bukan "siapa pun yang jabatannya supervisor".
        #
        # Tanpa cadangan, dan itu disengaja: `reports_to` yang kosong
        # harus **menghentikan** pengajuan dengan menyebut kolomnya,
        # bukan lolos dengan meja atasan diisi orang yang tidak pernah
        # membawahi siapa pun di dokumen ini.
        "sequence": 2,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        "fallback_role": None,
    },
    {
        "sequence": 3,
        "name": "Approved By (HR Manager Site)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-MANAGER",
        "approver_scope": ApproverScope.LOCATION,
        # Tanpa cadangan: jadwal setahun untuk puluhan orang tidak boleh
        # terbit tanpa satu pun manajer melihatnya. Kalau site-nya belum
        # punya HR Manager, itu yang harus diisi.
        "fallback_role": None,
    },
]


# Penyesuaian jadwal yang sudah berjalan.
#
# Beda dengan setup: ini dokumen **satu pegawai**, jadi atasan
# langsungnya jelas siapa. Meja ketiga hanya untuk yang menyentuh
# saldo — menggeser tanggal dua hari tidak perlu naik ke HR Manager,
# tapi menerbitkan kredit berarti menambah hak yang bisa diuangkan.
ROSTER_ADJUSTMENT_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        "fallback_role": "HR-MANAGER",
    },
    {
        "sequence": 2,
        "name": "Verified By (Admin HR Site)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        "approver_scope": ApproverScope.LOCATION,
        "fallback_role": "HR-MANAGER",
    },
    {
        "sequence": 3,
        "name": "Approved By (HR Manager)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-MANAGER",
        "approver_scope": ApproverScope.LOCATION,
        "fallback_role": "HR-ADMIN",
        "condition": {
            "field": "credit_impact",
            "op": "in",
            "value": ["earn", "use"],
        },
    },
]


TRAVEL_REQUEST_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
    },
    {
        "sequence": 2,
        "name": "Acknowledged By (Kepala Departemen)",
        "approver_type": ApproverType.DEPARTMENT_HEAD,
        "is_required": False,
    },
    {
        "sequence": 3,
        "name": "Verified By (HR)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        "fallback_role": "HR-MANAGER",
    },
]


# Kunjungan tamu.
#
# Dua meja, dan pendeknya disengaja: tamu yang datang rapat sejam tidak
# boleh menunggu empat tanda tangan, dan alur yang terlalu panjang untuk
# hal sesederhana ini akan dilewati orang — mereka menerima tamunya dulu
# lalu mengetik dokumennya belakangan, dan sesudah itu catatan siapa
# masuk kapan tidak ada gunanya lagi.
#
# Meja pertama tuan rumahnya sendiri, dan itu bukan formalitas: pemohon
# lazim sekretaris atau admin, sementara yang tahu tamunya memang
# diundang adalah orang yang akan menerimanya. `USER` di sini tidak
# dipakai — approver-nya berbeda per dokumen, jadi tipenya `MANAGER`
# terhadap pemohon. Yang mengajukan untuk dirinya sendiri dilewati
# engine lewat `initiator_employee`; tanpa itu ia diminta menyetujui
# undangannya sendiri.
# Business Trip — Atasan Langsung → HRGA (keputusan final BT-0B #1).
#
# Atasan menilai kebutuhan bisnisnya; HRGA menilai kebijakan perjalanan
# dan kelengkapan administrasinya. **Tanpa meja Finance**: uang muka dan
# penyelesaian perjalanan belum ada. Rantai ini konfigurasi, bukan kode —
# service Business Trip tidak menyebut satu pun meja; tenant mengubahnya
# lewat definisi yang lebih khusus (company/lokasi/employee group).
BUSINESS_TRIP_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        # Cadangan HRGA: pegawai yang `reports_to`-nya belum diisi tetap
        # bisa mengajukan, sama alasannya dengan Visitor Request.
        "fallback_role": "HRGA",
    },
    {
        "sequence": 2,
        "name": "Verified By (HRGA)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HRGA",
        "approver_scope": ApproverScope.COMPANY,
        # Berjenjang (BT-APPROVER-2), yang pertama ketemu yang menang:
        #
        # 1. HR Admin se-company — cadangan lama, sekarang tertulis;
        #    company yang sudah punya HR Admin tidak berubah rutenya.
        # 2. HR Manager se-company — tingkat yang sudah dipakai Leave dan
        #    Travel Request; company tanpa HR Admin (MIN) berhenti di sini.
        # 3. HR Manager se-tenant — jaring terakhir untuk company tanpa
        #    personel HR sama sekali (holding), dan untuk HR Manager yang
        #    mengajukan perjalanannya sendiri: engine mengeluarkan dirinya,
        #    jadi HR Manager company lain yang menyetujui. HR melayani
        #    seluruh grup, itulah guna `TENANT` (lihat `ApproverScope`).
        #
        # Tidak ada role yang perlu dibagikan supaya rute ini jalan.
        "fallbacks": [
            ("HR-ADMIN", ApproverScope.COMPANY),
            ("HR-MANAGER", ApproverScope.COMPANY),
            ("HR-MANAGER", ApproverScope.TENANT),
        ],
    },
]


VISITOR_REQUEST_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        # Ada cadangan, berbeda dengan alur roster: kunjungan diajukan
        # siapa saja termasuk orang yang `reports_to`-nya belum diisi,
        # dan tamu yang sudah di depan gerbang tidak bisa menunggu data
        # organisasi dirapikan.
        "fallback_role": "HRGA",
    },
    {
        "sequence": 2,
        "name": "Verified By (HRGA / Security)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HRGA",
        # Se-company, bukan per-lokasi: bagian umum yang mengurus tamu
        # lazim duduk di kantor pusat, dan meja per-lokasi akan kosong
        # di site yang tidak punya HRGA sendiri.
        "approver_scope": ApproverScope.COMPANY,
        "fallback_role": "HR-ADMIN",
    },
]


# Attendance Permission.
#
# **Employee → Atasan Langsung → HR**, dan tiga meja itu bawaan, bukan
# kebijakan: spesifikasinya menyebut rantai ini sebagai rekomendasi
# default dan menyebut dengan jelas bahwa perusahaan lain boleh berhenti
# di atasan langsung atau menambah Kepala Departemen di tengah. Yang
# mengaturnya layar Workflow Definition, bukan kode — karena itu tidak
# ada satu baris pun di modul izin yang mengasumsikan jumlah mejanya.
#
# Meja pertama punya cadangan HR-ADMIN, berbeda dengan alur roster:
# izin diajukan siapa saja termasuk pegawai yang `reports_to`-nya belum
# diisi, dan izin datang terlambat yang tertahan seminggu karena data
# organisasi belum rapi tidak akan pernah dipakai orang — mereka
# berhenti mengajukannya dan pengecualiannya kembali jadi keterlambatan
# tanpa penjelasan.
ATTENDANCE_PERMISSION_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Atasan Langsung)",
        "approver_type": ApproverType.MANAGER,
        "level": 1,
        "fallback_role": "HR-ADMIN",
    },
    {
        "sequence": 2,
        "name": "Verified By (HR)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-ADMIN",
        # Per-lokasi, dan **role-nya tetap `HR-ADMIN`** — satu meja
        # melayani kantor pusat maupun site.
        #
        # Sebelumnya se-company, dengan alasan "meja per-lokasi akan
        # kosong di site yang belum punya admin HR sendiri". UAT browser
        # 8 Sep 2026 membuktikan harganya: izin Bimo Nugroho (Jakarta
        # HO) memunculkan **dua** candidate — HR HO dan HR site — lalu
        # yang site ditandai SKIPPED. Bukan ANY-ONE yang salah; yang
        # salah orangnya tidak pernah berwenang sejak awal.
        #
        # Yang membuat satu meja cukup untuk dua-duanya: HR site dan HR
        # kantor pusat memang memegang **kode role yang sama**
        # (`demo_workforce.py` → USERS), dan yang memisahkan mereka
        # penempatannya. Jadi `location` menyaring ke orang yang tepat
        # di kedua sisi tanpa alur kedua dan tanpa role kedua.
        #
        # Nilai ini sudah lebih dulu diubah tangan di tenant `demo`
        # lewat layar Workflow. Seed dan layar sempat berbeda, dan
        # `_write()` memakai `update_or_create(defaults=…)` — jadi
        # `seed_workflows` berikutnya akan mengembalikannya ke
        # `company` dan membatalkan perbaikan itu **tanpa pesan apa
        # pun**. Barisnya disamakan di sini supaya keduanya berhenti
        # saling membatalkan.
        "approver_scope": ApproverScope.LOCATION,
        # Jaring pengaman untuk lokasi yang memang belum punya HR Admin.
        # Se-company dan sengaja: melebarnya tercatat sebagai
        # `HR_MANAGER_FALLBACK` di jejak dokumen, bukan diam.
        "fallback_role": "HR-MANAGER",
    },
]


# Jenis lokasi yang berarti "lapangan": di sinilah roster, travel
# request, dan meja KTT masuk akal. Diambil dari master `LocationType`
# yang memang sudah ada dan sudah dipakai layar Locations.
FIELD_LOCATION_TYPES = ["MINE", "PROJECT", "PORT"]

OFFICE_LOCATION_TYPES = ["HO", "OFFICE"]


# Payroll Run.
#
# **Seluruh mejanya bertipe Role**, dan itu bukan pilihan gaya:
# satu run mewakili ratusan pegawai, jadi "atasan langsung" tidak
# menunjuk siapa pun. `PayrollRunService.assert_definition_supported`
# menolak alur payroll yang memuat meja per-pegawai, dengan alasan yang
# sama seperti Roster Setup.
#
# Dua meja, bukan satu: HR menyatakan angkanya benar, Finance
# menyatakan uangnya tersedia. Menggabungkannya membuat dua keputusan
# yang berbeda diambil satu tanda tangan.
PAYROLL_RUN_STEPS = [
    {
        "sequence": 1,
        "name": "Reviewed By (HR Manager)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "HR-MANAGER",
        "approver_scope": ApproverScope.COMPANY,
        "fallback_role": None,
    },
    {
        "sequence": 2,
        "name": "Approved By (Finance Manager)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "FINANCE-MANAGER",
        "approver_scope": ApproverScope.COMPANY,
        # Tanpa cadangan. Payroll yang terbit tanpa satu pun tanda
        # tangan keuangan adalah uang yang keluar tanpa yang
        # menganggarkannya tahu; kalau company-nya belum punya Finance
        # Manager, itu yang harus diisi.
        "fallback_role": None,
    },
]


# ----------------------------------------------------------------------
# Jurnal umum
# ----------------------------------------------------------------------
#
# **Satu meja saja, dan itu disengaja.** Dua hal yang biasa diminta —
# "jurnal di atas sekian butuh direktur", "jurnal site lewat HO dulu" —
# keduanya bisa disusun dari layar Workflow Definitions tanpa satu baris
# kode: yang pertama lewat `WorkflowStep.condition` yang membaca
# `amount` di konteks, yang kedua lewat alur kedua yang bercakupan
# company. Menuliskan keduanya di seed berarti menanam ambang rupiah dan
# nama role di dalam kode — persis yang §17 larang.
#
# Konteks yang dibekukan saat pengajuan sudah membawa `amount`,
# `journal_type`, `line_count`, dan `source_module`
# (`JournalService.workflow_context`), jadi syarat yang menyebut
# keempatnya bisa ditulis orang keuangan dari layar.
JOURNAL_STEPS = [
    {
        "sequence": 1,
        "name": "Approved By (Finance Manager)",
        "approver_type": ApproverType.ROLE,
        "approver_role": "FINANCE-MANAGER",
        # Company, bukan location: jurnal tidak punya pegawai subjek,
        # dan barisnya boleh menyebut beberapa site sekaligus. Meja yang
        # dicari per-site tidak akan pernah menemukan siapa pun untuk
        # dokumen semacam itu.
        "approver_scope": ApproverScope.COMPANY,
        # Tanpa cadangan. Jurnal yang terbit tanpa satu pun tanda tangan
        # keuangan adalah angka yang masuk buku besar tanpa ada yang
        # memeriksanya; kalau company-nya belum punya Finance Manager,
        # itu yang harus diisi.
        "fallback_role": None,
    },
]


def _operating_company():
    """
    Perusahaan yang punya lapangan — itu yang alur site-nya diseed.

    **Tanpa ini, tenant berisi lebih dari satu company memilih lokasi
    yang salah, dan gagalnya jauh dari sebabnya.** Versi sebelumnya
    mencari "kantor pusat" dan "lokasi selain kantor pusat" di seluruh
    tenant sekaligus: begitu ada tiga perusahaan yang masing-masing
    punya kantor pusat, satu di antaranya terpilih sebagai kantor pusat
    dan **kantor pusat perusahaan lain** jadi kandidat pertama "lokasi
    site" — kodenya kebetulan lebih kecil daripada nama site mana pun.
    Akibatnya alur site menempel ke Jakarta, dan pegawai kantor yang
    mengajukan cuti ditagih tanda tangan Kepala Teknik Tambang.

    Yang dipilih perusahaan dengan lokasi lapangan terbanyak. Kalau
    tidak ada satu pun, tenant ini memang tidak punya operasi lapangan
    dan alur site-nya dilewati.
    """
    counts: dict[int, int] = {}

    rows = (
        Location.objects
        .filter(
            is_deleted=False,
            location_type__code__in=FIELD_LOCATION_TYPES,
        )
        .values_list("company_id", flat=True)
    )

    for company_id in rows:
        counts[company_id] = counts.get(company_id, 0) + 1

    if not counts:
        return None

    # Urutan pemenangnya ditentukan jumlah lokasi lapangan, lalu id —
    # dua perusahaan berimbang harus menghasilkan pilihan yang sama
    # setiap kali seed dijalankan.
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))[0][0]


def _head_office(company_id=None):
    """
    Lokasi kantor pusat di master tenant ini.

    Dicari berjenjang karena penamaannya berbeda-beda: jenis lokasi
    dulu (master `LocationType` sudah punya `HO`), lalu kode persis,
    lalu "head office" di namanya, lalu token "HO" berdiri sendiri.
    Yang terakhir sengaja per token, bukan `icontains="ho"` — substring
    itu ikut mencocokkan "Sorong" dan "Ternate", dan alur Head Office
    yang menempel ke lokasi site adalah kesalahan yang tidak berbunyi
    sampai ada pegawai site yang cutinya lewat jalur HO.

    `company_id` mempersempitnya ke perusahaan yang punya operasi
    lapangan. Kantor pusat perusahaan induk yang tidak berpegawai bukan
    tempat alur cuti kantor seharusnya menempel.
    """
    def scoped(queryset):
        if company_id is not None:
            return queryset.filter(company_id=company_id)

        return queryset

    location = (
        scoped(
            Location.objects.filter(
                is_deleted=False,
                location_type__code="HO",
            )
        )
        .order_by("code")
        .first()
    )

    if location is not None:
        return location

    for code in HEAD_OFFICE_CODES:
        location = (
            scoped(Location.objects.filter(code__iexact=code, is_deleted=False))
            .first()
        )

        if location is not None:
            return location

    location = (
        scoped(
            Location.objects.filter(
                name__icontains="head office",
                is_deleted=False,
            )
        )
        .first()
    )

    if location is not None:
        return location

    for candidate in scoped(Location.objects.filter(is_deleted=False)):
        tokens = set(
            candidate.code.replace("-", " ").upper().split()
        ) | set(
            candidate.name.replace("-", " ").upper().split()
        )

        if "HO" in tokens:
            return candidate

    return None


def _site_location(head_office, company_id=None):
    """
    Lokasi lapangan tempat alur site berlaku.

    Yang dicari **jenis lokasinya**, bukan "yang bukan kantor pusat".
    Aturan lama itu benar selama tenant cuma punya satu perusahaan;
    begitu ada dua, kantor perusahaan kedua lolos sebagai "bukan kantor
    pusat" dan alur site menempel padanya — lihat `_operating_company`.
    """
    queryset = Location.objects.filter(
        is_deleted=False,
        location_type__code__in=FIELD_LOCATION_TYPES,
    )

    if company_id is not None:
        queryset = queryset.filter(company_id=company_id)

    if head_office is not None:
        queryset = queryset.exclude(pk=head_office.pk)

    # "Default Location" adalah baris bawaan tiap company, bukan lokasi
    # kerja sungguhan — memilihnya membuat alur site berlaku untuk
    # pegawai yang lokasinya belum diisi.
    queryset = queryset.exclude(code__iexact="DEFAULT")

    # Tambang dan proyek didahulukan atas pelabuhan: yang menjalani
    # roster dan mengajukan travel request adalah orang yang tinggal di
    # site, dan pelabuhan lazimnya titik singgah, bukan tempat orang
    # menjalani blok kerjanya.
    for type_code in FIELD_LOCATION_TYPES:
        location = (
            queryset
            .filter(location_type__code=type_code)
            .order_by("code")
            .first()
        )

        if location is not None:
            return location

    return None


def _write(config, roles) -> tuple[WorkflowDefinition, int]:
    steps = config.pop("steps")

    # Dicocokkan lewat **`code`**, bukan lewat cakupannya.
    #
    # Dulu kuncinya (module, document_type, company, branch, location,
    # employee_group, version), dan itu pecah begitu cakupan sebuah alur
    # dibetulkan: baris lama tidak lagi cocok, seed mencoba membuat yang
    # baru, lalu ditolak `uniq_active_workflow_definition_code` — jadi
    # justru perbaikan cakupan yang paling mustahil dijalankan. `code`
    # yang unik dan `code` yang stabil; cakupannya yang boleh berubah.
    definition, _ = WorkflowDefinition.objects.update_or_create(
        code=config["code"],
        defaults={
            "module": config["module"],
            "document_type": config["document_type"],
            "company": None,
            "branch": None,
            "location": config.get("location"),
            "employee_group": None,
            "version": 1,
            "name": config["name"],
            "description": config["description"],
            "status": WorkflowStatus.ACTIVE,
            "is_active": True,
            "is_deleted": False,
        },
    )

    # Dikembalikan supaya seed-nya tetap aman dipanggil dua kali dari
    # proses yang sama — `pop` di atas mengosongkan konstanta modul
    # kalau tidak dipulihkan.
    config["steps"] = steps

    for step in steps:
        row, _ = WorkflowStep.objects.update_or_create(
            definition=definition,
            sequence=step["sequence"],
            defaults={
                "name": step["name"],
                "approver_type": step["approver_type"],
                "level": step.get("level", 1),
                "approver_role": roles.get(step.get("approver_role")),
                "approver_scope": step.get(
                    "approver_scope",
                    ApproverScope.COMPANY,
                ),
                "fallback_role": roles.get(step.get("fallback_role")),
                "approval_mode": step.get(
                    "approval_mode",
                    ApprovalMode.ANY,
                ),
                "minimum_approvals": step.get("minimum_approvals", 1),
                "is_required": step.get("is_required", True),
                "condition": step.get("condition", {}),
                "is_active": True,
                "is_deleted": False,
            },
        )

        _seed_fallbacks(row, step.get("fallbacks") or [], roles)

    _retire_extra_steps(definition, [step["sequence"] for step in steps])

    return definition, len(steps)


def _retire_extra_steps(definition, sequences) -> None:
    """
    Menonaktifkan step yang sudah tidak ada lagi di daftar seed.

    Tanpa ini seed hanya idempoten selama rantainya tidak pernah
    **memendek**: `update_or_create` per `sequence` menulis ulang yang
    disebut dan tidak menyentuh sisanya, jadi rantai yang dipangkas dari
    enam meja jadi empat meninggalkan dua meja lama yang tetap aktif dan
    tetap ikut dibangun saat dokumen diajukan. Alur yang berjalan
    berbeda dari alur yang tertulis di seed adalah selisih yang tidak
    akan pernah ada yang mencurigainya — keduanya "sudah diseed".

    **Soft delete, bukan hard.** `WorkflowApproval.step` ber-`PROTECT`,
    jadi menghapus step yang pernah dipakai satu dokumen pun akan
    menggagalkan seluruh seed; dan kotak tanda tangan di dokumen lama
    harus tetap bisa dibaca. `_build_approvals` menyaring
    `is_deleted=False, is_active=True`, jadi menandainya sudah cukup
    untuk mengeluarkannya dari pengajuan berikutnya.
    """
    definition.steps.exclude(sequence__in=sequences).update(
        is_active=False,
        is_deleted=True,
    )


def _seed_fallbacks(step, chain, roles) -> None:
    """
    Cadangan berjenjang milik satu step.

    Dihapus lebih dulu, bukan di-`update_or_create` per baris: rantai
    yang dipendekkan di kode akan meninggalkan tingkat lama yang tetap
    dicoba, dan urutan pencarian yang berbeda dari yang tertulis di seed
    adalah selisih yang tidak akan pernah ada yang mencurigainya. Hard
    delete, karena baris bertanda terhapus tetap menempati kunci unik
    `(step, sequence)` dan justru menggagalkan penulisan berikutnya.
    """
    step.fallbacks.all().delete()

    for index, (code, scope) in enumerate(chain, start=1):
        role = roles.get(code)

        if role is None:
            continue

        WorkflowStepFallback.objects.create(
            step=step,
            sequence=index,
            role=role,
            approver_scope=scope,
        )


@transaction.atomic
def seed() -> dict:
    roles = {}

    for code, name in REQUIRED_ROLES:
        role, _ = Role.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "description": f"Diseed untuk alur approval ({name}).",
                "is_deleted": False,
            },
        )

        roles[code] = role

    # Perusahaan yang punya lapangan dipilih lebih dulu, lalu kedua
    # lokasinya dicari **di dalamnya**. Kalau tidak ada satu pun operasi
    # lapangan, pencariannya melebar ke seluruh tenant seperti dulu —
    # tenant yang isinya kantor semua tetap dapat alur HO-nya.
    operating_company = _operating_company()

    head_office = _head_office(operating_company)

    configs = [
        {
            "module": "hr",
            "document_type": "leave_request",
            "code": "HR-LEAVE-STD",
            "name": "Cuti — Standar",
            "description": (
                "Atasan langsung → HR. Berlaku untuk semua pegawai "
                "yang tidak punya alur lebih khusus."
            ),
            "location": None,
            "steps": LEAVE_STEPS,
        },
        {
            "module": "hr",
            "document_type": "travel_request",
            "code": "HR-TRAVEL-REQUEST",
            "name": "Travel Request — Standar",
            "description": (
                "Atasan langsung → Kepala Departemen → HR. Mengikuti "
                "kotak tanda tangan di formulir Travel Request."
            ),
            "location": None,
            "steps": TRAVEL_REQUEST_STEPS,
        },
        {
            "module": "hr",
            "document_type": "visitor_request",
            "code": "HR-VISITOR-REQUEST",
            "name": "Visitor Request — Standar",
            "description": (
                "Atasan langsung → HRGA. Sengaja pendek: tamu yang "
                "datang rapat sejam tidak boleh menunggu empat tanda "
                "tangan, dan alur yang terlalu panjang akan dilewati "
                "orang."
            ),
            "location": None,
            "steps": VISITOR_REQUEST_STEPS,
        },
        {
            "module": "hr",
            "document_type": "business_trip",
            "code": "HR-BUSINESS-TRIP",
            "name": "Business Trip — Standar",
            "description": (
                "Atasan langsung → HRGA. Atasan menilai kebutuhan "
                "bisnisnya, HRGA menilai kebijakan perjalanan dan "
                "administrasinya. Belum ada meja Finance."
            ),
            "location": None,
            "steps": BUSINESS_TRIP_STEPS,
        },
        {
            "module": "hr",
            "document_type": "attendance_permission",
            "code": "HR-ATT-PERMISSION",
            "name": "Attendance Permission — Standar",
            "description": (
                "Atasan langsung → HR. Rantainya sengaja pendek: izin "
                "datang terlambat yang tertahan seminggu tidak akan "
                "pernah dipakai orang. Perusahaan yang butuh meja "
                "tambahan menambahnya di layar ini, bukan di kode."
            ),
            "location": None,
            "steps": ATTENDANCE_PERMISSION_STEPS,
        },
        {
            "module": "finance",
            "document_type": "journal",
            "code": "FIN-JOURNAL-STD",
            "name": "Journal — Standar",
            "description": (
                "Satu meja: Finance Manager. Ambang nilai dan meja "
                "tambahan disusun dari layar ini, bukan di kode — "
                "konteksnya sudah membawa `amount`, `journal_type`, dan "
                "`source_module` supaya syarat step bisa menyebutnya."
            ),
            "location": None,
            "steps": JOURNAL_STEPS,
        },
        {
            "module": "payroll",
            "document_type": "payroll_run",
            "code": "PAY-RUN-STD",
            "name": "Payroll Run — Standar",
            "description": (
                "HR Manager → Finance Manager. Seluruh mejanya bertipe "
                "Role karena satu run mewakili banyak pegawai."
            ),
            "location": None,
            "steps": PAYROLL_RUN_STEPS,
        },
        {
            "module": "hr",
            "document_type": "employee_action",
            "code": "HR-EMPLOYEE-ACTION",
            "name": "Employee Action — Standar",
            "description": (
                "Atasan langsung → HR → HR Manager (untuk perubahan "
                "jenis kepegawaian, gaji, jabatan, dan pemutusan). "
                "Melayani seluruh jenis Employee Action; yang "
                "membedakan tinggi mejanya adalah `action_type`."
            ),
            "location": None,
            "steps": EMPLOYEE_ACTION_STEPS,
        },
        {
            "module": "hr",
            "document_type": "roster_setup",
            "code": "HR-ROSTER-SETUP",
            "name": "Roster Setup — Standar",
            "description": (
                "Dibuat & diajukan Admin Department / Admin Section → "
                "HR Admin Site → Atasan Langsung → HR Manager Site → "
                "commit otomatis. Meja atasan langsung mensyaratkan "
                "seluruh baris dokumen punya atasan yang sama; kalau "
                "berbeda, dokumennya dipecah per atasan."
            ),
            "location": None,
            "steps": ROSTER_SETUP_STEPS,
        },
        {
            "module": "hr",
            "document_type": "roster_adjustment",
            "code": "HR-ROSTER-ADJUSTMENT",
            "name": "Roster Adjustment — Standar",
            "description": (
                "Atasan Langsung → Admin HR Site → HR Manager (hanya "
                "yang menyentuh rotation credit). Menggeser tanggal dua "
                "hari tidak perlu naik ke meja yang sama dengan "
                "menerbitkan hak baru."
            ),
            "location": None,
            "steps": ROSTER_ADJUSTMENT_STEPS,
        },
    ]

    skipped = []

    # Alur perjalanan khusus site. Dicari lokasi non-HO yang ada di
    # master; kalau tenant baru punya satu lokasi (HO), alur ini
    # dilewati dengan pesan — bukan dibuatkan lokasi karangan.
    site = _site_location(head_office, operating_company)

    if site is not None:
        description = (
            "Admin Section (cadangan: Admin Department) → HR Admin "
            "Site → Atasan Langsung → HR Manager Site → KTT Site → "
            "HRGA. Menang atas alur standar karena menyebut lokasi."
        )

        # Dua dokumen, meja yang sama. Pegawai site yang pulang cuti
        # tetap harus dibelikan tiket, jadi Cuti melewati rantai yang
        # sama persis dengan Travel Request — bedanya cuma jenis
        # dokumennya. `steps` disalin, bukan dibagi: `_write` menulis
        # per definisi, dan dua definisi yang menunjuk list yang sama
        # tetap aman, tapi menyalinnya membuat perubahan salah satu
        # tidak diam-diam menyeret yang lain.
        for document_type, code, name in [
            ("travel_request", "HR-TR-SITE", "Travel Request — Site"),
            ("leave_request", "HR-LEAVE-SITE", "Cuti — Site"),
        ]:
            configs.append(
                {
                    "module": "hr",
                    "document_type": document_type,
                    "code": code,
                    "name": name,
                    "description": description,
                    "location": site,
                    "steps": list(SITE_STEPS),
                },
            )
    else:
        skipped.append(
            "HR-TR-SITE / HR-LEAVE-SITE — belum ada lokasi kerja selain "
            "kantor pusat di master."
        )

    if head_office is not None:
        configs.append(
            {
                "module": "hr",
                "document_type": "leave_request",
                "code": "HR-HO-LEAVE",
                "name": "Cuti — Head Office",
                "description": (
                    "Atasan langsung → HR Manager. Dua meja, dan "
                    "seluruh cuti kantor pusat lewat keduanya, berapa "
                    "pun harinya. Menang atas alur standar karena "
                    "menyebut lokasi."
                ),
                "location": head_office,
                "steps": HEAD_OFFICE_LEAVE_STEPS,
            },
        )
    else:
        skipped.append(
            "HR-HO-LEAVE — lokasi Head Office tidak ketemu di master "
            f"(dicari kode {', '.join(HEAD_OFFICE_CODES)} atau nama "
            "mengandung 'head office')."
        )

    definitions = 0
    steps = 0

    for config in configs:
        _, count = _write(config, roles)

        definitions += 1
        steps += count

    return {
        "roles": len(roles),
        "definitions": definitions,
        "steps": steps,
        "skipped": skipped,
    }
