"""
Satu baris keputusan — dan satu kotak tanda tangan di formulir tercetak.

Seluruh barisnya dibuat di depan saat dokumen diajukan, bukan satu per
satu saat gilirannya tiba: formulir yang dicetak harus memperlihatkan
semua kotak sejak awal, termasuk yang belum diisi. Approver-nya pun
dibekukan pada saat pengajuan — mutasi atasan minggu depan tidak boleh
mengubah siapa yang seharusnya menandatangani dokumen yang sudah
berjalan.
"""

from django.conf import settings
from django.db import models

from .delegation import WorkflowDelegation
from .instance import WorkflowInstance
from .step import WorkflowStep


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"

    # Dikembalikan ke pengaju untuk diperbaiki.
    RETURNED = "returned", "Returned"

    # Approver tidak ketemu pada step tidak wajib, atau orangnya sudah
    # menyetujui di step sebelumnya. Dicatat, bukan dihilangkan: kotak
    # tanda tangan yang kosong di formulir harus bisa dijelaskan.
    SKIPPED = "skipped", "Skipped"

    CANCELLED = "cancelled", "Cancelled"


class AssignmentType(models.TextChoices):
    """Dari mana nama approver ini datang. Untuk ditampilkan, bukan logika."""

    USER = "user", "Specific User"
    ROLE = "role", "Role Holder"
    POSITION = "position", "Position Hierarchy"
    MANAGER = "manager", "Direct Manager"
    DEPARTMENT_HEAD = "department_head", "Department Head"
    FALLBACK_ROLE = "fallback_role", "Fallback Role"


class WorkflowApproval(models.Model):
    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.CASCADE,
        related_name="approvals",
    )

    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        related_name="approvals",
    )

    # Disalin dari step, bukan dibaca lewat relasi: judul kotak tanda
    # tangan di dokumen lama harus tetap seperti saat dokumen itu
    # diajukan, walau alurnya dirombak tahun depan.
    name = models.CharField(max_length=200, blank=True, default="")

    sequence = models.PositiveIntegerField(default=1)

    # ------------------------------------------------------------------
    # Approver
    # ------------------------------------------------------------------

    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_approvals",
        help_text="Kosong = approver tidak berhasil ditemukan.",
    )

    # Pegawai di balik akun itu. Disimpan terpisah karena formulir
    # tercetak menulis nama pegawai dan jabatannya, bukan username.
    approver_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_approvals",
    )

    # Siapa yang benar-benar menekan tombolnya. Berbeda dari `approver`
    # kalau keputusannya diambil delegate — dan siapa yang mewakili
    # harus tercatat, bukan disamarkan jadi seolah atasannya sendiri
    # yang menyetujui.
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_actions",
    )

    acted_via_delegation = models.ForeignKey(
        WorkflowDelegation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approvals",
        help_text=(
            "Surat kuasa yang dipakai. Terisi hanya kalau yang "
            "memutuskan bukan approver-nya sendiri."
        ),
    )

    # ------------------------------------------------------------------
    # Keadaan
    # ------------------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )

    is_required = models.BooleanField(default=True)

    comment = models.TextField(blank=True, default="")

    acted_at = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Asal-usul approver
    # ------------------------------------------------------------------

    assignment_type = models.CharField(
        max_length=30,
        choices=AssignmentType.choices,
        blank=True,
        default="",
    )

    # Kalimat penjelas dari resolver: dari mana nama ini datang, atau
    # (saat gagal) kolom mana yang masih kosong. Selalu terisi —
    # "kenapa yang harus approve orang ini" adalah pertanyaan pertama
    # yang sampai ke HR.
    #
    # **TextField, bukan CharField(255).** Sejak cadangan boleh
    # berjenjang (`WorkflowStepFallback`), alasannya menyebut **setiap**
    # tingkat yang sudah dicoba beserta cakupannya — dan rantai tiga
    # tingkat dengan nama lokasi yang wajar sudah menembus 285 karakter.
    # Gagalnya di tempat terburuk: `DataError` saat **submit**, jadi
    # pengajuan ditolak seluruhnya oleh kolom penjelas yang tidak
    # menentukan apa pun. Memotongnya di kode juga salah — yang terbuang
    # justru ekornya, tingkat terakhir yang dicoba, satu-satunya bagian
    # yang menjawab "kenapa yang tanda tangan orang ini".
    assignment_reference = models.TextField(
        blank=True,
        default="",
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_approval"

        ordering = ["instance_id", "sequence", "id"]

        constraints = [
            # Satu orang satu kotak per step. Approver yang sama muncul
            # di dua step berbeda tetap sah — itu ditangani sebagai
            # SKIPPED oleh service, bukan ditolak database.
            models.UniqueConstraint(
                fields=["instance", "step", "approver"],
                name="uq_workflow_approval_instance_step_approver",
            ),
        ]

        indexes = [
            models.Index(
                fields=["approver", "status", "created_at"],
                name="idx_workflow_approval_inbox",
            ),
            models.Index(
                fields=["instance", "step", "status"],
                name="idx_workflow_approval_step",
            ),
        ]

    @property
    def is_decided(self) -> bool:
        return self.status != ApprovalStatus.PENDING

    @property
    def was_delegated(self) -> bool:
        return (
            self.acted_by_id is not None
            and self.approver_id is not None
            and self.acted_by_id != self.approver_id
        )

    def __str__(self) -> str:
        return f"#{self.sequence} {self.name} — {self.status}"
