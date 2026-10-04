"""
Isi panduan bawaan Help Center.

Ditulis di sini, bukan di file Markdown, karena artikelnya **memang
milik tenant**: yang diseed cuma titik awal, dan tiap klien akan
menambahkan panduan internalnya sendiri lewat layar Help Articles.
Yang tidak boleh terjadi adalah seed menimpa tulisan orang — karena
itu pencocokannya lewat `code` dan artikel yang **sudah disunting
manusia** (`updated_by` terisi) dilewati, bukan ditulis ulang.

Bahasanya Indonesia karena pembacanya pengguna akhir; label UI di
dalamnya tetap ditulis persis seperti yang tampil di layar (Inggris),
sesuai konvensi penamaan di repo ini. Panduan yang menyebut "tombol
Simpan" untuk tombol yang berbunyi "Save" membuat pembacanya mencari
tombol yang tidak ada.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.helpcenter.models import (
    HelpArticle,
    HelpArticleStatus,
    HelpCategory,
)
from apps.helpcenter.services import HelpArticleService


CATEGORIES = [
    {
        "code": "GETTING-STARTED",
        "name": "Memulai",
        "description": "Langkah pertama setelah akun Anda dibuat.",
        "icon": "i-lucide-rocket",
        "module": "",
        "sort_order": 10,
    },
    {
        "code": "HR-SELF-SERVICE",
        "name": "Cuti & Kehadiran",
        "description": "Mengajukan cuti, membaca saldo, dan memeriksa absensi.",
        "icon": "i-lucide-calendar-check",
        "module": "hr",
        "sort_order": 20,
    },
    {
        "code": "HR-TRAVEL-ROSTER",
        "name": "Perjalanan & Roster",
        "description": "Travel Request dan jadwal kerja pegawai site.",
        "icon": "i-lucide-plane",
        "module": "hr",
        "sort_order": 30,
    },
    {
        "code": "APPROVAL",
        "name": "Persetujuan",
        "description": "Kotak masuk approver dan pelacakan pengajuan.",
        "icon": "i-lucide-check-check",
        "module": "workflow",
        "sort_order": 40,
    },
    {
        "code": "HR-ADMIN",
        "name": "Untuk Admin HR",
        "description": "Mengelola data pegawai, import, dan roster site.",
        "icon": "i-lucide-users",
        "module": "hr",
        "sort_order": 50,
    },
    {
        "code": "TROUBLESHOOTING",
        "name": "Kendala Umum",
        "description": "Jawaban untuk hal yang paling sering ditanyakan.",
        "icon": "i-lucide-life-buoy",
        "module": "",
        "sort_order": 90,
    },
]


ARTICLES = [
    # ------------------------------------------------------------------
    # Memulai
    # ------------------------------------------------------------------
    {
        "code": "GS-LOGIN",
        "category": "GETTING-STARTED",
        "title": "Masuk ke sistem untuk pertama kali",
        "summary": (
            "Cara login, mengganti password bawaan, dan apa yang harus "
            "dilakukan kalau akun Anda terkunci."
        ),
        "icon": "i-lucide-log-in",
        "keywords": "login, masuk, password, sandi, lupa password",
        "route_prefix": "",
        "sort_order": 10,
        "content": """
<p>Akun Anda dibuat oleh admin perusahaan. Anda akan menerima
<strong>username</strong> dan <strong>password sementara</strong> —
keduanya harus diganti sendiri setelah masuk pertama kali.</p>

<h3>Langkah masuk</h3>
<ol>
  <li>Buka alamat ERP perusahaan Anda di browser.</li>
  <li>Isi <strong>Username</strong> dan <strong>Password</strong>.</li>
  <li>Klik <strong>Sign in</strong>.</li>
</ol>

<h3>Mengganti password</h3>
<ol>
  <li>Klik nama Anda di bagian bawah sidebar kiri.</li>
  <li>Pilih <strong>Account</strong>.</li>
  <li>Isi password lama dan password baru, lalu simpan.</li>
</ol>

<p>Gantilah password sementara pada hari pertama. Password itu
diketahui orang yang membuat akun Anda, dan seluruh tindakan yang
dilakukan lewat akun Anda tercatat atas nama Anda di jejak audit.</p>

<h3>Kalau tidak bisa masuk</h3>
<ul>
  <li>Pastikan username diketik tanpa spasi di depan atau belakang.</li>
  <li>Password membedakan huruf besar dan kecil.</li>
  <li>Kalau tetap gagal, hubungi admin perusahaan Anda — sistem ini
  belum punya fitur reset password mandiri, jadi password baru harus
  dibuatkan admin.</li>
</ul>
""",
    },
    {
        "code": "GS-HOME",
        "category": "GETTING-STARTED",
        "title": "Mengatur tampilan beranda",
        "summary": (
            "Menyusun ulang widget, memilih aplikasi favorit, dan "
            "menentukan pintasan menu yang muncul di halaman depan."
        ),
        "icon": "i-lucide-layout-dashboard",
        "keywords": "beranda, home, dashboard, widget, favorit, pintasan",
        "route_prefix": "/",
        "sort_order": 20,
        "content": """
<p>Beranda adalah halaman pertama yang terbuka setelah login. Isinya
bisa Anda susun sendiri, dan susunannya tersimpan di akun Anda —
tidak memengaruhi tampilan orang lain.</p>

<h3>Masuk ke mode penyusunan</h3>
<ol>
  <li>Klik tombol <strong>Customize</strong> di kanan atas beranda.</li>
  <li>Tampilan berubah: setiap bagian kini punya tombol pengatur.</li>
  <li>Setelah selesai, klik <strong>Save</strong>. Satu tombol itu
  menyimpan seluruh susunan sekaligus.</li>
</ol>

<h3>Tiga hal yang bisa diatur</h3>
<ul>
  <li><strong>Widget</strong> — geser naik/turun dengan tombol panah,
  sembunyikan dengan tombol mata, lipat dengan tombol panah kecil di
  kepala kartunya.</li>
  <li><strong>Applications</strong> — kartu modul. Klik bintang untuk
  memilih mana yang tampil. Modul yang belum punya halaman ditandai
  <em>Coming soon</em> dan tidak bisa dipilih.</li>
  <li><strong>Favorite Menus</strong> — pintasan ke layar yang sering
  Anda buka. Gunakan kotak cari di mode Customize kalau daftarnya
  panjang.</li>
</ul>

<h3>Yang perlu diketahui</h3>
<ul>
  <li>Widget yang disembunyikan tetap terlihat (pudar) selama mode
  Customize, supaya bisa dimunculkan lagi.</li>
  <li>Kalau Anda belum pernah menyusun apa pun, yang tampil adalah
  susunan bawaan — dan susunan bawaan itu ikut berubah kalau
  perusahaan menambah modul baru.</li>
  <li>Menekan <strong>Reset</strong> mengembalikan beranda ke susunan
  bawaan, bukan mengosongkannya.</li>
</ul>
""",
    },
    {
        "code": "GS-PROFILE",
        "category": "GETTING-STARTED",
        "title": "Memperbarui profil Anda",
        "summary": (
            "Membetulkan nama dan email sendiri tanpa harus meminta "
            "bantuan admin."
        ),
        "icon": "i-lucide-user-round-cog",
        "keywords": "profil, nama, email, akun, ubah data",
        "route_prefix": "/settings/profile",
        "sort_order": 30,
        "content": """
<p>Nama yang salah ketik saat akun dibuat bisa Anda betulkan sendiri.</p>

<ol>
  <li>Klik nama Anda di bagian bawah sidebar.</li>
  <li>Pilih <strong>Account</strong>.</li>
  <li>Ubah <strong>First name</strong>, <strong>Last name</strong>,
  atau <strong>Email</strong>.</li>
  <li>Klik <strong>Update profile</strong>.</li>
</ol>

<h3>Yang tidak bisa diubah sendiri</h3>
<ul>
  <li><strong>Username</strong> — dipakai untuk login, tercetak di
  jejak audit, dan dirujuk dokumen yang sudah berjalan.</li>
  <li><strong>Role dan hak akses</strong> — diatur admin keamanan.</li>
  <li><strong>Data kepegawaian</strong> (jabatan, departemen, tanggal
  masuk) — itu milik kartu pegawai, bukan profil akun. Perubahannya
  lewat HR.</li>
</ul>

<p>Email harus unik. Kalau muncul pesan bahwa email sudah dipakai,
berarti ada akun lain dengan email yang sama — hubungi admin.</p>
""",
    },

    # ------------------------------------------------------------------
    # Cuti & kehadiran
    # ------------------------------------------------------------------
    {
        "code": "HR-LEAVE-REQUEST",
        "category": "HR-SELF-SERVICE",
        "title": "Mengajukan cuti",
        "summary": (
            "Membuat pengajuan cuti, mengirimkannya untuk disetujui, "
            "dan menariknya kembali kalau ada yang salah."
        ),
        "icon": "i-lucide-clock-3",
        "keywords": "cuti, ijin, izin, leave, pengajuan, libur",
        "route_prefix": "/hr/leave",
        "sort_order": 10,
        "content": """
<h3>Membuat pengajuan</h3>
<ol>
  <li>Buka menu <strong>HR &rsaquo; Leave</strong>.</li>
  <li>Klik <strong>Add</strong>.</li>
  <li>Isi <strong>Leave Type</strong>, <strong>Start Date</strong>, dan
  <strong>End Date</strong>.</li>
  <li>Tulis alasannya di <strong>Reason</strong> — ini yang dibaca
  atasan Anda saat memutuskan.</li>
  <li>Klik <strong>Save</strong>. Dokumen tersimpan sebagai
  <strong>Draft</strong> dan belum dikirim ke siapa pun.</li>
  <li>Buka kembali dokumennya, lalu klik <strong>Submit</strong>.</li>
</ol>

<p>Selama masih Draft, dokumen bisa disunting bebas. Setelah Submit,
dokumen terkunci — untuk mengubahnya, tarik dulu dengan tombol
<strong>Withdraw</strong>.</p>

<h3>Berapa hari yang terpotong dari saldo</h3>
<p>Kolom <strong>Total Days</strong> terisi otomatis, dan angkanya
belum tentu sama dengan jumlah hari di kalender:</p>
<ul>
  <li><strong>Pegawai kantor</strong> — Sabtu, Minggu, dan hari libur
  nasional tidak dihitung. Cuti 14–18 Agustus bisa jadi hanya memotong
  2 hari.</li>
  <li><strong>Pegawai site</strong> — yang dihitung blok kerja pada
  roster Anda. Akhir pekan dan tanggal merah tidak dikecualikan,
  karena roster Anda sendiri yang jadi kalendernya.</li>
</ul>

<p><strong>Total Days 0 itu sah.</strong> Kalau tanggal cuti Anda
jatuh seluruhnya di blok off, tidak ada hari kerja yang hilang — jadi
tidak ada saldo yang terpotong.</p>

