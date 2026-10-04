"""
Kebijakan cuti bawaan.

Dua kelompok, dan pembedanya `uses_balance`
-------------------------------------------
**Bersaldo** — hari ini hanya ``ANNUAL-STD``: 12 hari setelah 12 bulan
bekerja terus-menerus, angka yang bisa ditunjuk ke UU Ketenagakerjaan.
Dari sinilah `LeaveBalance` terbit, dan seluruh alur Go-Live, saldo
awal, serta carry over bergantung padanya.

**Tanpa saldo** — cuti menikah, melahirkan, duka, dan seterusnya.
Haknya melekat pada **kejadian**, bukan pada tahun, jadi tidak ada
angka yang perlu disimpan per pegawai per tahun. Yang diseed di sini
batas dan pemeriksaannya, dan keduanya dinilai saat cutinya diajukan
(`apps/hr/api/leave/rules.py`).

Kenapa yang tanpa saldo tetap perlu diseed
------------------------------------------
Sebelum ini jenis cuti selain tahunan **tidak punya aturan sama
sekali**: siapa pun bisa mengajukan cuti menikah tujuh hari, tiga kali
setahun, tanpa satu pun dokumen — dan tidak ada satu baris pun di
sistem yang bisa ditunjuk sebagai batasnya. Angkanya di bawah bukan
karangan: 3 hari menikah, 2 hari menikahkan/mengkhitankan anak, 1 hari
baptis anak, 2 hari keluarga inti meninggal — semuanya pasal 93 ayat
(4) UU Ketenagakerjaan.

Yang **tidak** diberi angka juga disengaja. Sakit, melahirkan,
keguguran, haji, dan ibadah keagamaan `max_days`-nya dikosongkan:
lamanya ditentukan surat dokter atau keterangan resmi, bukan oleh
perusahaan. Angka karangan di master lebih berbahaya daripada tidak ada
angka — orang menganggapnya sudah divalidasi. Itu pelajaran dari
``SICK-STD`` yang sempat diseed 30 hari dan ditarik; ia kembali di
sini, tapi sebagai aturan **tanpa saldo dan tanpa kuota**.

``BIG`` (Cuti Besar) sengaja **tidak** diseed sama sekali — bersaldo
atau per kejadian adalah keputusan yang belum diambil, dan menebaknya
berarti tenant yang memakainya harus membongkar data yang sudah
terbit.

Semuanya titik awal, bukan kebijakan. Tenant yang jatah pegawai
site-nya berbeda tinggal menyalin barisnya dan mengisi Employee Group —
`LeavePolicyResolver` memenangkan aturan yang lebih khusus tanpa perlu
menghapus yang umum.
"""

from django.db import transaction

from apps.administration.models import LeavePolicy, LeaveType
from apps.administration.models.references.leave_policy import (
    LeaveAccrual,
    LeaveHistoryAction,
    LeavePeriodBasis,
)


