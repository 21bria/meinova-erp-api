"""
Alamat email akun peragaan — satu daftar, dipakai semua seed.

Akun peragaan dibentuk **dua** berkas: `demo_workforce.py` (panggung
untuk dokumen, sebelas akun) dan `demo_employees.py` (tenant untuk
diisi tangan, dua puluh enam akun). Keduanya menyusun orang yang sama
dengan username yang sama persis, dan sebelum ini keduanya juga
menurunkan email-nya sendiri-sendiri lewat `f"{username}@example.test"`.

Selama polanya cuma satu baris f-string, dua salinan itu tidak terasa.
Begitu akunnya harus memakai alamat sungguhan supaya email approval
bisa dibuktikan sampai ke kotak masuk, dua salinan berarti seed mana
yang dijalankan terakhir menentukan siapa yang menerima surat — dan
bedanya tidak terlihat di layar mana pun. Karena itu daftarnya
dipindahkan ke sini dan semuanya membacanya.

**Hanya email yang diatur di sini.** Username, nomor pegawai, role,
garis pelaporan, dan penempatan tetap milik seed masing-masing; berkas
ini tidak membentuk user, employee, maupun role satu pun.

Bentuk alamatnya subaddress (`+tag`) pada satu kotak masuk sungguhan:
tiap akun tetap bisa dibedakan penerimanya dan bisa disaring sendiri,
tanpa membuat akun email baru untuk tiap peran.

**Seluruh akun `demo.*` ada di daftar ini**, bukan cuma pemegang meja
alur persetujuan. Versi sebelumnya hanya memetakan tiga belas meja dan
membiarkan sisanya jatuh ke `@example.test` — domain yang memang tidak
menerima surat. Akibatnya baru terlihat saat sebuah dokumen berpindah
ke approver yang tidak pernah masuk daftar: notifikasinya terkirim,
laporannya berhasil, dan tidak ada satu pun surat yang bisa dibuka.
Karena itu daftarnya sekarang menutup seluruh roster, dan akun
peragaan baru yang lupa didaftarkan pun tetap mendarat di kotak masuk
sungguhan lewat `demo_email()` — bukan di domain buntu.
"""

from __future__ import annotations


# Kotak masuk sungguhan yang dipakai memeriksa email peragaan.
# Alamatnya dibentuk subaddress: `<INBOX_LOCAL>+<alias>@<INBOX_DOMAIN>`.
INBOX_LOCAL = "brya.seran"
INBOX_DOMAIN = "gmail.com"

# Awalan username akun peragaan. Dipakai `demo_email()` untuk memutuskan
# apakah sebuah akun berhak atas alamat peragaan — akun sistem
# (`admin`) tidak berawalan ini dan karena itu tidak pernah disentuh.
USERNAME_PREFIX = "demo."


def demo_address(alias: str) -> str:
    """Alamat subaddress untuk satu alias."""
    return f"{INBOX_LOCAL}+{alias}@{INBOX_DOMAIN}"