<h3>Saldo baru berkurang setelah disetujui</h3>
<p>Pengajuan yang masih menunggu keputusan belum mengurangi saldo Anda.
Kalau ditolak, tidak ada yang perlu dikembalikan.</p>

<h3>Tanggalnya bentrok</h3>
<p>Sistem menolak pengajuan yang tanggalnya beririsan dengan cuti lain
yang sudah tercatat, disetujui, atau sedang diajukan — dan pesannya
menyebut nomor dokumen yang bentrok. Yang berstatus Draft, Rejected,
atau Cancelled tidak menghalangi.</p>
""",
    },
    {
        "code": "HR-LEAVE-BALANCE",
        "category": "HR-SELF-SERVICE",
        "title": "Membaca saldo cuti",
        "summary": (
            "Arti kolom Entitlement, Used, Adjustment, dan Remaining — "
            "serta kenapa saldo Anda bisa nol."
        ),
        "icon": "i-lucide-wallet-minimal",
        "keywords": "saldo, sisa cuti, jatah, kuota, balance",
        "route_prefix": "/hr/leave-balances",
        "sort_order": 20,
        "content": """
<p>Buka <strong>HR &rsaquo; Leave Balance</strong>. Satu baris = satu
jenis cuti untuk satu tahun.</p>

<table>
  <thead>
    <tr><th>Kolom</th><th>Artinya</th></tr>
  </thead>
  <tbody>
    <tr><td>Entitlement</td><td>Jatah yang terbit dari kebijakan
    perusahaan.</td></tr>
    <tr><td>Used</td><td>Terpakai. Dijumlahkan ulang dari catatan cuti
    yang sudah disetujui atau tercatat.</td></tr>
    <tr><td>Adjustment</td><td>Koreksi manual dari HR — tambahan atau
    pengurangan di luar aturan.</td></tr>
    <tr><td>Remaining</td><td>Entitlement + Adjustment − Used.</td></tr>
  </tbody>
</table>

<h3>Kenapa saldo saya nol?</h3>
<p>Kolom keterangan pada baris saldo menyebutkan alasannya, dan
biasanya salah satu dari ini:</p>
<ul>
  <li><strong>Belum genap masa tunggu.</strong> Cuti tahunan lazimnya
  baru terbit setelah 12 bulan bekerja. Keterangannya menyebut tanggal
  Anda mulai berhak.</li>
  <li><strong>Tanggal masuk belum diisi</strong> di data kepegawaian
  Anda — hubungi HR.</li>
  <li><strong>Jenis cuti itu memang tidak berkuota.</strong> Cuti yang
  tidak punya kebijakan jatah tidak menghasilkan baris saldo sama
  sekali; cutinya tetap bisa diambil dan dicatat.</li>
</ul>

<p>Saldo boleh menjadi minus. Sistem tidak memblokir pengambilan cuti
melebihi sisa — pengendaliannya ada pada persetujuan atasan.</p>
""",
    },
    # ------------------------------------------------------------------
    # Cuti — tiga artikel di bawah ini DRAFT.
    #
    # Isinya menjelaskan sisa cuti tahun lalu, cuti dibayar di muka, dan
    # perhitungan hak saat berhenti bekerja: rancangannya ada di
    # `docs/03-modules/hr/Leave-Balance-Proposal.md`, kodenya belum.
    # Diseed sekarang supaya tulisannya sudah duduk di tenant dan bisa
    # direview dari layar Help Articles; ubah statusnya jadi Published
    # begitu fiturnya rilis.
    # ------------------------------------------------------------------
    {
        "code": "HR-LEAVE-CARRY-OVER",
        "category": "HR-SELF-SERVICE",
        "title": "Sisa cuti tahun lalu: dibawa, masa berlakunya, dan kapan hangus",
        "summary": (
            "Sisa cuti yang tidak habis tahun lalu dibawa ke tahun ini "
            "dengan batas waktu pemakaian. Yang lewat batas itu hangus "
            "— tapi angkanya tidak dihapus."
        ),
        "icon": "i-lucide-calendar-clock",
        "keywords": (
            "carry over, sisa cuti, hangus, kadaluarsa, gugur, bawaan, "
            "tahun lalu"
        ),
        "route_prefix": "/hr/leave-balances",
        "sort_order": 25,
        "content": """
<p>Cuti yang tidak Anda habiskan tahun lalu <strong>tidak langsung
hilang</strong> pada 1 Januari. Sisanya dibawa ke tahun berjalan
sebagai <strong>Carried Over</strong>, dengan satu syarat: ada batas
waktu pemakaiannya.</p>

<h3>Membaca kartu cuti Anda</h3>

<p>Buka <strong>HR &rsaquo; Leave Balance</strong>. Baris tahun
berjalan sekarang punya kolom tambahan:</p>

<table>
  <thead>
    <tr><th>Kolom</th><th>Artinya</th></tr>
  </thead>
  <tbody>
    <tr><td>Entitlement</td><td>Jatah tahun ini.</td></tr>
    <tr><td>Carried Over</td><td>Sisa tahun lalu yang dibawa.</td></tr>
    <tr><td>Carry Over Expiry</td><td><strong>Tanggal terakhir</strong>
    sisa bawaan itu masih boleh dipakai.</td></tr>
    <tr><td>Expired</td><td>Bagian bawaan yang sudah lewat tanggal itu
    dan tidak bisa dipakai lagi.</td></tr>
    <tr><td>Remaining</td><td>Yang benar-benar masih bisa Anda
    ambil.</td></tr>
  </tbody>
</table>

<h3>Yang dipakai lebih dulu adalah sisa tahun lalu</h3>

<p>Setiap cuti yang Anda ambil <strong>menggerus sisa bawaan lebih
dulu</strong>, baru jatah tahun ini. Ini menguntungkan Anda: yang punya
tanggal kedaluwarsa dihabiskan duluan, jadi kemungkinan ada yang hangus
jadi sekecil mungkin.</p>

<p>Contoh — jatah 12 hari, bawaan 12 hari, batas 30 Juni:</p>

<ul>
  <li>Anda cuti 8 hari di bulan Februari.</li>
  <li>Kedelapannya diambil dari <strong>bawaan</strong>. Sisa bawaan
  tinggal 4 hari, jatah tahun ini masih utuh 12.</li>
  <li>Kalau sampai 30 Juni 4 hari itu tidak terpakai, keempatnya
  hangus. Jatah 12 hari tahun ini tidak terpengaruh sama sekali.</li>
</ul>

<h3>Anda akan diingatkan sebelum hangus</h3>

<p>Sistem mengirim pemberitahuan menjelang tanggal batas — ke Anda dan
ke atasan langsung Anda. Pemberitahuan terakhir dikirim pada hari
penghangusan, berisi jumlah harinya.</p>

<h3>Yang hangus tidak dihapus dari kartu Anda</h3>

<p>Ini yang paling sering disalahpahami. Hari yang hangus
<strong>tidak bisa diambil sebagai cuti lagi</strong>, tapi angkanya
tetap tercatat di kolom <strong>Expired</strong> — selamanya, per
tahun. Kartu cuti Anda tidak pernah kembali kosong.</p>

<p>Apakah hari yang sudah hangus itu ikut dibayar saat Anda berhenti
bekerja adalah <strong>kebijakan masing-masing perusahaan</strong>.
Ketentuan minimum yang berlaku umum hanya mengganti cuti yang belum
diambil <em>dan belum gugur</em>. Tanyakan ke HR bagaimana kebijakan
di perusahaan Anda — angkanya ada di kartu Anda, jadi bisa dicek
bersama.</p>

<h3>Kenapa ada batas cuti yang boleh dibawa?</h3>

<p>Sebagian perusahaan membatasi jumlah maksimal yang boleh dibawa
(misalnya 6 dari 12 hari). Kelebihannya tidak ikut terbawa dan langsung
tercatat sebagai hangus pada 1 Januari. Batas itu diatur HR per
perusahaan; kalau angka di kartu Anda lebih kecil daripada sisa tahun
lalu, inilah sebabnya.</p>
""",
    },
    {
        "code": "HR-LEAVE-ADVANCE",
        "category": "HR-SELF-SERVICE",
        "title": "Mengajukan cuti saat saldo sudah habis",
        "summary": (
            "Sebagian perusahaan mengizinkan cuti melebihi saldo untuk "
            "keperluan mendadak. Kelebihannya menjadi cuti dibayar di "
            "muka, dan itu punya konsekuensi."
        ),
        "icon": "i-lucide-hand-coins",
        "keywords": (
            "saldo habis, minus, hutang cuti, dibayar di muka, advance, "
            "cuti mendadak, dadakan, darurat"
        ),
        "route_prefix": "/hr/leave",
        "sort_order": 26,
        "content": """
<p>Ada keperluan yang tidak bisa menunggu saldo terisi lagi — keluarga
sakit, musibah, urusan yang tidak bisa diwakilkan. Kalau perusahaan
Anda mengizinkannya, cuti tetap bisa diajukan walau
<strong>Remaining</strong> Anda sudah nol.</p>

<p>Kelebihannya disebut <strong>cuti dibayar di muka</strong>: hari
yang Anda ambil sekarang, tapi jatahnya belum Anda peroleh.</p>

<h3>Apa yang terjadi saat Anda mengajukan</h3>

<ol>
  <li>Isi formulir cuti seperti biasa.</li>
  <li>Kalau jumlah harinya melebihi sisa saldo, muncul
  <strong>peringatan</strong> yang menyebut angkanya — misalnya
  "Melebihi saldo Anda sebanyak 3 hari".</li>
  <li>Anda diminta <strong>mencentang pernyataan persetujuan</strong>
  bahwa kelebihan itu diperhitungkan bila Anda berhenti bekerja.
  Tanpa centang itu, tombol Submit tidak aktif.</li>
  <li>Pengajuannya berjalan lewat <strong>meja persetujuan tambahan</strong>
  — biasanya HR atau atasan yang lebih tinggi. Rantai persetujuannya
  memang lebih panjang daripada cuti biasa.</li>
</ol>

<h3>Ada batasnya, dan batas itu keras</h3>

<p>Perusahaan menetapkan berapa hari maksimal boleh diambil di muka.
Di atas batas itu pengajuan <strong>ditolak sistem</strong>, berapa pun
persetujuan yang Anda punya. Angka batasnya bisa ditanyakan ke HR.</p>

<h3>Bagaimana lunasnya</h3>

<p>Hutang cuti melunasi dirinya sendiri pada pergantian tahun: jatah
tahun depan dipotong lebih dulu sebanyak yang Anda ambil di muka.
Ambil 3 hari di muka tahun ini &rarr; jatah tahun depan efektif 9 dari
12 hari.</p>

<p>Kartu cuti Anda menampilkannya di kolom <strong>Debt Carried In</strong>,
jadi selisihnya bisa dijelaskan — bukan jatah yang tiba-tiba berkurang
tanpa sebab.</p>