POLICIES = [
    # ------------------------------------------------------------------
    # Bersaldo
    # ------------------------------------------------------------------
    {
        "code": "ANNUAL-STD",
        "name": "Cuti Tahunan — Standar",
        "leave_type": "ANNUAL",
        "uses_balance": True,
        "entitlement_days": 12,
        "eligible_after_months": 12,
        "prorate_first_period": True,
        "accrual": LeaveAccrual.UPFRONT,
        "period_basis": LeavePeriodBasis.CALENDAR_YEAR,
        "allow_carry_over": False,
        "description": (
            "12 hari kerja setelah 12 bulan bekerja terus-menerus, "
            "sesuai UU Ketenagakerjaan. Periode pertama diprorata."
        ),
    },

    # ------------------------------------------------------------------
    # Tanpa saldo — lamanya ditentukan keterangan resmi
    # ------------------------------------------------------------------
    {
        "code": "SICK-STD",
        "name": "Cuti Sakit — Standar",
        "leave_type": "SICK",
        "uses_balance": False,
        "max_days": None,
        "per_event": False,
        "document_required": False,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Tanpa kuota hari: undang-undang tidak mengatur jumlah "
            "hari sakit per tahun, melainkan skala upah selama sakit "
            "berkepanjangan. Riwayat tahun berjalan ditampilkan supaya "
            "pola yang perlu ditindaklanjuti terlihat — bukan untuk "
            "menolaknya."
        ),
    },
    {
        "code": "MATERNITY-STD",
        "name": "Cuti Melahirkan — Standar",
        "leave_type": "MATERNITY",
        "uses_balance": False,
        "max_days": None,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Lamanya mengikuti surat keterangan dokter atau bidan, "
            "bukan angka di master. Per kejadian: kelahiran berikutnya "
            "berhak penuh lagi."
        ),
    },
    {
        "code": "MISCARRIAGE-STD",
        "name": "Cuti Keguguran — Standar",
        "leave_type": "MISCARRIAGE",
        "uses_balance": False,
        "max_days": None,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Lamanya mengikuti surat keterangan dokter atau bidan."
        ),
    },
    {
        "code": "PATERNITY-STD",
        "name": "Cuti Suami/Istri Melahirkan — Standar",
        "leave_type": "PATERNITY",
        "uses_balance": False,
        "max_days": 2,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "2 hari, pasal 93 ayat (4) UU Ketenagakerjaan."
        ),
    },

    # ------------------------------------------------------------------
    # Tanpa saldo — berkuota, pasal 93 ayat (4)
    # ------------------------------------------------------------------
    {
        "code": "MARRIAGE-STD",
        "name": "Cuti Menikah — Standar",
        "leave_type": "MARRIAGE",
        "uses_balance": False,
        "max_days": 3,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "3 hari, pasal 93 ayat (4) UU Ketenagakerjaan. Riwayat "
            "diperiksa tapi tidak menolak — pernikahan kedua tetap "
            "berhak, dan yang bisa memastikannya cuma orang yang "
            "memegang surat nikahnya."
        ),
    },
    {
        "code": "CHILD-MARRIAGE-STD",
        "name": "Cuti Menikahkan Anak — Standar",
        "leave_type": "CHILD_MARRIAGE",
        "uses_balance": False,
        "max_days": 2,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": "2 hari, pasal 93 ayat (4).",
    },
    {
        "code": "CHILD-CIRCUMCISION-STD",
        "name": "Cuti Khitan Anak — Standar",
        "leave_type": "CHILD_CIRCUMCISION",
        "uses_balance": False,
        "max_days": 2,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": "2 hari, pasal 93 ayat (4).",
    },
    {
        "code": "CHILD-BAPTISM-STD",
        "name": "Cuti Baptis Anak — Standar",
        "leave_type": "CHILD_BAPTISM",
        "uses_balance": False,
        "max_days": 1,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": "1 hari, pasal 93 ayat (4).",
    },
    {
        "code": "BEREAVEMENT-STD",
        "name": "Cuti Kedukaan — Standar",
        "leave_type": "BEREAVEMENT",
        "uses_balance": False,
        "max_days": 2,
        "per_event": True,
        "document_required": False,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "2 hari untuk keluarga inti, pasal 93 ayat (4). Dokumen "
            "tidak diwajibkan: surat keterangan kematian lazim baru "
            "keluar berhari-hari kemudian, dan orang yang sedang "
            "berduka tidak boleh dihalangi mengajukan cutinya."
        ),
    },

    # ------------------------------------------------------------------
    # Tanpa saldo — lamanya dari keterangan resmi
    # ------------------------------------------------------------------
    {
        "code": "HAJJ-STD",
        "name": "Cuti Ibadah Haji",
        "leave_type": "HAJJ",
        "uses_balance": False,
        "max_days": None,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Lamanya mengikuti jadwal keberangkatan resmi. Riwayat "
            "diperiksa karena hak ini lazimnya sekali selama bekerja — "
            "tapi ditandai, bukan ditolak."
        ),
    },
    {
        "code": "RELIGIOUS-STD",
        "name": "Cuti Keagamaan / Ibadah",
        "leave_type": "RELIGIOUS",
        "uses_balance": False,
        "max_days": None,
        "per_event": True,
        "document_required": True,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Untuk ibadah yang diwajibkan agamanya di luar haji."
        ),
    },
    {
        "code": "SPECIAL-STD",
        "name": "Cuti Khusus",
        "leave_type": "SPECIAL",
        "uses_balance": False,
        "max_days": None,
        "per_event": False,
        "document_required": False,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Penampung keadaan yang tidak masuk jenis mana pun. "
            "Sengaja tanpa batas — yang membatasinya persetujuan, "
            "bukan angka; riwayat tahun berjalan ditampilkan supaya "
            "pemakaian yang menumpuk tetap terlihat."
        ),
    },
    {
        "code": "UNPAID-STD",
        "name": "Cuti Tanpa Upah",
        "leave_type": "UNPAID",
        "uses_balance": False,
        "max_days": None,
        "per_event": False,
        "document_required": False,
        "history_check": True,
        "history_action": LeaveHistoryAction.REVIEW,
        "description": (
            "Tidak memotong saldo apa pun karena memang tidak dibayar. "
            "Riwayat tahun berjalan ditampilkan — pemakaian yang "
            "menumpuk adalah hal pertama yang ditanyakan saat "
            "perpanjangan kontrak."
        ),
    },
]