# username → alias subaddress.
#
# Kuncinya username, bukan nomor pegawai: yang memegang email adalah
# akun, dan nomor pegawai tidak ada di tabel user. Nomor pegawainya
# ditulis di komentar supaya daftar ini masih bisa dicocokkan dengan
# `USERS`/`PEOPLE` di dua seed pembentuknya.
#
# Aliasnya **tidak** selalu sama dengan potongan username. Empat meja
# pertama alur cuti kantor pusat memakai alias peran (`employee`,
# `supervisor`, …) karena alamat itu sudah dipakai di trial email yang
# sedang berjalan; menggantinya berarti membuang jejak surat yang sudah
# masuk. Yang lain memakai potongan usernamenya sendiri.
DEMO_EMAIL_ALIASES = {
    # ------------------------------------------------------------------
    # Kantor pusat Jakarta — rantai alur `HR-HO-LEAVE`
    # ------------------------------------------------------------------

    # HO003 Bimo Nugroho — pengaju cuti kantor pusat.
    "demo.hostaff": "employee",

    # HO005 Farah Anindita — atasan langsung HO003, meja #1.
    "demo.homanager": "supervisor",

    # HO002 Hesti Rahayu — HR-ADMIN kantor pusat, meja #2.
    "demo.hradmin": "hradmin",

    # HO001 Sarah Wibowo — HR-MANAGER kantor pusat, meja #3.
    "demo.hrmanager": "hrmanager",

    # HO004 Clara Wijaya — HRGA, meja penerbitan tiket alur site.
    "demo.hrga": "hrga",

    # HO006 Adrian Mahendra — GM, puncak garis pelaporan kantor pusat.
    # Ikut karena `department_head` dan `manager` level 2 bisa jatuh
    # kepadanya; meja yang tidak pernah bisa dibuktikan penerimanya
    # sama saja dengan meja yang tidak diuji.
    "demo.gm": "gm",

    # HO007 Rangga Pratomo — staf Accounting, bawahan HO005.
    "demo.accstaff": "accstaff",

    # HO008 Yulia Kartika — staf GA, bawahan HO001.
    "demo.gastaff": "gastaff",

    # ------------------------------------------------------------------
    # Site Sagea (POH) — rantai alur `HR-LEAVE-SITE` / `HR-TR-SITE`
    # ------------------------------------------------------------------

    # SGA002 Ahmad Sudrajat — pengaju cuti/TR site.
    "demo.sitestaff": "sitestaff",

    # SGA003 Bayu Prakoso — ADMIN-SECTION, meja #1.
    "demo.siteadmin": "adminsection",

    # SGA006 Eko Prasetyo — HR-ADMIN site, meja #2.
    "demo.sitehradmin": "sitehradmin",

    # SGA001 Rinaldo Saputra — atasan seluruh meja site, meja #3.
    "demo.sitespv": "sitesupervisor",

    # SGA004 Citra Halimah — HR-MANAGER site, meja #4. Pemegang role
    # yang **sama** dengan HO001 di lokasi berbeda; inilah pasangan
    # yang membuktikan `approver_scope=location` benar-benar memisah.
    "demo.sitehrmanager": "sitehrmanager",

    # SGA005 Dedi Kurniawan — KTT, meja #5.
    "demo.ktt": "ktt",

    # SGA007 Ferry Wibisono — supervisor Plant, atasan LOK005/LOK006.
    "demo.plantspv": "plantspv",

    # SGA010 Yusuf Maulana — supervisor Hauling, atasan LOK002–LOK004.
    "demo.haulingspv": "haulingspv",

    # SGA008 Gilang Ramadhan — Survey, atasan LOK008.
    "demo.surveyor": "surveyor",

    # SGA009 Novita Sari — HSE, department tanpa kepala.
    "demo.hse": "hse",

    # ------------------------------------------------------------------
    # Site Sagea (tenaga lokal) — tanpa POH, tanpa roster
    # ------------------------------------------------------------------

    # LOK001 Rustam Hasan — ADMIN-DEPARTMENT, cadangan meja #1.
    "demo.deptadmin": "admindepartment",

    # LOK002 Jufri Sangaji — crew hauling, pengaju cuti jalur lokal.
    "demo.opr1": "opr1",

    # LOK003 Rahmat Tidore — crew hauling.
    "demo.opr2": "opr2",

    # LOK004 Sultan Ahmad — crew hauling, kontraknya sudah lewat.
    "demo.opr3": "opr3",

    # LOK005 Umar Sahdan — crew Plant, section Mechanical.
    "demo.mech1": "mech1",

    # LOK006 Taufik Ode — crew Plant, section Electrical.
    "demo.elec1": "elec1",

    # LOK007 Hamid Latif — Logistics.
    "demo.log1": "log1",

    # LOK008 Nurlela Wahab — Survey, pegawai lokal terbaru.
    "demo.survey2": "survey2",

    # ------------------------------------------------------------------
    # Organization Scope — dibentuk `seed_demo_org_scope`
    # ------------------------------------------------------------------
    #
    # Keempatnya bukan pemegang meja alur persetujuan; yang diuji lewat
    # akun ini seberapa luas datanya, bukan surat yang diterimanya.
    # Tetap didaftarkan supaya alamatnya bisa ditebak dan disaring, dan
    # supaya tidak ada akun peragaan yang bentuk alamatnya bergantung
    # pada jalur cadangan.

    # BOD001 Wirawan Adisurya — Presiden Direktur, cakupan seluruh grup.
    "demo.bod1": "bod1",

    # BOD002 Lestari Handayani — Direktur Operasi, cakupan seluruh grup.
    "demo.bod2": "bod2",

    # HO009 Gunawan Prasetyo — GM kantor pusat, cakupan MMR + MLS.
    "demo.gmho": "gmho",

    # SGA011 Bayu Nugraha — GM site Sagea, cakupan sebatas lokasinya.
    "demo.gmsite": "gmsite",
}


# username → alamat email lengkap. Diturunkan dari aliasnya supaya
# bentuk alamat hanya ditulis di satu tempat.
DEMO_EMAILS = {
    username: demo_address(alias)
    for username, alias in DEMO_EMAIL_ALIASES.items()
}


def derive_alias(username: str) -> str:
    """
    Alias cadangan untuk akun peragaan yang belum didaftarkan.

    Dipakai supaya akun peragaan baru yang lupa ditambahkan ke
    `DEMO_EMAIL_ALIASES` tetap mendarat di kotak masuk sungguhan.
    Titik dan garis dibuang: subaddress yang mengandung titik dibaca
    berbeda oleh sebagian penyaring, dan alias yang tidak bisa disaring
    sama saja dengan alias yang tidak ada.
    """
    tail = username[len(USERNAME_PREFIX):] if username.startswith(USERNAME_PREFIX) else username

    return "".join(char for char in tail.lower() if char.isalnum()) or "demo"


def demo_email(username: str) -> str:
    """
    Alamat email untuk satu akun peragaan.

    Yang tidak terdaftar tetap mendapat alamat kotak masuk sungguhan,
    aliasnya diturunkan dari usernamenya. Fungsi ini hanya dipanggil
    seed akun peragaan — akun sistem (`admin`) tidak pernah lewat sini
    — jadi tidak ada akun peragaan yang bisa diam-diam kembali ke
    domain buntu hanya karena lupa didaftarkan.
    """
    if username in DEMO_EMAILS:
        return DEMO_EMAILS[username]

    return demo_address(derive_alias(username))