<h3>Kalau Anda berhenti sebelum lunas</h3>

<p>Sisanya diperhitungkan dalam penyelesaian akhir. Rinciannya di
<strong>Perhitungan hak cuti saat berhenti bekerja</strong>.</p>

<h3>Kalau tombolnya tidak muncul</h3>

<p>Berarti perusahaan Anda <strong>tidak</strong> mengizinkan cuti
melebihi saldo untuk jenis cuti itu — dan itu setelan yang sah, bukan
kerusakan. Pengaturannya bisa berbeda per jenis cuti, per lokasi, dan
per golongan pegawai. Bicarakan dengan atasan Anda; cuti tanpa upah
lazimnya jadi jalur penggantinya.</p>
""",
    },
    {
        "code": "HR-LEAVE-SEPARATION",
        "category": "HR-SELF-SERVICE",
        "status": HelpArticleStatus.DRAFT,
        "title": "Perhitungan hak cuti saat berhenti bekerja",
        "summary": (
            "Saat resign atau PHK, jatah cuti dihitung ulang sebanding "
            "masa kerja tahun berjalan — bukan dibaca dari sisa di "
            "kartu."
        ),
        "icon": "i-lucide-file-check-2",
        "keywords": (
            "resign, phk, berhenti, keluar, pesangon, uang penggantian "
            "hak, sisa cuti, penyelesaian"
        ),
        "route_prefix": "/hr/leave-balances",
        "sort_order": 27,
        "content": """
<p>Saat pengunduran diri atau pemutusan hubungan kerja Anda diproses,
sistem membuat satu <strong>rincian penyelesaian cuti</strong>. Isinya
bisa Anda minta ke HR dan dibaca berdampingan dengan kartu cuti
Anda.</p>

<h3>Angkanya bukan kolom Remaining</h3>

<p>Ini bagian yang paling sering mengejutkan, jadi perlu dijelaskan
pelan-pelan.</p>

<p>Jatah cuti tahunan lazimnya diberikan <strong>sekaligus di awal
tahun</strong> — 12 hari pada 1 Januari. Tapi hari-hari itu sebenarnya
<em>diperoleh</em> sepanjang tahun, sebulan sedikit demi sedikit. Kalau
Anda berhenti di pertengahan tahun, yang benar-benar sudah Anda peroleh
baru sebagian.</p>

<p>Karena itu saat berhenti, jatah tahun berjalan
<strong>dihitung ulang sebanding masa kerja Anda</strong>:</p>

<pre><code>hak tahun berjalan = jatah setahun &times; (bulan dilayani &divide; 12)</code></pre>

<p>Bulan yang sedang berjalan lazimnya dihitung penuh — berhenti
tanggal 10 Juli tetap dihitung 7 bulan, bukan 6.</p>

<h3>Rumus lengkapnya</h3>

<pre><code>hak bersih = hak tahun berjalan (prorata)
           + sisa bawaan tahun lalu yang belum gugur
           + koreksi manual dari HR
           &minus; seluruh cuti yang sudah diambil tahun ini</code></pre>

<ul>
  <li><strong>Hasilnya positif</strong> &rarr; menjadi hak Anda, dibayar
  sebagai uang penggantian hak bersama pembayaran terakhir.</li>
  <li><strong>Hasilnya negatif</strong> &rarr; Anda mengambil cuti lebih
  banyak daripada yang sempat diperoleh. Selisihnya diperhitungkan
  dalam penyelesaian akhir.</li>
</ul>

<h3>Contoh</h3>

<p>Jatah 12 hari setahun. Sisa tahun lalu 12 hari (batas 30 Juni).
Berhenti 31 Juli.</p>

<table>
  <thead>
    <tr><th>Komponen</th><th>Hari</th></tr>
  </thead>
  <tbody>
    <tr><td>Hak tahun berjalan &mdash; 12 &times; 7/12</td><td>7</td></tr>
    <tr><td>Sisa bawaan tahun lalu (terpakai sebelum 30 Juni)</td><td>12</td></tr>
    <tr><td>Cuti yang sudah diambil sepanjang tahun</td><td>&minus;28</td></tr>
    <tr><td><strong>Hak bersih</strong></td><td><strong>&minus;9</strong></td></tr>
  </tbody>
</table>

<p>Sembilan hari itu adalah cuti yang sudah dinikmati tapi jatahnya
belum sempat diperoleh.</p>

<h3>Kalau hasilnya negatif, apakah langsung dipotong?</h3>

<p><strong>Tidak otomatis.</strong> Sistem menghitung dan menampilkan
angkanya; keputusan pemotongannya ada di HR dan payroll, dan potongan
upah untuk membayar hutang pekerja memang harus punya dasar tertulis.
Persetujuan yang Anda centang saat mengajukan cuti di muka adalah
bagian dari dasar itu, dan salinannya tersimpan di dokumen cutinya.</p>

<p>Sebagian perusahaan memilih menghapuskannya. Tanyakan ke HR sebelum
menandatangani apa pun.</p>

<h3>Angkanya berbeda dari perkiraan Anda?</h3>

<p>Bawa tiga hal ini ke HR — ketiganya ada di layar, jadi bisa dicek
bersama:</p>

<ol>
  <li><strong>Tanggal kerja terakhir</strong> pada dokumen pengunduran
  diri Anda. Ini yang menentukan jumlah bulannya.</li>
  <li><strong>Kolom Used</strong> di kartu cuti tahun berjalan.</li>
  <li><strong>Kolom Carried Over dan Expired.</strong> Sisa tahun lalu
  yang sudah <em>gugur</em> lazimnya tidak ikut dibayar — dan itulah
  selisih yang paling sering tidak terduga.</li>
</ol>

<p>Angka penyelesaian dibekukan pada saat dokumen Anda diproses.
Perubahan kebijakan sesudahnya tidak mengubah rincian yang sudah
diserahkan ke Anda.</p>
""",
    },
    {
        "code": "HR-ATTENDANCE-LEAVE-OBLIGATION",
        "category": "HR-SELF-SERVICE",
        "title": "Terlambat lebih dari 2 jam: kenapa hari itu terhitung cuti",
        "summary": (
            "Keterlambatan atau pulang cepat di atas ambang tertentu "
            "terhitung sebagai satu hari cuti penuh. Cara membacanya, "
            "dan cara mengajukan keberatan."
        ),
        "icon": "i-lucide-alarm-clock-off",
        "keywords": (
            "telat, terlambat, finger, absen, pulang cepat, pulang "
            "awal, potong cuti, sanksi, keterlambatan"
        ),
        "route_prefix": "/hr/attendance",
        "sort_order": 35,
        "content": """
<p>Sebagian perusahaan menerapkan aturan: keterlambatan di atas batas
tertentu — lazimnya <strong>2 jam</strong> — terhitung sebagai
<strong>satu hari cuti penuh</strong>. Aturan yang sama berlaku untuk
pulang lebih awal dari batas itu.</p>

<p>Batasnya bisa berbeda di tiap perusahaan, lokasi, dan golongan
pegawai — dan di banyak lokasi aturannya <strong>tidak dinyalakan sama
sekali</strong>. Angka yang berlaku untuk Anda bisa ditanyakan ke HR.</p>

<h3>Cara membacanya di layar</h3>

<p>Buka <strong>HR &rsaquo; Attendance</strong> dan cari tanggalnya.
Dua kolom yang menjelaskannya:</p>

<table>
  <thead>
    <tr><th>Kolom</th><th>Artinya</th></tr>
  </thead>
  <tbody>
    <tr><td>Late</td><td>Menit keterlambatan Anda hari itu.</td></tr>
    <tr><td>Leave Required</td><td>Hari cuti yang harus diambil untuk
    hari itu. Nol = tidak ada.</td></tr>
    <tr><td>Obligation</td><td>Sudah diselesaikan atau belum:
    <em>Outstanding</em>, <em>Waived</em> (dibebaskan),
    <em>Leave Issued</em>, atau <em>Settled</em>.</td></tr>
  </tbody>
</table>

<h3>Tiga hal yang sering disalahpahami</h3>

<ul>
  <li><strong>Diukur dari jam jadwal, bukan dari batas toleransi.</strong>
  Toleransi harian (misalnya 15 menit) hanya menentukan apakah Anda
  tercatat terlambat. Ambang 2 jam dihitung dari jam masuk seharusnya —
  jadi tiba pukul 10.05 untuk jadwal 08.00 adalah 2 jam 5 menit, bukan
  1 jam 50 menit.</li>
  <li><strong>Sekali sehari, bukan dua kali.</strong> Datang terlambat
  <em>dan</em> pulang cepat di hari yang sama tetap terhitung satu
  potongan. Kolom keterangannya berbunyi "Terlambat &amp; pulang
  cepat".</li>
  <li><strong>Saldo Anda tidak berkurang otomatis.</strong> Yang muncul
  di baris presensi hanya <em>penandanya</em>. Saldo baru berkurang
  setelah ada dokumen cuti yang diterbitkan dan disetujui — dan Anda
  akan melihat dokumen itu seperti cuti biasa.</li>
</ul>

<h3>Anda tetap bekerja hari itu — kenapa dipotong sehari penuh?</h3>

<p>Karena ini <strong>aturan kedisiplinan</strong>, bukan perhitungan
jam kerja. Catatan presensi Anda tetap menyimpan jam masuk, jam pulang,
dan jam kerja bersih yang sebenarnya; potongan cutinya berdiri
terpisah dari angka-angka itu.</p>

<h3>Kalau ada alasannya</h3>

<p>Sampaikan ke atasan dan HR <strong>pada hari itu juga</strong> —
kecelakaan di jalan, kendaraan mogok, keperluan mendesak yang sudah
seizin atasan. HR bisa:</p>

<ul>
  <li><strong>Membebaskannya</strong> — potongan dibatalkan, alasannya
  dicatat pada baris presensi itu. Jam tap Anda tidak diubah, karena
  itu fakta.</li>
  <li><strong>Menyesuaikan jumlah harinya</strong> — misalnya menjadi
  setengah hari.</li>
</ul>

<p>Anda akan menerima pemberitahuan pada hari kejadian, bukan menunggu
sampai penggajian. Itu memang tujuannya: supaya masih ada waktu
menjelaskan sebelum keputusannya diambil.</p>

<h3>Kalau saldo cuti saya sudah habis?</h3>

<p>Cuti yang terbit dari sini diperlakukan sama dengan cuti lain: ia
menggerus sisa tahun lalu lebih dulu, dan kalau saldo Anda benar-benar
habis, ia menjadi <strong>cuti dibayar di muka</strong> yang
diperhitungkan bila Anda berhenti bekerja. Rinciannya di artikel
<strong>Mengajukan cuti saat saldo sudah habis</strong>.</p>
""",
    },
    {
        "code": "HR-ATTENDANCE-VIEW",
        "category": "HR-SELF-SERVICE",
        "title": "Memeriksa catatan kehadiran",
        "summary": (
            "Membaca jam masuk, keterlambatan, dan lembur — serta apa "
            "yang harus dilakukan kalau ada tanggal yang kosong."
        ),
        "icon": "i-lucide-calendar-check",
        "keywords": "absen, absensi, kehadiran, terlambat, fingerprint, lembur",
        "route_prefix": "/hr/attendance",
        "sort_order": 30,
        "content": """
