"""
Alur persetujuan untuk satu jenis dokumen.

Generik, bukan milik HR: `module` + `document_type` adalah pola kunci
yang sama dengan `NumberingSequence`, jadi Payroll, Finance, dan SCM
memakai engine ini tanpa satu baris pun kode baru di sisi engine.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class WorkflowStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class WorkflowDefinition(BaseModel):
    """
    Satu alur, dengan cakupan berjenjang.

    Seluruh kolom cakupan opsional dan **kosong berarti "berlaku untuk
    semua", bukan "tidak berlaku"** — itu jebakan paling gampang di
    layar settingnya, sama seperti di `LeavePolicy` dan `RosterPolicy`.
    Pemenangnya dipilih skor `specificity`, bukan urutan baris: alur
    khusus Head Office menang atas alur global tanpa siapa pun perlu
    mengatur prioritas manual.
    """

    code = models.CharField(max_length=100)

    name = models.CharField(max_length=200)

    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Dokumen yang dilayani
    # ------------------------------------------------------------------

    module = models.CharField(
        max_length=100,
        db_index=True,
        help_text=(
            "Modul pemilik dokumen, mis. hr, payroll, finance, scm."
        ),
    )

    document_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text=(
            "Jenis dokumen yang dilayani alur ini, mis. leave_request "
            "atau travel_request."
        ),
    )

    # ------------------------------------------------------------------
    # Untuk siapa
    # ------------------------------------------------------------------
    #
    # Empat-empatnya opsional dan boleh dipakai bersama. Inilah yang
    # membuat "cuti karyawan Head Office" bisa punya alur sendiri —
    # cukup isi `location` dengan Jakarta HO — tanpa mengubah alur
    # pegawai site yang sudah berjalan.

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_definitions",
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak "
            "punya alurnya sendiri."
        ),
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_definitions",
        help_text="Dikosongkan = berlaku untuk semua branch.",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_definitions",
        help_text=(
            "Lokasi kerja pengaju. Dikosongkan = berlaku untuk semua "
            "lokasi. Ini kolom yang membedakan alur Head Office dari "
            "alur site."
        ),
    )

    employee_group = models.ForeignKey(
        "administration.EmployeeGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_definitions",
        help_text="Dikosongkan = berlaku untuk semua golongan pegawai.",
    )

    # ------------------------------------------------------------------
    # Versi & status
    # ------------------------------------------------------------------

    version = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=20,
        choices=WorkflowStatus.choices,
        default=WorkflowStatus.DRAFT,
        db_index=True,
        help_text=(
            "Hanya alur berstatus Active yang dipakai saat dokumen "
            "diajukan."
        ),
    )

    # Instance yang sudah berjalan menunjuk step-nya lewat FK, jadi
    # mengubah alur tidak mengubah dokumen yang sedang berjalan. Nomor
    # versi di sini murni penanda untuk manusia — dua alur berbeda versi
    # untuk dokumen yang sama tetap harus dibedakan cakupannya, kalau
    # tidak yang menang cuma soal specificity.
    class Meta:
        db_table = "workflow_definition"

        ordering = ["module", "document_type", "-version", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_workflow_definition_code",
            ),
            # Dua alur dengan cakupan persis sama untuk dokumen yang
            # sama akan punya specificity identik, dan pemenangnya jadi
            # soal urutan `id` — persis yang mau dihindari desain ini.
            models.UniqueConstraint(
                fields=[
                    "module",
                    "document_type",
                    "company",
                    "branch",
                    "location",
                    "employee_group",
                    "version",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_workflow_definition_scope",
            ),
        ]

        indexes = [
            models.Index(
                fields=["module", "document_type", "status"],
                name="idx_workflow_def_target",
            ),
        ]

    # ------------------------------------------------------------------
    # Pencocokan
    # ------------------------------------------------------------------

    @property
    def specificity(self) -> int:
        """
        Seberapa khusus alur ini. Makin tinggi makin menang.

        Bobotnya menurun mengikuti hierarki organisasi: company
        mengalahkan branch, branch mengalahkan location. Golongan
        pegawai diberi bobot paling kecil karena ia memotong hierarki —
        "semua staf" bisa berlaku lintas lokasi.
        """
        return (
            (8 if self.company_id else 0)
            + (4 if self.branch_id else 0)
            + (2 if self.location_id else 0)
            + (1 if self.employee_group_id else 0)
        )

    @property
    def is_usable(self) -> bool:
        return (
            self.status == WorkflowStatus.ACTIVE
            and self.is_active
            and not self.is_deleted
        )

    def clean(self):
        super().clean()

        errors = {}

        if self.module:
            self.module = self.module.strip().lower()

        if self.document_type:
            self.document_type = self.document_type.strip().lower()

        if not self.module:
            errors["module"] = "Modul wajib diisi."

        if not self.document_type:
            errors["document_type"] = "Jenis dokumen wajib diisi."

        # Cakupan yang saling bertentangan menghasilkan alur yang tidak
        # pernah cocok dengan siapa pun, dan gagalnya baru ketahuan saat
        # ada yang menekan Submit — jauh dari layar ini.
        if self.branch_id and self.company_id:
            if self.branch.company_id != self.company_id:
                errors["branch"] = (
                    "Branch ini bukan milik company yang dipilih."
                )

        if self.location_id and self.branch_id:
            if (
                self.location.branch_id
                and self.location.branch_id != self.branch_id
            ):
                errors["location"] = (
                    "Location ini bukan milik branch yang dipilih."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.name} ({self.module}/{self.document_type})"
