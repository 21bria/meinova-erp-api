"""
Surat kuasa: siapa yang boleh memutuskan atas nama siapa, dan sampai
kapan.

Delegasi **tidak mengubah siapa approver-nya**. Baris keputusan tetap
tercatat atas nama atasan yang seharusnya menandatangani; yang berubah
cuma siapa yang boleh menekan tombolnya, dan itu disimpan terpisah di
`WorkflowApproval.acted_by`. Mengganti approver-nya akan membuat
formulir tercetak menunjukkan nama yang berbeda dari struktur
organisasi, dan jejak "kenapa yang tanda tangan orang ini" hilang.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel


class WorkflowDelegation(BaseModel):
    delegator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workflow_delegations_given",
        help_text="Approver yang berhalangan.",
    )

    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workflow_delegations_received",
        help_text="Yang diberi kuasa memutuskan selama periode ini.",
    )

    # ------------------------------------------------------------------
    # Cakupan
    # ------------------------------------------------------------------
    #
    # Kosong berarti "semua", bukan "tidak berlaku" — sama seperti
    # cakupan di WorkflowDefinition. Diisi kalau kuasanya memang
    # terbatas: HR Manager yang cuti boleh menyerahkan persetujuan cuti
    # tanpa ikut menyerahkan persetujuan payroll.

    module = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        help_text="Dikosongkan = berlaku untuk semua modul.",
    )

    document_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        help_text="Dikosongkan = berlaku untuk semua jenis dokumen.",
    )

    # ------------------------------------------------------------------
    # Masa berlaku
    # ------------------------------------------------------------------

    starts_at = models.DateTimeField(db_index=True)

    ends_at = models.DateTimeField(db_index=True)

    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "workflow_delegation"

        ordering = ["-starts_at", "-created_at"]

        indexes = [
            models.Index(
                fields=["delegator", "starts_at", "ends_at"],
                name="idx_workflow_del_active",
            ),
            models.Index(
                fields=["delegate"],
                name="idx_workflow_del_delegate",
            ),
            models.Index(
                fields=["module", "document_type"],
                name="idx_workflow_del_scope",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=~models.Q(delegator=models.F("delegate")),
                name="ck_workflow_delegation_different_users",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="ck_workflow_delegation_valid_period",
            ),
        ]

    def covers(self, *, module: str, document_type: str) -> bool:
        """Apakah kuasa ini mencakup jenis dokumen tersebut."""
        if self.module and self.module != module:
            return False

        if self.document_type and self.document_type != document_type:
            return False

        return True

    def clean(self):
        super().clean()

        errors = {}

        if self.module:
            self.module = self.module.strip().lower()

        if self.document_type:
            self.document_type = self.document_type.strip().lower()

        if self.delegator_id and self.delegator_id == self.delegate_id:
            errors["delegate"] = (
                "Tidak bisa memberi kuasa kepada diri sendiri."
            )

        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = (
                "Berakhir harus setelah mulai."
            )

        # Cakupan jenis dokumen tanpa modulnya tidak pernah bisa
        # dicocokkan dengan benar: `leave_request` milik HR dan
        # `leave_request` milik modul lain tidak bisa dibedakan.
        if self.document_type and not self.module:
            errors["module"] = (
                "Isi modulnya juga kalau cakupannya dibatasi ke satu "
                "jenis dokumen."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.delegator} → {self.delegate}"