<p>Buka <strong>HR &rsaquo; Attendance</strong>. Yang Anda lihat hanya
catatan Anda sendiri, kecuali Anda memang admin.</p>

<h3>Dari mana datanya</h3>
<p>Sebagian besar baris masuk otomatis dari mesin fingerprint. Nomor
pegawai di mesin harus sama persis dengan nomor pegawai di sistem —
kalau berbeda, tap Anda tidak akan menempel ke nama Anda.</p>

<h3>Membaca kolomnya</h3>
<ul>
  <li><strong>Late</strong> — selisih terhadap jam masuk terjadwal,
  sesudah dikurangi toleransi kalau perusahaan Anda memberikannya.</li>
  <li><strong>Overtime</strong> — hanya terisi kalau melewati ambang
  minimum. Lebih lima menit dari jam pulang lazimnya tidak dihitung
  lembur.</li>
  <li><strong>Absent</strong> — hari kerja terjadwal yang tidak punya
  satu pun tap. Ditulis sistem saat penutupan hari, bukan langsung.</li>
</ul>

<blockquote>
<p>Hari berlabel <strong>Recovery</strong> di Shift Calendar tidak
terhitung hari kerja terjadwal, jadi tidak akan pernah muncul sebagai
<em>Absent</em> — walaupun letaknya di tengah blok kerja Anda.</p>
</blockquote>

<h3>Ada tanggal yang salah atau hilang</h3>
<p>Jangan menunggu akhir bulan. Laporkan ke admin HR beserta
tanggalnya; koreksi kehadiran hanya bisa dilakukan orang yang punya
izin mengubah data absensi, dan setiap koreksinya tercatat.</p>
""",
    },

    # ------------------------------------------------------------------
    # Perjalanan & roster
    # ------------------------------------------------------------------
    {
        "code": "HR-TRAVEL-REQUEST",
        "category": "HR-TRAVEL-ROSTER",
        "title": "Mengajukan Travel Request",
        "summary": (
            "Dokumen kepulangan dari site: mengisi tujuan perjalanan, "
            "etape penerbangan, dan mengirimkannya untuk disetujui."
        ),
        "icon": "i-lucide-plane",
        "keywords": "travel request, tr, tiket, pulang, kepulangan, cuti lapangan",
        "route_prefix": "/hr/travel-requests",
        "sort_order": 10,
        "content": """
<p>Travel Request adalah dokumen <strong>satu kali kepulangan</strong>.
Ia berbeda dari Roster Schedule, yang merupakan jadwal kerja Anda
sepanjang tahun. Satu orang punya satu jadwal dan beberapa TR setahun.</p>

<h3>Membuat dokumen</h3>
<ol>
  <li>Buka <strong>HR &rsaquo; Travel Request</strong>, klik
  <strong>Add</strong>.</li>
  <li>Kalau jadwal roster Anda sudah tersusun, pilih blok off yang
  dituju pada <strong>Rotation Period</strong> — tanggalnya akan
  terisi otomatis. Blok jadwal hanya usulan tanggal; masih bisa
  diubah.</li>
  <li>Isi tabel <strong>Travel Purpose</strong>: alasan kepulangan
  beserta tanggalnya. Satu blok boleh dipecah — misalnya 7 hari Field
  Break lalu 7 hari Cuti Tahunan.</li>
  <li>Isi tabel <strong>Travel Arrangement</strong>: satu baris untuk
  satu etape perjalanan. Rute Jakarta &rarr; Sorong &rarr; Gebe berarti
  dua baris, masing-masing dengan moda dan nomor tiketnya.</li>
  <li>Klik <strong>Submit</strong>.</li>
</ol>

<h3>Yang perlu diperhatikan</h3>
<ul>
  <li><strong>Roster bukan syarat.</strong> Kalau jadwal Anda belum
  disusun, TR tetap bisa diajukan — kosongkan Rotation Period dan isi
  tanggalnya sendiri.</li>
  <li><strong>Baris yang memotong saldo cuti</strong> ditandai pada
  jenis tujuannya. Catatan cutinya baru terbit saat dokumen ini
  disetujui penuh, bukan saat diketik.</li>
  <li>Tanggal yang bentrok dengan cuti Anda yang lain ditolak saat
  Submit, bukan di akhir alur — supaya Anda masih bisa
  membetulkannya.</li>
  <li>Dokumen yang sudah Submit tidak bisa disunting. Tarik dulu
  dengan <strong>Withdraw</strong>.</li>
</ul>
""",
    },
    {
        "code": "HR-ROSTER-READ",
        "category": "HR-TRAVEL-ROSTER",
        "title": "Membaca jadwal roster Anda",
        "summary": (
            "Arti blok Work, Field Break, hari perjalanan, dan hari "
            "Recovery — serta kenapa jadwal bisa bergeser."
        ),
        "icon": "i-lucide-calendar-range",
        "keywords": (
            "roster, jadwal, siklus, swing, on site, off, field break, "
            "recovery, istirahat"
        ),
        "route_prefix": "/hr/site-rotations",
        "sort_order": 20,
        "content": """
<p>Buka <strong>HR &rsaquo; Roster Schedule</strong>. Dokumen jadwal
Anda berisi deretan blok, masing-masing dengan tanggal mulai dan
selesai.</p>

<h3>Empat jenis blok</h3>
<ul>
  <li><strong>Work</strong> — hari kerja di site.</li>
  <li><strong>Travel Out</strong> — perjalanan meninggalkan site.</li>
  <li><strong>Field Break</strong> — hari off Anda.</li>
  <li><strong>Travel In</strong> — perjalanan kembali ke site.</li>
</ul>

<p>Satu putaran berbentuk Work &rarr; Travel Out &rarr; Field Break
&rarr; Travel In. Kalau Anda tinggal di sekitar site, blok perjalanan
memang tidak ada — dan itu benar, bukan data yang belum lengkap.</p>

<h3>Hari perjalanan berbeda-beda antar orang</h3>
<p>Jumlahnya ditentukan jarak dari <strong>Point of Hire</strong> Anda
ke site, bukan oleh gelombang atau pola roster. Dua orang di crew yang
sama bisa punya jumlah hari perjalanan berbeda.</p>

<h3>Ada hari kosong di tengah blok kerja saya</h3>
<p>Kalau di <strong>Shift Calendar</strong> Anda menemukan satu hari
berlabel <strong>Recovery</strong> di tengah blok kerja, itu
<mark>bukan</mark> kesalahan data dan bukan hari yang lupa diisi. Hari
itu sengaja dikosongkan karena pergantian shift-nya tidak menyisakan
istirahat yang cukup.</p>

<p>Contohnya: shift malam <code>19:00&ndash;07:00 (+1)</code> baru
selesai pukul 07:00 pagi, dan shift berikutnya justru mulai pukul
07:00 di hari yang sama. Nol jam istirahat. Hari Recovery disisipkan di
antaranya, dan shift berikutnya bergeser satu hari.</p>

<ul>
  <li>Hari Recovery <strong>tidak</strong> menuntut Anda tap mesin, dan
  tidak akan dihitung mangkir.</li>
  <li>Blok kerja Anda <strong>tidak</strong> ikut bergeser — tanggal
  mulai dan selesainya tetap sama.</li>
  <li>Berapa jam yang dianggap cukup ditentukan aturan roster site
  Anda, bukan per orang.</li>
</ul>

<h3>Jadwal saya bergeser</h3>
<p>Penyesuaian dicatat sebagai dokumen <strong>Roster
Adjustment</strong> tersendiri, lengkap dengan alasannya. Beberapa
jenis penyesuaian memang <strong>tidak</strong> menggeser satu tanggal
pun — misalnya penerbangan yang dibatalkan maskapai — tapi tetap
dicatat supaya pertanyaan "kenapa jadwal saya tidak berubah" punya
jawaban tertulis.</p>

<p>Blok yang sudah lewat tidak pernah diubah oleh penyesuaian apa pun.
Yang berubah hanya blok sejak tanggal berlakunya ke depan.</p>
""",
    },

    # ------------------------------------------------------------------
    # Persetujuan
    # ------------------------------------------------------------------
    {
        "code": "WF-INBOX",
        "category": "APPROVAL",
        "title": "Menyetujui dokumen dari kotak masuk",
        "summary": (
            "Satu kotak masuk untuk semua modul: menyetujui, menolak, "
            "atau mengembalikan dokumen untuk diperbaiki."
        ),
        "icon": "i-lucide-inbox",
        "keywords": "approval, persetujuan, approve, reject, kotak masuk, inbox",
        "route_prefix": "/workflow/inbox",
        "sort_order": 10,
        "content": """
<p>Buka <strong>Workflow &rsaquo; My Approvals</strong>. Semua dokumen
yang menunggu keputusan Anda ada di sana — dari modul mana pun. Anda
tidak perlu membuka layar Cuti untuk menyetujui cuti.</p>

<h3>Tiga keputusan</h3>
<table>
  <thead>
    <tr><th>Tombol</th><th>Dipakai saat</th><th>Yang terjadi pada dokumennya</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Approve</strong></td>
      <td>Isinya benar dan Anda setuju</td>
      <td>Berpindah ke meja berikutnya — atau selesai, kalau Anda meja terakhir</td>
    </tr>
    <tr>
      <td><strong>Reject</strong></td>
      <td>Permintaannya memang tidak disetujui</td>
      <td>Berhenti. Pengaju harus membuat dokumen <strong>baru</strong> kalau masih ingin mengajukan</td>
    </tr>
    <tr>
      <td><strong>Return</strong></td>
      <td>Maksudnya benar tapi isinya salah — misalnya tanggal keliru satu hari</td>
      <td>Kembali ke pengaju untuk dibetulkan, lalu diajukan ulang <mark>tanpa kehilangan jejaknya</mark></td>
    </tr>
  </tbody>
</table>

<p>Tulis alasan pada Reject dan Return. Yang menerimanya hanya melihat
apa yang Anda tulis, dan tanpa itu ia hanya tahu dokumennya ditolak.</p>

<h3>Yang perlu diketahui</h3>
<ul>
  <li>Anda hanya melihat dokumen yang <strong>sudah giliran Anda</strong>.
  Yang masih di meja sebelum Anda belum tampil — dan memang belum perlu
  Anda putuskan, karena bisa saja ditolak di bawah.</li>
  <li>Klik satu baris untuk membuka jejak persetujuannya: siapa saja
  yang sudah memutuskan, kapan, dan apa alasannya.</li>
  <li>Baris yang sudah Anda putuskan langsung hilang dari daftar.</li>