# Kolom milik cuti bersaldo yang **harus** dinolkan pada aturan tanpa
# saldo. Bukan kerapian: baris `SICK-STD` yang pernah diseed 30 hari
# masih ada di tenant lama, dan `update_or_create` hanya menimpa kunci
# yang disebut. Tanpa penormalan ini ia hidup kembali membawa
# `entitlement_days = 30` — angka yang memang tidak berpengaruh lagi
# (gerbangnya di `LeaveEntitlementCalculator`), tapi terbaca di layar
# sebagai kuota yang berlaku, dan yang membacanya tidak punya cara tahu
# bahwa ia mati.
NON_BALANCE_RESET = {
    "entitlement_days": 0,
    "eligible_after_months": 0,
    "prorate_first_period": False,
    "accrual": LeaveAccrual.UPFRONT,
    "period_basis": LeavePeriodBasis.CALENDAR_YEAR,
    "allow_carry_over": False,
    "carry_over_max_days": None,
    "carry_over_expiry_months": None,
    "carry_over_reminder_days": "",
}


@transaction.atomic
def seed() -> dict:
    count = 0
    balance_count = 0
    missing = []

    for config in POLICIES:
        leave_type = LeaveType.objects.filter(
            code=config["leave_type"],
            is_deleted=False,
        ).first()

        if leave_type is None:
            missing.append(config["leave_type"])

            continue

        defaults = {
            key: value
            for key, value in config.items()
            if key not in {"code", "leave_type"}
        }

        if not defaults.get("uses_balance", True):
            # Nilai eksplisit di POLICIES tetap menang — penormalan ini
            # cuma mengisi kolom yang tidak disebut.
            for key, value in NON_BALANCE_RESET.items():
                defaults.setdefault(key, value)
        else:
            balance_count += 1

        defaults["leave_type"] = leave_type

        # Wajib disebut: `update_or_create` ikut menemukan baris yang
        # sudah di-soft-delete (`SICK-STD` pernah ditarik lewat
        # OBSOLETE_CODES), dan defaults yang tidak menyebutkannya akan
        # memperbarui isinya tanpa pernah menghidupkannya kembali —
        # seed melaporkan berhasil sementara aturannya tetap tidak ada
        # di layar mana pun.
        defaults["is_deleted"] = False
        defaults["is_active"] = True

        LeavePolicy.objects.update_or_create(
            company=None,
            code=config["code"],
            defaults=defaults,
        )

        count += 1

    return {
        "policies": count,
        "balance_policies": balance_count,
        "non_balance_policies": count - balance_count,
        "missing_leave_types": missing,
        "retired": 0,
    }
