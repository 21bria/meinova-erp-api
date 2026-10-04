"""
Satu dokumen yang sedang berjalan di sebuah alur.

Dokumennya ditunjuk `module` + `document_type` + `object_id`, bukan
`GenericForeignKey`: engine ini tidak perlu tahu apa-apa tentang model
yang memakainya, dan kunci yang dipakai persis sama dengan kunci yang
dipakai mencari alurnya. Konsekuensinya tidak ada integritas
referensial di level database — yang menjaganya constraint di bawah
plus penghapusan dokumen yang di codebase ini selalu soft delete.
"""

from django.conf import settings
from django.db import models

from .definition import WorkflowDefinition
from .step import WorkflowStep


class InstanceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"

    # Dikembalikan ke pengaju untuk diperbaiki. Bukan penolakan: alur
    # yang sama bisa diajukan ulang tanpa dokumen baru.
    RETURNED = "returned", "Returned"

    CANCELLED = "cancelled", "Cancelled"


# Status yang berarti "masih menghalangi pengajuan baru untuk dokumen
# yang sama". RETURNED ikut: dokumen yang dikembalikan belum selesai,
# pengaju tinggal memperbaiki dan mengajukan ulang instance itu juga.
OPEN_STATUSES = [
    InstanceStatus.DRAFT,
    InstanceStatus.PENDING,
    InstanceStatus.RETURNED,
]


class WorkflowInstance(models.Model):
    definition = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.PROTECT,
        related_name="instances",
    )

    # ------------------------------------------------------------------
    # Dokumen yang diajukan
    # ------------------------------------------------------------------

    module = models.CharField(max_length=100, db_index=True)

    document_type = models.CharField(max_length=100, db_index=True)

    object_id = models.CharField(max_length=100, db_index=True)

    document_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )

    document_label = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Ringkasan yang ditampilkan di kotak masuk approver — "
            "disalin, bukan dibaca lewat relasi, karena engine ini "
            "tidak mengenal model dokumennya."
        ),
    )

    # ------------------------------------------------------------------
    # Subjek & organisasi
    # ------------------------------------------------------------------
    #
    # Pegawai yang dokumennya diajukan — bukan yang menekan tombol.
    # Penelusuran atasan berangkat dari orang ini, dan bagian HR yang
    # mengajukan atas nama pegawai lain tidak boleh mengubah siapa
    # atasannya.

    subject_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_instances",
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_instances",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_instances",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_instances",
    )

    # ------------------------------------------------------------------
    # Keadaan alur
    # ------------------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=InstanceStatus.choices,
        default=InstanceStatus.DRAFT,
        db_index=True,
    )

    current_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_instances",
    )

    # ------------------------------------------------------------------
    # Pengaju
    # ------------------------------------------------------------------

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_workflows",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Konteks
    # ------------------------------------------------------------------

    context = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Cuplikan nilai dokumen saat diajukan. Inilah yang dinilai "
            "`WorkflowStep.condition` — dibekukan supaya syarat sebuah "
            "step tidak berubah di tengah jalan gara-gara dokumennya "
            "disunting."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_instance"

        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["module", "document_type", "object_id"],
                name="idx_workflow_inst_target",
            ),
            models.Index(
                fields=["status", "created_at"],
                name="idx_workflow_inst_status",
            ),
        ]

        constraints = [
            # Satu dokumen satu pengajuan berjalan. Pengajuan yang sudah
            # ditolak atau dibatalkan boleh disusul yang baru — itu
            # memang jalur revisi — jadi yang dikunci hanya yang masih
            # terbuka. Sengaja tanpa `definition`: dokumen yang sama
            # tidak boleh berjalan di dua alur sekaligus.
            models.UniqueConstraint(
                fields=["module", "document_type", "object_id"],
                condition=models.Q(
                    status__in=["draft", "pending", "returned"],
                ),
                name="uq_workflow_open_instance",
            ),
        ]

    # ------------------------------------------------------------------
    # Turunan
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def pending_approvals(self):
        """
        Baris keputusan di step yang sedang ditunggu.

        Bisa lebih dari satu: step bertipe Role Holder dengan mode All
        Approvers menunggu semua pemegang role-nya.
        """
        from .approval import ApprovalStatus

        if self.current_step_id is None:
            return self.approvals.none()

        return self.approvals.filter(
            step_id=self.current_step_id,
            status=ApprovalStatus.PENDING,
        )

    def __str__(self) -> str:
        return (
            f"{self.definition.code} — "
            f"{self.document_number or self.object_id}"
        )