</ul>
""",
    },
    {
        "code": "WF-MY-SUBMISSIONS",
        "category": "APPROVAL",
        "title": "Melacak pengajuan Anda sendiri",
        "summary": (
            "Melihat dokumen Anda sedang berada di meja siapa dan sudah "
            "berapa lama menunggu di sana."
        ),
        "icon": "i-lucide-send",
        "keywords": "pengajuan, status, tracking, menunggu, progress",
        "route_prefix": "/workflow/submissions",
        "sort_order": 20,
        "content": """
<p>Buka <strong>Workflow &rsaquo; My Submissions</strong>.</p>

<p>Tiap baris menampilkan batang kemajuan dan keterangan
<strong>menunggu siapa</strong> beserta sejak kapan. Angka "sejak"
dihitung dari keputusan terakhir sebelum meja itu — bukan dari tanggal
Anda mengajukan, supaya yang terbaca adalah berapa lama dokumen
tertahan di meja yang sekarang.</p>

<h3>Empat keadaan akhir</h3>
<ul>
  <li><strong>Approved</strong> — selesai dan disetujui.</li>
  <li><strong>Rejected</strong> — ditolak.</li>
  <li><strong>Returned</strong> — dikembalikan untuk diperbaiki.
  Buka dokumennya, betulkan, lalu Submit lagi.</li>
  <li><strong>Cancelled</strong> — Anda tarik sendiri, atau ditutup
  karena diajukan ulang.</li>
</ul>

<p>Beberapa meja mungkin tertulis <em>dilewati</em>. Itu terjadi kalau
orang yang seharusnya menandatangani sudah menandatangani di langkah
sebelumnya, atau kalau syarat langkah itu tidak terpenuhi — misalnya
meja HR Manager yang hanya berlaku untuk cuti lima hari ke atas.</p>
""",
    },
    {
        "code": "WF-DELEGATION",
        "category": "APPROVAL",
        "title": "Menyerahkan persetujuan saat Anda tidak di tempat",
        "summary": (
            "Membuat surat kuasa supaya dokumen tidak menumpuk di meja "
            "Anda selama cuti."
        ),
        "icon": "i-lucide-user-round-check",
        "keywords": "delegasi, kuasa, wakil, cuti, pengganti",
        "route_prefix": "/workflow/delegations",
        "sort_order": 30,
        "content": """
<p>Buka <strong>Workflow &rsaquo; Delegations</strong>, klik
<strong>Add</strong>. Anda boleh membuat kuasa untuk diri sendiri tanpa
perlu menunggu IT.</p>

<ol>
  <li>Pilih siapa yang menerima kuasa.</li>
  <li>Tentukan periodenya.</li>
  <li>Batasi modul atau jenis dokumen kalau perlu. Dikosongkan berarti
  berlaku untuk semua.</li>
</ol>

<h3>Yang berubah dan yang tidak</h3>
<p>Delegasi <strong>tidak mengubah siapa approver-nya</strong>. Kotak
tanda tangan pada dokumen tercetak tetap atas nama Anda; yang berubah
hanya siapa yang boleh menekan tombolnya, dan itu tercatat lengkap
dengan surat kuasanya.</p>

<p>Dua surat kuasa aktif dengan cakupan yang tumpang tindih akan
ditolak — kalau dibiarkan, satu dokumen punya dua penerima kuasa yang
sama-sama berhak.</p>
""",
    },

    # ------------------------------------------------------------------
    # Admin HR
    # ------------------------------------------------------------------
    {
        "code": "ADM-EMPLOYEE-NEW",
        "category": "HR-ADMIN",
        "title": "Menambahkan pegawai baru",
        "summary": (
            "Kolom yang wajib diisi, nomor pegawai otomatis, dan apa "
            "yang terbit sendiri setelah disimpan."
        ),
        "icon": "i-lucide-user-plus",
        "keywords": "pegawai baru, karyawan, employee, nomor pegawai, nip",
        "route_prefix": "/hr/employees",
        "sort_order": 10,
        "role": "HR-ADMIN",
        "content": """
<ol>
  <li>Buka <strong>HR &rsaquo; Employees</strong>, klik
  <strong>Add</strong>.</li>
  <li>Pilih <strong>Company</strong> lebih dulu. Kolom
  <strong>Employee Number</strong> akan langsung memperlihatkan nomor
  yang akan terbit.</li>
  <li>Isi tab <strong>General</strong>, lalu tab
  <strong>Organization</strong> dan <strong>Employment</strong>.</li>
  <li>Klik <strong>Save</strong>.</li>
</ol>

<h3>Nomor pegawai</h3>
<p>Selama <strong>Auto Generate</strong> menyala, nomornya dikunci dan
diterbitkan sistem per perusahaan per tahun. Angka yang tampil sebelum
disimpan adalah <em>perkiraan</em> — nomor yang benar-benar terbit
dialokasikan saat Save. Matikan saklarnya kalau nomornya harus diketik
sendiri; keunikannya tetap diperiksa.</p>

<p>Nomor pegawai hanya dialokasikan saat pembuatan dan tidak pernah
dihitung ulang. Transfer atau pindah perusahaan tidak mengubahnya —
nomor itu sudah tercetak di kontrak dan terdaftar di mesin absensi.</p>

<h3>Yang wajib dan yang tidak</h3>
<p>Dari seluruh struktur organisasi, hanya <strong>Company</strong>
yang wajib. Branch, Location, Division, Department, dan Section boleh
dikosongkan, dan boleh dilompati — satu struktur ini melayani kantor
tunggal maupun tambang multi-lokasi.</p>

<h3>Setelah disimpan</h3>
<ul>
  <li>Saldo cuti terbit sendiri begitu <strong>Join Date</strong>
  diisi, mengikuti kebijakan jatah yang berlaku untuk pegawai itu.</li>
  <li>Pegawai <strong>belum punya akun</strong>. Akun dibuat terpisah
  di <strong>Security &rsaquo; Users</strong>. Tanpa akun, ia tidak
  bisa login dan tidak akan pernah jadi approver.</li>
</ul>
""",
    },
    {
        "code": "ADM-IMPORT",
        "category": "HR-ADMIN",
        "title": "Import data dari file",
        "summary": (
            "Alur unduh template, preview, lalu konfirmasi — dan cara "
            "membaca laporan barisnya yang gagal."
        ),
        "icon": "i-lucide-upload",
        "keywords": "import, excel, csv, upload, unggah, migrasi data",
        "route_prefix": "",
        "sort_order": 20,
        "role": "HR-ADMIN",
        "content": """
<p>Layar yang mendukung import punya tombol <strong>Import</strong> di
toolbar tabelnya.</p>

<ol>
  <li>Klik <strong>Import</strong>, lalu <strong>Download
  Template</strong>. Template berisi nama kolom yang dikenali beserta
  satu baris contoh.</li>
  <li>Isi file Anda, lalu unggah.</li>
  <li>Sistem menampilkan <strong>preview</strong>: baris yang valid,
  baris yang bermasalah, dan relasi yang berhasil dicocokkan. Pada
  tahap ini <strong>belum ada data yang ditulis</strong>.</li>
  <li>Kalau hasilnya sudah benar, klik <strong>Confirm</strong>.
  Prosesnya berjalan di belakang layar dan kemajuannya bisa dipantau.</li>
</ol>

<h3>Selalu periksa preview</h3>
<p>Jangan melewatinya. Dua kesalahan paling sering, dan keduanya
<strong>tidak</strong> memunculkan pesan error:</p>
<ul>
  <li><strong>Format tanggal.</strong> File bergaya Amerika
  (<code>5/2/2011</code> untuk 2 Mei) terbaca sebagai 5 Februari, dan
  tidak ada yang salah secara teknis. Atur format tanggalnya di Import
  Profile.</li>
  <li><strong>Kode yang ambigu.</strong> Kode departemen dan lokasi
  hanya unik per perusahaan. Kode yang cocok di dua perusahaan
  <em>ditolak</em>, tidak ditebak — sertakan kolom induknya.</li>
</ul>

<h3>Kalau ada baris yang gagal</h3>
<p>Unduh laporan errornya. Isinya nomor baris dan alasannya per baris.
Betulkan di file Anda, lalu import ulang — baris yang sudah masuk
dikenali dari kunci uniknya dan diperbarui, bukan diduplikasi.</p>
""",
    },
    {
        "code": "ADM-ROSTER-SETUP",
        "category": "HR-ADMIN",
        "title": "Menyusun roster untuk banyak pegawai sekaligus",
        "summary": (
            "Enam langkah dari dokumen kosong sampai jadwal terbit, "
            "lewat dua tahap persetujuan."
        ),
        "icon": "i-lucide-calendar-plus",
        "keywords": "roster setup, jadwal massal, batch, site, gelombang",
        "route_prefix": "/hr/roster-setups",
        "sort_order": 30,
        "role": "HR-ADMIN",
        "content": """
<p>Satu dokumen menampung banyak pegawai sekaligus — satu gelombang
penyiapan, bukan satu dokumen per orang.</p>

<h3>Enam langkah, sekilas</h3>
<table>
  <thead>
    <tr><th>#</th><th>Yang Anda lakukan</th><th>Hasil yang harus muncul</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td>Create &rarr; isi Company, Site, As Of Date, Horizon &rarr; <strong>Save</strong></td><td>Nomor dokumen terbit, status <strong>Draft</strong></td></tr>
    <tr><td>2</td><td><strong>Actions &rsaquo; Add Employees</strong></td><td>Tiap pegawai membawa jangkar siklusnya sendiri</td></tr>
    <tr><td>3</td><td><strong>Actions &rsaquo; Preview Schedule</strong></td><td><code>N baris ditinjau; 0 bermasalah.</code></td></tr>
    <tr><td>4</td><td><strong>Actions &rsaquo; Submit</strong></td><td>Status <strong>Pending Approval</strong></td></tr>
    <tr><td>5</td><td>Approver 1 menyetujui (Admin HR Site)</td><td>Berpindah ke tahap kedua</td></tr>
    <tr><td>6</td><td>Approver 2 menyetujui (HR Manager Site)</td><td>Status <strong>Committed</strong>, jadwal terbit</td></tr>
  </tbody>
</table>

<hr>

<h3>1. Buat dokumennya</h3>
<p>Buka <strong>HR &rsaquo; Roster Setups</strong>, klik
<strong>Create</strong>, lalu isi:</p>

<table>
  <thead>
    <tr><th>Kolom</th><th>Isi</th></tr>
  </thead>
  <tbody>
    <tr><td><strong>Company</strong></td><td>Wajib</td></tr>
    <tr><td><strong>Site</strong></td><td>Wajib. Satu dokumen hanya untuk satu site</td></tr>
    <tr><td>Department, Section</td><td>Boleh kosong; mengisinya mempersempit daftar kandidat</td></tr>
    <tr><td><strong>As Of Date</strong></td><td>Tanggal acuan penyusunan</td></tr>
    <tr><td><strong>Horizon (Months)</strong></td><td>Panjang jadwal yang diterbitkan</td></tr>
  </tbody>
