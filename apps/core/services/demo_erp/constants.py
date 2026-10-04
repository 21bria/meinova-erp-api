"""
Konstanta kepemilikan dataset Meinova ERP.

Kepemilikan tidak pernah disimpulkan dari rentang PK, tanggal buat, atau
"semua baris di tabel ini". Sebuah baris milik dataset ini hanya kalau
ia membawa penanda di bawah **dan** duduk di perusahaan milik dataset.
"""

from __future__ import annotations

from datetime import date


#: DEMO-1B disetujui 28 Sep 2026: baseline boleh diterapkan (berhenti di REVIEW).
APPLY_ENABLED = True

#: Satu-satunya tenant yang boleh disentuh perintah ini. Tenant lain
#: ditolak, bukan hanya `public`.
ALLOWED_TENANTS = frozenset({"demo"})

DEFAULT_SOURCE = "docs/demo-data/Meinova_ERP_Demo_Data_Blueprint_UPDATED.xlsx"

#: Tanggal acuan workbook (lembar 04). Label kedaluwarsa kontrak dihitung
#: ERP dari tanggal ini, tidak pernah disimpan.
REFERENCE_DATE = date(2026, 9, 28)

#: Tahun buku yang dibutuhkan payroll Agustus–September 2026.
FISCAL_YEAR = 2026

# ----------------------------------------------------------------------
# Penanda kepemilikan
# ----------------------------------------------------------------------

DATASET_KEY = "DEMO-ERP"

#: Perusahaan milik dataset ini (B1). Kodenya dari workbook lembar 01.
OWNED_COMPANY_CODES = ("GRP", "MMN", "MIN")

#: Company tidak punya kolom catatan. Penandanya alamat surel domain
#: fiktif milik dataset ini — nilai yang memang harus diisi untuk
#: perusahaan peragaan, dan tidak mungkin tertabrak data sungguhan.
COMPANY_EMAIL_DOMAIN = "demo-erp.meinova.example"

#: Pegawai: nomor dari workbook + catatan berawalan penanda.
EMPLOYEE_NUMBER_PATTERN = r"^EMP\d{3}$"
EMPLOYEE_NOTE_PREFIX = "[DEMO-ERP:"

#: Akun login pegawai dataset ini.
USERNAME_PREFIX = "demoerp."

#: Dokumen (cuti, izin, lembur, run payroll) membawa kunci skenarionya
#: di catatan: `[DEMO-ERP:LV-001]`.
DOCUMENT_NOTE_PREFIX = "[DEMO-ERP:"

#: Presensi & tap mentah (DEMO-1B).
ATTENDANCE_EXTERNAL_PREFIX = "DEMOERP-ATT-"
ATTENDANCE_BATCH = "DEMOERP-DEVICE"

# ----------------------------------------------------------------------
# Yang dilindungi
# ----------------------------------------------------------------------

#: Perusahaan milik dataset lain (B1): tidak pernah ditulis, tidak pernah
#: dijadikan tujuan pemetaan.
#: Kode company peragaan lama. Sejak DEMO-1F ketiganya **dibuang** dari
#: tenant `demo`; kode tetap di sini sebagai kode terlarang: dataset yang
#: menyebutnya ditolak, dan perencana menolak tenant yang memuat company di
#: luar OWNED_COMPANY_CODES.
PROTECTED_COMPANY_CODES = ("MNI", "MMR", "MLS")

#: Awalan pegawai yang **tidak pernah** milik dataset ini: pemeran HR-DEMO-1..3
#: dan jalur uji teknis TRL. Sejak DEMO-1D (28 Sep 2026) keduanya sudah dibuang
#: dari tenant `demo` (`purge_legacy_hr_demo`), jadi baseline tidak mengharapkan
#: satu pun baris berawalan ini. Pagarnya tetap: DEMOERP tidak boleh mengklaim,
#: membongkar, atau menimpa pegawai berawalan ini bila muncul lagi.
PROTECTED_EMPLOYEE_PREFIXES = ("HO", "SGA", "LOK", "BOD", "TRL")

#: Awalan kepemilikan presensi milik HR-DEMO-2 — tidak boleh tertimpa.
PROTECTED_ATTENDANCE_PREFIXES = ("SEED-ATT-", "DEV-ATT-", "CLOSE-")

# ----------------------------------------------------------------------
# Workbook
# ----------------------------------------------------------------------

REQUIRED_SHEETS = (
    "00_Demo_Summary",
    "01_Companies",
    "02_Org_Structure",
    "03_Employees",
    "04_Contracts_Action",
    "05_Calendar_Roster",
    "06_Roster_Assignment",
    "07_Leave_Workflow",
    "08_Attendance_2M",
    "09_Payroll_2M",
    "10_Finance_Posting",
    "11_Demo_Test_Scenarios",
    "12_Role_Data_Scope",
)
