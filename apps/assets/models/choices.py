"""
Kosakata tertutup Asset Management.

Enum, bukan master referensi, karena aturan modul membacanya — dan
tidak ada satu baris kode pun yang boleh bergantung pada isi master
yang bisa diganti tenant (`docs/claude/assets.md` §8, §16).

**Nilai yang belum punya jalan tidak dibuat dulu.** Status RETIRED/LOST
masuk bersama tahap yang membuka jalannya — nilai tanpa jalan masuk/keluar
membuat filter dan laporan berbohong.
"""

from django.db import models


class AssetStatus(models.TextChoices):
    """
    Lifecycle **register**, bukan keadaan custody dan bukan kondisi.

    `ACTIVE` tidak berkata apa pun tentang siapa pemegangnya — itu
    jawaban `AssetCustody`. ACTIVE + STORAGE dan (kelak) ACTIVE +
    EMPLOYEE sama-sama sah.
    """

    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"


class AssetCondition(models.TextChoices):
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    DAMAGED = "DAMAGED", "Damaged"
    UNSERVICEABLE = "UNSERVICEABLE", "Unserviceable"


# Kondisi yang layak diserahkan lewat Assignment (ASSET-4). DAMAGED dan
# UNSERVICEABLE tetap boleh **kembali** ke STORAGE, tetapi tidak ditawarkan
# dan tidak bisa diajukan untuk diserahkan lagi sampai kondisinya dicatat
# layak (inspeksi, kelak maintenance). Kondisi dan custody adalah sumbu
# terpisah — aturan ini milik Assignment, bukan custody.
ASSIGNABLE_CONDITIONS = (
    AssetCondition.GOOD,
    AssetCondition.FAIR,
)


class CustodyType(models.TextChoices):
    """
    Tiga jenis custody kanonik (§8).

    Bentuk tiap jenis dijaga `ck_assets_custody_holder_shape`:
    EMPLOYEE = pegawai, tanpa department/PIC; ORGANIZATION = department
    wajib, PIC opsional, tanpa pegawai; STORAGE = tanpa pemegang sama
    sekali. STORAGE selalu diperbolehkan untuk kategori apa pun — ia
    keadaan internal pemilik, bukan pilihan kategori.
    """

    EMPLOYEE = "EMPLOYEE", "Employee"
    ORGANIZATION = "ORGANIZATION", "Organization"
    STORAGE = "STORAGE", "Storage"


class ConditionSource(models.TextChoices):
    REGISTRATION = "REGISTRATION", "Registration"
    INSPECTION = "INSPECTION", "Inspection"
    # Kondisi yang dicatat saat serah terima selesai — hanya bila
    # dikirim eksplisit; Assignment tidak pernah mengubah kondisi diam-diam.
    HANDOVER = "HANDOVER", "Handover"
    # Kondisi saat aset kembali ke penyimpanan — **selalu** dicatat saat
    # Return selesai (wajib diisi), juga bila nilainya sama.
    RETURN = "RETURN", "Return"
    # Kondisi saat Transfer selesai — **selalu** dicatat (wajib diisi).
    TRANSFER = "TRANSFER", "Transfer"


class AssignmentStatus(models.TextChoices):
    """
    Lifecycle dokumen Assignment (`docs/claude/assets.md` §16).

    Nilainya mengikuti `BaseTransactionService` (huruf besar), ditambah
    COMPLETED. **Approval tidak memindahkan custody** — hanya COMPLETED.
    Aset dipesan (reserved) selama SUBMITTED dan APPROVED.
    """

    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


# Status yang memesan aset — satu-satunya definisi "in-flight" per jenis
# dokumen. Pemesanannya sendiri disimpan `AssetOperationReservation`;
# konstanta ini dipakai service (kapan memesan/melepas) dan pemeriksaan
# integritas (dokumen berjalan ⇔ pemesanan terbuka).
ASSIGNMENT_RESERVING_STATUSES = (
    AssignmentStatus.SUBMITTED,
    AssignmentStatus.APPROVED,
)


class ReturnStatus(models.TextChoices):
    """
    Lifecycle dokumen Return — sama persis dengan Assignment: approval
    tidak memindahkan custody, hanya COMPLETED. Dipesan selama SUBMITTED
    dan APPROVED.
    """

    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


RETURN_RESERVING_STATUSES = (
    ReturnStatus.SUBMITTED,
    ReturnStatus.APPROVED,
)


class ReturnReason(models.TextChoices):
    """Alasan pengembalian (`docs/claude/assets.md` §11)."""

    END_OF_USE = "END_OF_USE", "End of use"
    # Pegawai keluar. Kelak dibuat dari offboarding — tetap lewat
    # lifecycle Return yang sama, bukan menutup custody langsung (§19).
    SEPARATION = "SEPARATION", "Separation"
    REPLACEMENT = "REPLACEMENT", "Replacement"
    DAMAGE = "DAMAGE", "Damage"
    OTHER = "OTHER", "Other"


class AssetOperationType(models.TextChoices):
    """
    Jenis dokumen operasional yang boleh memesan aset lewat
    `AssetOperationReservation` — satu per dokumen pergerakan, semantiknya
    tidak tumpang tindih:

    * ASSIGNMENT — STORAGE → pemakaian;
    * RETURN — pemakaian → STORAGE;
    * TRANSFER — pemakaian → pemakaian, atau STORAGE → STORAGE.
    """

    ASSIGNMENT = "ASSIGNMENT", "Assignment"
    RETURN = "RETURN", "Return"
    TRANSFER = "TRANSFER", "Transfer"


class ReservationRelease(models.TextChoices):
    """Kenapa pemesanan dilepas — status yang dicapai dokumennya."""

    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    REJECTED = "REJECTED", "Rejected"
    # Dikembalikan engine workflow untuk diperbaiki → dokumen turun ke DRAFT.
    RETURNED_TO_DRAFT = "RETURNED_TO_DRAFT", "Returned to draft"


class TransferStatus(models.TextChoices):
    """Lifecycle dokumen Transfer — sama dengan Assignment/Return."""

    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


TRANSFER_RESERVING_STATUSES = (
    TransferStatus.SUBMITTED,
    TransferStatus.APPROVED,
)


class TransferReason(models.TextChoices):
    """Alasan Transfer (§10). Bukan penentu semantik — itu dari asal/tujuan."""

    REASSIGNMENT = "REASSIGNMENT", "Reassignment"
    PIC_CHANGE = "PIC_CHANGE", "PIC change"
    RELOCATION = "RELOCATION", "Relocation"
    REORGANIZATION = "REORGANIZATION", "Reorganization"
    OTHER = "OTHER", "Other"