</table>

<blockquote>
<p>Kolom tanggal memakai format <mark>hari dulu</mark>:
<code>01.09.26</code> berarti 1 September 2026 — bukan 9 Januari.</p>
</blockquote>

<h3>2. Masukkan pegawainya</h3>
<p><strong>Actions &rsaquo; Add Employees</strong>, pilih beberapa
sekaligus, lalu konfirmasi.</p>

<p>Tiap pegawai masuk membawa <strong>Roster Policy</strong> dan
<strong>Current Cycle Start</strong> miliknya sendiri, diambil dari
penempatannya. Jadi tanggal jangkarnya <mark>memang berbeda-beda</mark>
antar orang di satu dokumen — itu benar, bukan data yang belum diisi:
setiap orang sedang berada di titik siklus yang berbeda. Anda tetap
bisa mengoreksinya per baris di tab <strong>Employees</strong>.</p>

<blockquote>
<p><strong>Pegawai yang dicari tidak muncul?</strong> Daftar kandidat
menyaring sendiri: yang <strong>sudah punya roster berjalan</strong>
dan yang sudah berhenti tidak ditampilkan. Tutup dulu eranya, atau
pakai dokumen <strong>Roster Adjustment</strong> untuk mengubah jadwal
yang sudah ada.</p>
</blockquote>

<h3>3. Tinjau sebelum diajukan</h3>
<p><strong>Actions &rsaquo; Preview Schedule</strong> menghitung
jadwal lengkapnya <strong>tanpa menyimpan apa pun</strong>. Yang
tampil di sini persis yang nanti tersimpan.</p>

<table>
  <thead>
    <tr><th>Jenis temuan</th><th>Artinya</th></tr>
  </thead>
  <tbody>
    <tr><td><strong>Blocking</strong></td><td>Harus dibetulkan. Jadwalnya tidak akan terbit, dan Submit akan ditolak dengan alasan yang sama</td></tr>
    <tr><td><strong>Warning</strong></td><td>Boleh dilanjutkan. Misalnya pegawai yang belum punya pasangan back-to-back — itu tidak boleh menghalangi jadwalnya terbit</td></tr>
  </tbody>
</table>

<h3>4. Ajukan</h3>
<p><strong>Actions &rsaquo; Submit</strong>. Status berubah menjadi
<strong>Pending Approval</strong> dan dokumen berpindah ke meja
approver — sampai di sini tugas Anda selesai.</p>

<h3>5 &amp; 6. Persetujuan dua tahap</h3>
<p>Kedua tahapnya berbasis <strong>role</strong>, dan approver
membukanya di <strong>Workflow &rsaquo; My Approvals</strong>.</p>

<table>
  <thead>
    <tr><th>Tahap</th><th>Siapa</th></tr>
  </thead>
  <tbody>
    <tr><td>Prepared By</td><td>Pemegang role <strong>Admin HR Site</strong> di site tersebut</td></tr>
    <tr><td>Approved By</td><td>Pemegang role <strong>HR Manager Site</strong></td></tr>
  </tbody>
</table>

<blockquote>
<p>Kalau Anda bukan pemegang role itu, kotak masuk Anda akan
<mark>kosong</mark> walau Anda yang membuat dokumennya. Itu memang
aturannya, bukan gangguan sistem.</p>
</blockquote>

<h3>Jadwal terbit sendiri saat disetujui</h3>
<p>Begitu tahap terakhir menyetujui, dokumen <strong>langsung menjadi
Committed</strong> dan jadwalnya terbit — <mark>tidak ada tombol yang
perlu ditekan lagi</mark>. Rencana shift tiap pegawai ikut terbit
bersamaan; lihat panduan <em>Mengatur perputaran shift dan membaca
Shift Calendar</em>.</p>

<blockquote>
<p>Kalau Roster Policy site itu mengisi <strong>Minimum Rest
(hours)</strong>, sebagian tanggal di dalam blok kerja akan terbit
sebagai hari <strong>Recovery</strong> — tanpa shift, dan tanpa
kewajiban presensi. Blok kerjanya <mark>tidak</mark> ikut bergeser.
Itu bukan baris yang gagal terbit.</p>
</blockquote>

<p>Tombol <strong>Commit</strong> dipakai hanya kalau ada baris yang
gagal terbit — misalnya jadwalnya ternyata bentrok. Baris yang gagal
ditandai beserta alasannya, dan mengulang Commit tidak memproses ulang
baris yang sudah berhasil: satu baris gagal tidak membatalkan dua
puluh sembilan lainnya.</p>

<hr>

<h3>Batas yang perlu diketahui</h3>
<ul>
  <li><strong>Satu batch = satu site.</strong> Kalau bercampur,
  approver-nya tidak bisa ditentukan.</li>
  <li>Maksimal <strong>200 baris</strong> per batch. Lebih dari itu,
  pecah per Section.</li>
</ul>
""",
    },

    {
        "code": "ADM-ROSTER-SHIFT",
        "category": "HR-ADMIN",
        "title": "Mengatur perputaran shift dan membaca Shift Calendar",
        "summary": (
            "Susun urutan shift dan jeda istirahat minimum sekali di "
            "Roster Policy, lalu baca hasilnya per tanggal dan buat "
            "pengecualian bila perlu."
        ),
        "icon": "i-lucide-calendar-sync",
        "keywords": (
            "shift, rotasi shift, shift calendar, adjust shift, "
            "perputaran, baseline, malam, recovery, istirahat, "
            "minimum rest, jeda"
        ),
        "route_prefix": "/hr/shift-calendar",
        "sort_order": 40,
        "role": "HR-ADMIN",
        "content": """
<p>Roster menjawab <strong>kapan</strong> orang bekerja. Shift
menjawab <strong>jam berapa</strong>. Keduanya disusun di tempat
berbeda — dan yang kedua cukup diatur <mark>sekali per site</mark>.</p>

<table>
  <thead>
    <tr><th>#</th><th>Tempat</th><th>Yang terjadi</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td>Roster Policy &rsaquo; tab <strong>Shift Rotation</strong></td><td>Anda susun urutannya, sekali saja</td></tr>
    <tr><td>2</td><td>Roster Policy &rsaquo; tab <strong>Cycle Pattern</strong></td><td>Anda tentukan <strong>Minimum Rest (hours)</strong></td></tr>
    <tr><td>3</td><td>Roster Schedule</td><td>Rencana shift terbit <strong>sendiri</strong></td></tr>
    <tr><td>4</td><td><strong>Shift Calendar</strong></td><td>Anda baca hasilnya per tanggal</td></tr>
    <tr><td>5</td><td>Tombol <strong>Adjust Shift</strong></td><td>Pengecualian pada rentang tertentu</td></tr>
  </tbody>
</table>

<hr>

<h3>1. Susun perputarannya</h3>
<p>Buka <strong>Roster Policy</strong> site tersebut, masuk ke tab
<strong>Shift Rotation</strong>, lalu isi urutannya. Contoh
perputaran tiga langkah:</p>

<table>
  <thead>
    <tr><th>Langkah</th><th>Shift</th><th>Jam</th><th>Panjang blok</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td>Morning</td><td><code>07:00 &ndash; 15:00</code></td><td>7 hari</td></tr>
    <tr><td>2</td><td>Night</td><td><code>23:00 &ndash; 07:00 (+1)</code></td><td>7 hari</td></tr>
    <tr><td>3</td><td>Day</td><td><code>15:00 &ndash; 23:00</code></td><td>7 hari</td></tr>
  </tbody>
</table>

<p>Sesudah langkah terakhir, urutannya mengulang dari langkah 1.</p>

<blockquote>
<p>Jam kerjanya <strong>tidak</strong> diketik di sini — diambil dari
master <strong>Shift</strong>. Mengubah jam satu shift cukup di satu
tempat, dan seluruh jadwal mengikutinya.</p>
</blockquote>

<h3>2. Tentukan jeda istirahat minimum</h3>
<p>Di <strong>Roster Policy</strong> yang sama, tab <strong>Cycle
Pattern</strong>, ada kolom <strong>Minimum Rest (hours)</strong>.
Isinya berapa jam istirahat yang wajib ada <mark>saat shift
berganti</mark>.</p>

<p>Yang dihitung selisih waktu sebenarnya: dari <strong>jam selesai
shift terakhir</strong> sampai <strong>jam mulai shift
berikutnya</strong>. Tanpa kolom ini, pergantian seperti di bawah ini
lolos begitu saja — dan tidak ada satu angka pun yang terlihat
salah:</p>

<table>
  <thead>
    <tr><th>Tanggal</th><th>Shift</th><th>Jam</th></tr>
  </thead>
  <tbody>
    <tr><td>24</td><td>Night</td><td><code>19:00 &ndash; 07:00 (+1)</code></td></tr>
    <tr><td>25</td><td>Day</td><td><code>07:00 &ndash; 19:00</code></td></tr>
  </tbody>
</table>

<p>Malamnya baru selesai tanggal <strong>25 pukul 07:00</strong>, dan
Day-nya mulai pukul 07:00 di hari yang sama: <strong>nol jam</strong>
istirahat. Dengan Minimum Rest diisi <code>24</code>, sistem menyisipkan
satu hari <strong>Recovery</strong>:</p>

<table>
  <thead>
    <tr><th>Tanggal</th><th>Shift</th><th>Jam</th></tr>
  </thead>
  <tbody>
    <tr><td>24</td><td>Night</td><td><code>19:00 &ndash; 07:00 (+1)</code></td></tr>
    <tr><td>25</td><td><strong>Recovery</strong></td><td>&mdash; tidak ada shift &mdash;</td></tr>
    <tr><td>26</td><td>Day</td><td><code>07:00 &ndash; 19:00</code></td></tr>
  </tbody>
</table>

<p>Empat hal yang perlu diketahui tentang kolom ini:</p>
<ul>
  <li><strong>Bawaannya <code>0</code></strong> — artinya tidak
  diperiksa sama sekali. Site yang selama ini berjalan tanpa aturan ini
  tidak berubah apa-apa sampai angkanya diisi.</li>
  <li><strong>Rosternya tidak digeser.</strong> Hari Recovery memakai
  hari dari blok kerja yang sudah ada; tanggal mulai dan selesai blok
  kerjanya tetap sama persis.</li>
  <li><strong>Jumlah harinya dihitung, bukan selalu satu.</strong>
  Ambang 24 jam menyisipkan satu hari untuk pergantian di atas; ambang
  40 jam menyisipkan dua. Pergantian yang jedanya memang sudah cukup
  tidak disisipi apa pun.</li>
  <li><strong>Hanya saat shift berganti.</strong> Dua malam berturutan
  yang berjarak 12 jam adalah jeda harian biasa, bukan pergantian —
  tidak akan disisipi.</li>
</ul>

<blockquote>
<p>Aturan ini juga menjaga <strong>batas antar blok kerja</strong>,
bukan cuma pergantian di dalam satu blok. Kalau blok berikutnya
menyambung langsung dan mulai dari shift yang berbeda, jedanya diukur
dengan cara yang sama.</p>
</blockquote>

<h3>3. Rencana shift terbit sendiri</h3>
<p>Setiap kali roster dibuat atau digeser, rencana shift ikut disusun
ulang dari konfigurasi di atas. Anda <mark>tidak perlu</mark> membuka
layar penugasan shift untuk membuatnya satu per satu.</p>

<p>Polanya dijangkarkan ke <strong>awal blok kerja masing-masing
pegawai</strong>, bukan ke tanggal yang sama untuk semua. Dua orang
dengan jangkar berbeda memang tidak akan seragam di bulan yang sama —
itu yang membuat gelombang crew tetap bergantian.</p>

<h3>4. Baca hasilnya</h3>
<p>Buka <strong>HR &rsaquo; Shift Calendar</strong>, pilih pegawai dan
bulannya. Klik satu tanggal untuk melihat rinciannya:</p>

<table>
  <thead>
    <tr><th>Yang ditampilkan</th><th>Artinya</th></tr>
  </thead>
  <tbody>
    <tr><td>Status roster</td><td>Kerja, libur, perjalanan, field break, atau <strong>Recovery</strong></td></tr>
    <tr><td>Shift &amp; jam terjadwal</td><td>Jam masuk dan pulang hari itu</td></tr>
    <tr><td>Sumber</td><td>Dari roster, atau dari penyesuaian</td></tr>
    <tr><td>Alasan penyesuaian</td><td>Terisi hanya kalau tanggal itu disesuaikan</td></tr>
  </tbody>
</table>

<p>Shift malam ditampilkan <code>23:00&ndash;07:00 (+1)</code>. Tanda
<code>(+1)</code> berarti jam pulangnya jatuh di tanggal berikutnya,
dan presensi memang menutupnya di sana.</p>

<blockquote>
<p>Hari libur, perjalanan, dan field break <strong>tidak</strong>
diberi shift kerja. Begitu juga pegawai yang Attendance-nya tidak
berlaku — kalendernya berbunyi <em>Not Applicable</em>. Itu
konfigurasi Employee Group, bukan data yang belum lengkap.</p>
</blockquote>

<p>Sel <strong>Recovery</strong> berwarna hijau, tanpa kode shift dan
tanpa jam. Jumlahnya disebutkan di kepala kalender
(<em>&ldquo;2 hari recovery&rdquo;</em>) tepat di sebelah angka hari
terjadwal — jadi kalau angka hari terjadwal terlihat kurang dari
biasanya, penjelasannya ada di layar yang sama.</p>

<blockquote>
<p>Hari Recovery <strong>tidak menerbitkan kewajiban presensi</strong>:
tidak ada jam terjadwal, tidak ada keterlambatan, dan penutupan hari
tidak menandainya mangkir. Bedanya dengan sel oranye
<em>&ldquo;Belum ada shift&rdquo;</em>: yang oranye berarti masternya
belum lengkap dan harus diperbaiki, yang hijau memang keputusan
jadwalnya.</p>
</blockquote>

<h3>5. Pengecualian: Adjust Shift</h3>
<p>Untuk satu orang yang tukar shift beberapa hari saja, pakai tombol
<strong>Adjust Shift</strong> di layar kalender.</p>

<table>
  <thead>
    <tr><th>Kolom</th><th>Isi</th></tr>
  </thead>
  <tbody>
    <tr><td><strong>Start Date</strong> &amp; <strong>End Date</strong></td><td>Rentang yang disesuaikan</td></tr>
    <tr><td><strong>Shift</strong></td><td>Shift pengganti, dari master Shift</td></tr>
    <tr><td><strong>Reason</strong></td><td>Wajib diisi</td></tr>
  </tbody>
</table>

<p>Penyesuaian berlaku <mark>hanya pada rentang itu</mark> — tanggal
di luarnya tetap mengikuti roster. Menghapus penyesuaiannya
mengembalikan tanggal tersebut ke rencana semula.</p>

<blockquote>
<p>Alasan wajib diisi karena itu yang menjawab pertanyaan "kenapa
shift saya diubah" berbulan-bulan kemudian, saat orang yang
mengubahnya sudah tidak ingat.</p>
</blockquote>

<p><strong>Penyesuaian menang atas hari Recovery.</strong> Kalau site
benar-benar kekurangan orang, Anda tetap bisa menugaskan shift di
tanggal Recovery — dan Minimum Rest <mark>tidak</mark> menolaknya.
Aturan itu menyusun <strong>rencana</strong>; penyesuaian adalah
keputusan orang yang sedang melihat kondisi site, dan sistem tidak
mengambil alih keputusan itu. Konsekuensinya juga berarti penyesuaian
bisa menghasilkan jadwal tanpa jeda — periksa sendiri jam shift
sebelum dan sesudahnya.</p>

<hr>

<h3>Shift Assignment Records</h3>
<p>Layar itu untuk <strong>penelusuran</strong> — melihat baris
rencana dan penyesuaian satu per satu ketika ada yang perlu dicek.
Bukan tempat menyusun roster, dan dalam pemakaian normal tidak perlu
disentuh.</p>
""",
    },

    {
        "code": "ADM-LEAVE-GO-LIVE",
        "category": "HR-ADMIN",
        "title": "Menyalakan modul cuti: tanggal go-live dan saldo awal",
        "summary": (
            "Menetapkan tanggal perusahaan mulai mencatat cuti di "
            "sistem, memasukkan saldo dari sistem lama, lalu "
            "mem-posting-nya jadi saldo pegawai."
        ),
        "icon": "i-lucide-power",
        "keywords": (
            "go live, go-live, saldo awal, opening balance, migrasi, "
            "cuti, import saldo, post"
        ),
        "route_prefix": "/hr/leave-opening-balances",
        "sort_order": 50,
        "role": "HR-ADMIN",
        "content": """
<p>Saat perusahaan pindah dari pencatatan lama ke sistem ini, sisa
cuti orang tidak muncul sendiri. Ada dua hal yang harus disiapkan:
<strong>kapan</strong> sistem mulai berlaku, dan <strong>berapa</strong>
sisa cuti tiap orang pada saat itu.</p>

<table>
  <thead>
    <tr><th>#</th><th>Langkah</th><th>Di mana</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td>Tetapkan tanggal go-live per perusahaan</td><td><strong>Leave Go Live</strong></td></tr>
    <tr><td>2</td><td>Masukkan saldo dari sistem lama</td><td><strong>Leave Opening Balance</strong> &mdash; import CSV atau isi manual</td></tr>
    <tr><td>3</td><td>Periksa angkanya selagi masih Draft</td><td>Daftar Leave Opening Balance</td></tr>
    <tr><td>4</td><td><strong>Post</strong> agar jadi saldo pegawai</td><td>Tombol <strong>Post Saldo Awal</strong></td></tr>
  </tbody>
</table>

<blockquote>
<p>Urutannya tidak bisa dibalik. Saldo awal tidak bisa masuk untuk
perusahaan yang <mark>belum punya tanggal go-live</mark> — barisnya
ditolak dengan pesan yang menyebut jalan keluarnya.</p>
</blockquote>

<hr>

<h3>1. Tetapkan tanggal go-live</h3>
<p>Buka <strong>Leave Go Live</strong>, buat satu baris per
perusahaan: pilih <strong>Company</strong> dan isi
<strong>Go Live Date</strong> — tanggal pertama sistem ini yang
mencatat cuti.</p>

<p>Tanggalnya <strong>milik perusahaan</strong>, bukan per lokasi atau
per golongan. Satu badan usaha pindah sekaligus; setengah perusahaan
tidak bisa pindah sementara setengahnya belum.</p>

<blockquote>
<p>Saldo awal yang Anda masukkan adalah sisa cuti pada
<strong>hari sebelum</strong> go-live. Kalau go-live 1 September,
angkanya adalah posisi per 31 Agustus.</p>
</blockquote>

<h3>2. Masukkan saldo dari sistem lama</h3>
<p>Buka <strong>Leave Opening Balance</strong>. Untuk beberapa orang,
isi manual lewat <strong>Create</strong>. Untuk satu perusahaan penuh,
pakai <strong>Import</strong> dengan berkas CSV.</p>

<table>
  <thead>
    <tr><th>Kolom CSV</th><th>Wajib</th><th>Keterangan</th></tr>
  </thead>
  <tbody>
    <tr><td><code>employee_code</code></td><td>Ya</td><td>Nomor pegawai</td></tr>
    <tr><td><code>employee_name</code></td><td>Tidak</td><td>Hanya untuk memeriksa mata &mdash; salah nomor terlihat saat berkas masih disunting</td></tr>
    <tr><td><code>leave_type</code></td><td>Ya</td><td>Jenis cutinya</td></tr>
    <tr><td><code>opening_date</code></td><td>Tidak</td><td>Kosong = ikut tanggal go-live perusahaannya</td></tr>
    <tr><td><code>opening_balance</code></td><td>Ya</td><td>Sisa cuti aktual pada tanggal itu</td></tr>
    <tr><td><code>remark</code></td><td>Tidak</td><td>Catatan bebas</td></tr>
  </tbody>
</table>

<p>Satu baris per pegawai per jenis cuti. Pegawai yang
<strong>sudah punya</strong> saldo awal ditolak sebagai duplikat —
bukan ditimpa.</p>

<blockquote>
<p><strong>Saldo nol tetap perlu diimport.</strong> Nol adalah
pernyataan "orang ini memang tidak punya sisa", dan itu berbeda dari
tidak ada barisnya sama sekali.</p>
</blockquote>

<h3>3. Periksa selagi masih Draft</h3>
<p>Hasil import masuk berstatus <strong>Draft</strong> dan
<mark>belum memengaruhi kartu cuti siapa pun</mark>. Inilah satu-satunya
kesempatan menangkap kolom yang tertukar sebelum angkanya menempel di
kartu orang.</p>

<p>Perhatikan terutama baris bertanda <strong>Review</strong>: saldo di
atas nol untuk pegawai yang menurut kebijakan belum berhak. Baris itu
<strong>tidak</strong> ditolak dan tidak diubah — sistem hanya menandai
supaya Anda memutuskan, karena bisa saja memang benar menurut
perjanjian lamanya.</p>

<h3>4. Post</h3>
<p>Sesudah angkanya benar, tekan <strong>Post Saldo Awal</strong>.</p>

<table>
  <thead>
    <tr><th>Cara</th><th>Yang diproses</th></tr>
  </thead>
  <tbody>
    <tr><td>Centang beberapa baris lalu Post</td><td>Hanya yang dicentang</td></tr>
    <tr><td>Tanpa mencentang apa pun</td><td><strong>Seluruh baris Draft yang sedang terlihat</strong> &mdash; penyaring toolbar ikut berlaku</td></tr>
  </tbody>
</table>

<p>Baris yang gagal dilaporkan satu per satu dan tidak membatalkan yang
berhasil. Aman diulang.</p>

<p>Sesudah di-post, angkanya jadi saldo cuti pegawai dan langsung bisa
dipakai mengajukan cuti.</p>

<h3>Kalau ada yang salah sesudah Post</h3>
<p>Buka barisnya dan tekan <strong>Unpost</strong>. Angkanya keluar
dari kartu cuti pegawainya.</p>

<blockquote>
<p>Cuti yang <strong>sudah terlanjur diambil tetap tercatat</strong>,
jadi saldonya bisa jadi minus sampai angka penggantinya di-post. Itu
memang disengaja: menghapus saldo tidak boleh diam-diam menghapus cuti
yang sudah dijalani orang.</p>
</blockquote>

<hr>

<h3>Yang perlu diketahui</h3>
<ul>
  <li>Sistem ini <strong>tidak menerbitkan jatah untuk tahun
  go-live</strong>. Angka yang Anda masukkan adalah saldo aktual, dan
  tidak ada jatah yang akan menumpukinya.</li>
  <li>Cuti dengan tanggal <strong>sebelum</strong> go-live bukan urusan
  sistem ini &mdash; catatannya ada di sistem lama, dan saldo awal sudah
  memperhitungkannya.</li>
  <li>Semua langkah di atas juga tersedia lewat baris perintah untuk
  migrasi besar; mintakan ke tim teknis kalau jumlah barisnya ribuan.</li>
</ul>
""",
    },

    # ------------------------------------------------------------------
    # Kendala umum
    # ------------------------------------------------------------------
    {
        "code": "TS-MENU-MISSING",
        "category": "TROUBLESHOOTING",
        "title": "Menu yang saya cari tidak ada di sidebar",
        "summary": "Tiga sebab paling sering, dan siapa yang bisa membukanya.",
        "icon": "i-lucide-panel-left-close",
        "keywords": "menu hilang, sidebar, tidak ada menu, akses",
        "route_prefix": "",
        "sort_order": 10,
        "content": """
<p>Sidebar disusun dari role yang Anda pegang. Kalau sebuah menu tidak
ada, biasanya salah satu dari ini:</p>

<ol>
  <li><strong>Role Anda memang tidak diberi menu itu.</strong> Admin
  keamanan mengaturnya di <em>Security &rsaquo; Menu Permissions</em>.</li>
  <li><strong>Menunya bersyarat pola kerja.</strong> Travel Request
  hanya muncul untuk pegawai site — pegawai kantor pusat tidak punya
  kepulangan dari site untuk diajukan. Kalau Anda pegawai site tapi
  menunya tetap tidak ada, berarti penempatan roster Anda belum
  terisi.</li>
  <li><strong>Modulnya belum ada halamannya.</strong> Beberapa modul
  sudah terdaftar tapi belum punya layar; ini bukan soal hak akses.</li>
</ol>

<p>Yang perlu Anda lakukan: hubungi admin dan sebutkan
<strong>nama menunya</strong> serta <strong>apa yang ingin Anda
kerjakan</strong> di sana. Menyebut yang kedua penting — kadang
pekerjaannya bisa dilakukan lewat layar lain yang sudah Anda punya.</p>
""",
    },
    {
        "code": "TS-403",
        "category": "TROUBLESHOOTING",
        "title": "Tombol Save saya ditolak",
        "summary": (
            "Membedakan penolakan hak akses dari kesalahan pengisian, "
            "dan apa yang harus disampaikan ke admin."
        ),
        "icon": "i-lucide-shield-alert",
        "keywords": "403, ditolak, forbidden, tidak bisa simpan, permission",
        "route_prefix": "",
        "sort_order": 20,
        "content": """
<p>Baca kalimat pada pesannya — ada dua jenis penolakan, dan
penanganannya berbeda:</p>

<table>
  <thead>
    <tr><th>Jenis</th><th>Ciri pesannya</th><th>Yang harus dilakukan</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Hak akses</strong></td>
      <td>Menempel di bawah form, menyebut Anda tidak berwenang</td>
      <td>Tidak ada isian yang perlu diubah — <mark>role Anda</mark> yang harus diubah admin</td>
    </tr>
    <tr>
      <td><strong>Pengisian</strong></td>
      <td>Merah, menempel tepat di bawah kolomnya</td>
      <td>Betulkan kolom itu lalu simpan lagi</td>
    </tr>
  </tbody>
</table>

<h3>1. Penolakan hak akses</h3>
<p>Pesannya menyebut bahwa Anda tidak berwenang melakukan tindakan itu.
Pesannya menempel di bawah form dan tidak hilang sendiri, supaya bisa
Anda salin. Tidak ada yang bisa Anda ubah pada isian — yang harus
diubah adalah role Anda. Sampaikan ke admin:</p>
<ul>
  <li>layar apa yang Anda buka,</li>
  <li>tombol apa yang Anda tekan,</li>
  <li>kalimat pesannya, disalin apa adanya.</li>
</ul>

<h3>2. Kesalahan pengisian</h3>
<p>Pesannya menempel pada kolom tertentu — merah, tepat di bawah kotak
isiannya. Betulkan kolom itu lalu simpan lagi. Kalau formnya bertab,
periksa juga tab lain: kolom yang bermasalah bisa saja ada di tab yang
sedang tidak terbuka.</p>

<h3>Membaca boleh, menulis tidak</h3>
<p>Beberapa layar sengaja bisa Anda buka tapi tidak bisa Anda ubah.
Melihat data untuk memeriksanya adalah hal yang berbeda dari mengubah
data — dan tombol yang hilang di layar itu memang bukan kesalahan.</p>
""",
    },
    {
        "code": "TS-DATA-MISSING",
        "category": "TROUBLESHOOTING",
        "title": "Data yang saya cari tidak muncul di tabel",
        "summary": (
            "Filter aktif, cakupan data, atau baris yang sudah dihapus "
            "— dan cara membedakan ketiganya."
        ),
        "icon": "i-lucide-search-x",
        "keywords": "data hilang, tidak muncul, kosong, filter, cari",
        "route_prefix": "",
        "sort_order": 30,
        "content": """
<p>Periksa berurutan:</p>

<ol>
  <li><strong>Filter di toolbar.</strong> Filter tersimpan selama Anda
  masih di halaman itu. Kosongkan semuanya lalu lihat lagi.</li>
  <li><strong>Kotak pencarian.</strong> Pencarian hanya melihat kolom
  tertentu, bukan seluruh isi baris. Kata yang ada di kolom catatan
  belum tentu ditemukan.</li>
  <li><strong>Halaman.</strong> Tabel menampilkan 20 baris per halaman.
  Yang Anda cari bisa saja di halaman berikutnya — urutkan kolomnya
  supaya lebih cepat ketemu.</li>
  <li><strong>Cakupan data Anda.</strong> Sebagian pengguna hanya
  melihat data perusahaan atau lokasinya sendiri. Kalau rekan Anda
  melihat baris itu dan Anda tidak, kemungkinan besar inilah
  sebabnya.</li>
  <li><strong>Barisnya sudah dihapus.</strong> Penghapusan di sistem
  ini bersifat lunak: barisnya masih ada tapi tidak lagi ditampilkan.
  Hubungi admin kalau perlu dikembalikan.</li>
</ol>

<p>Kalau setelah kelimanya data tetap tidak muncul, sebutkan ke admin
<strong>nilai unik</strong> dari baris yang Anda cari — nomor pegawai,
nomor dokumen — bukan sekadar namanya.</p>
""",
    },
]


@transaction.atomic
def seed() -> dict:
    result = {
        "categories": 0,
        "articles_created": 0,
        "articles_updated": 0,
        "articles_skipped": 0,
        "drafts": [],
        "missing_roles": [],
    }

    category_map: dict[str, HelpCategory] = {}

    for config in CATEGORIES:
        category, _ = HelpCategory.objects.update_or_create(
            code=config["code"],
            is_deleted=False,
            defaults={
                "name": config["name"],
                "description": config["description"],
                "icon": config["icon"],
                "module": config["module"],
                "sort_order": config["sort_order"],
                "is_published": True,
            },
        )

        category_map[config["code"]] = category
        result["categories"] += 1

    now = timezone.now()

    for config in ARTICLES:
        category = category_map[config["category"]]

        role = None
        role_code = config.get("role")

        if role_code:
            role = Role.objects.filter(
                code=role_code,
                is_deleted=False,
            ).first()

            if role is None:
                # Role belum diseed di tenant ini. Artikelnya tetap
                # diterbitkan tanpa pembatasan — panduan yang hilang
                # lebih merugikan daripada panduan admin yang terbaca
                # pegawai biasa, dan isinya bukan rahasia.
                result["missing_roles"].append(role_code)

        existing = HelpArticle.objects.filter(
            code=config["code"],
            is_deleted=False,
        ).first()

        # Artikel yang menjelaskan fitur yang **belum ada kodenya**
        # diseed sebagai DRAFT. Tulisannya sudah jadi dan sudah duduk di
        # tenant supaya bisa dibaca dan disunting dari layar Help
        # Articles, tapi portal hanya menampilkan yang PUBLISHED — jadi
        # tidak ada pembaca yang mendapat panduan untuk tombol yang belum
        # ada. Panduan yang percaya diri salah lebih merugikan daripada
        # panduan yang belum ada.
        status = config.get("status", HelpArticleStatus.PUBLISHED)

        if status != HelpArticleStatus.PUBLISHED:
            result["drafts"].append(config["code"])

        payload = {
            "category": category,
            "title": config["title"],
            "summary": config["summary"],
            "content": config["content"].strip(),
            "icon": config.get("icon", ""),
            "keywords": config.get("keywords", ""),
            "route_prefix": config.get("route_prefix", ""),
            "sort_order": config.get("sort_order", 0),
            "role": role,
            "status": status,
            "published_at": (
                now
                if status == HelpArticleStatus.PUBLISHED
                else None
            ),
        }

        if existing is None:
            HelpArticleService.create(
                data={"code": config["code"], **payload},
                user=None,
            )
            result["articles_created"] += 1
            continue

        # Artikel yang sudah disunting orang **tidak** ditulis ulang.
        # Seed adalah titik awal, bukan pemilik isinya — menimpanya
        # berarti pekerjaan penulisnya hilang tiap kali seseorang
        # menjalankan perintah ini.
        if existing.updated_by_id is not None:
            result["articles_skipped"] += 1
            continue

        HelpArticleService.update(
            instance=existing,
            data=payload,
            user=None,
        )
        result["articles_updated"] += 1

    result["missing_roles"] = sorted(set(result["missing_roles"]))

    return result
