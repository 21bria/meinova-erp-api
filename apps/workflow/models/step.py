"""
Satu tingkat di dalam alur, plus cara mencari siapa yang berhak
menyetujuinya.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .definition import WorkflowDefinition


class ApproverType(models.TextChoices):
    """
    Cara satu step menemukan orang yang berhak menyetujui.

    Empat yang pertama menelusuri struktur organisasi atau akun, `ROLE`
    tidak. Semuanya dibutuhkan: struktur organisasi paling akurat tapi
    paling sering bolong — di tenant yang datanya belum lengkap,
    `reports_to` kosong berarti tidak ada dokumen yang bisa disetujui
    sama sekali. Karena itu tiap step boleh membawa `fallback_role`.
    """

    # Orang tertentu, dipilih langsung. Untuk step yang memang selalu
    # satu nama — Direktur, pemilik.
    USER = "user", "Specific User"

    # Siapa pun pemegang Role tertentu. Untuk step yang bukan garis
    # komando: HR, Finance, bagian travel.
    ROLE = "role", "Role Holder"

    # Hierarki jabatan (Position.reports_to), bukan hierarki orang.
    # Dipakai kalau tenant mengelola struktur di level jabatan dan
    # pemegangnya sering berganti.
    POSITION = "position", "Position Hierarchy"

    # Atasan langsung pegawai, dari OrganizationAssignment.reports_to.
    # `level` menentukan berapa tingkat naik: 1 = atasan langsung,
    # 2 = atasan dari atasan.
    MANAGER = "manager", "Direct Manager"

    # Pemegang jabatan bertanda `is_manager` di department pegawai.
    # Untuk step "diketahui Kepala Departemen" yang tidak peduli garis
    # pelaporan langsung.
    DEPARTMENT_HEAD = "department_head", "Department Head"


class ApprovalMode(models.TextChoices):
    # Cukup satu orang (atau `minimum_approvals` orang) dari daftar
    # approver step ini.
    ANY = "any", "Any Approver"

    # Semua approver step ini harus memutuskan.
    ALL = "all", "All Approvers"


class ApproverScope(models.TextChoices):
    """
    Sejauh mana pemegang role dicari, untuk step bertipe Role Holder.

    Tanpa ini pencarian berhenti di company, dan itu terlalu longgar
    begitu satu company punya beberapa site: pengajuan dari Gebe ikut
    mendarat di kotak masuk KTT site lain, dan "Admin Section" menarik
    admin seluruh perusahaan. Kebocorannya diam — dokumennya memang
    tampil di kotak masuk yang salah, bukan error.

    Nilainya dibandingkan dengan penempatan **pegawai subjek dokumen**,
    bukan penempatan pengaju: yang menentukan meja mana yang berwenang
    adalah orang yang dokumennya diproses.

    `TENANT` sengaja disediakan untuk role yang memang melayani semua
    orang — Direktur, atau HRGA yang duduk di kantor pusat tapi
    membelikan tiket untuk seluruh site.
    """

    TENANT = "tenant", "Seluruh Tenant"
    COMPANY = "company", "Company"
    BRANCH = "branch", "Branch"
    LOCATION = "location", "Location"
    DIVISION = "division", "Division"
    DEPARTMENT = "department", "Department"
    SECTION = "section", "Section"


class WorkflowStep(BaseModel):
    definition = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.CASCADE,
        related_name="steps",
    )

    sequence = models.PositiveIntegerField(default=1)

    # Judul kotak tanda tangan di formulir tercetak. Bukan turunan dari
    # jabatan approver-nya: formulir menulis "Approved By: Site Manager"
    # walau yang menandatangani sedang dijabat pelaksana tugas.
    name = models.CharField(max_length=200)

    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Siapa yang menyetujui
    # ------------------------------------------------------------------

    approver_type = models.CharField(
        max_length=30,
        choices=ApproverType.choices,
        default=ApproverType.MANAGER,
    )

    approver_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_steps",
        help_text="Wajib diisi kalau tipenya Specific User.",
    )

    approver_role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_steps",
        help_text="Wajib diisi kalau tipenya Role Holder.",
    )

    approver_position = models.ForeignKey(
        "administration.Position",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_steps",
        help_text=(
            "Dikosongkan pada tipe Position Hierarchy = berangkat dari "
            "jabatan pengaju sendiri, lalu naik sebanyak Level."
        ),
    )

    level = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Berapa tingkat naik untuk tipe berbasis hierarki. "
            "1 = atasan langsung."
        ),
    )

    approver_scope = models.CharField(
        max_length=20,
        choices=ApproverScope.choices,
        default=ApproverScope.COMPANY,
        help_text=(
            "Sejauh mana pemegang role dicari, dibandingkan dengan "
            "penempatan pegawai yang dokumennya diproses. Hanya "
            "berpengaruh untuk tipe Role Holder dan role cadangan. "
            "Pilih Location untuk meja yang memang per site (KTT, "
            "Admin Site), Company untuk yang melayani lintas site "
            "(HRGA, HR Manager)."
        ),
    )

    fallback_role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_step_fallbacks",
        help_text=(
            "Dipakai kalau penelusuran struktur organisasi tidak "
            "menemukan siapa pun. Kosong = step-nya gagal, kecuali "
            "step ini ditandai tidak wajib."
        ),
    )

    # ------------------------------------------------------------------
    # Cara memutuskan
    # ------------------------------------------------------------------

    approval_mode = models.CharField(
        max_length=20,
        choices=ApprovalMode.choices,
        default=ApprovalMode.ANY,
        help_text=(
            "Hanya berpengaruh kalau step ini menghasilkan lebih dari "
            "satu approver — praktisnya tipe Role Holder."
        ),
    )

    minimum_approvals = models.PositiveIntegerField(
        default=1,
        help_text=(
            "Berapa persetujuan yang dibutuhkan pada mode Any Approver."
        ),
    )

    # ------------------------------------------------------------------
    # Perilaku
    # ------------------------------------------------------------------

    can_reject = models.BooleanField(
        default=True,
        help_text="Approver step ini boleh menolak dokumen.",
    )

    can_return = models.BooleanField(
        default=True,
        help_text=(
            "Approver step ini boleh mengembalikan dokumen ke pengaju "
            "untuk diperbaiki, tanpa menolaknya."
        ),
    )

    is_required = models.BooleanField(
        default=True,
        help_text=(
            "Dimatikan: approver yang tidak ketemu membuat step ini "
            "dilewati, bukan menggagalkan seluruh pengajuan."
        ),
    )

    # ------------------------------------------------------------------
    # Kondisi
    # ------------------------------------------------------------------

    condition = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Kosong = step selalu jalan. Bentuknya "
            '{"field": "total_days", "op": "gte", "value": 5}, atau '
            'digabung lewat {"all": [...]} / {"any": [...]}. '
            "Dinilai terhadap konteks dokumen saat diajukan."
        ),
    )

    class Meta:
        db_table = "workflow_step"

        ordering = ["definition_id", "sequence", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["definition", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_workflow_step_sequence",
            ),
        ]

        indexes = [
            models.Index(
                fields=["definition", "sequence"],
                name="idx_workflow_step_flow",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        # Step yang kekurangan penunjuk approver-nya akan selalu gagal
        # mencari orang, dan gagalnya baru ketahuan saat pengaju menekan
        # Submit — jauh dari layar tempat step ini dikonfigurasi.
        if self.approver_type == ApproverType.USER and not self.approver_user_id:
            errors["approver_user"] = (
                "Pilih penggunanya untuk step bertipe Specific User."
            )

        if self.approver_type == ApproverType.ROLE and not self.approver_role_id:
            errors["approver_role"] = (
                "Pilih role-nya untuk step bertipe Role Holder."
            )

        if self.level is not None and self.level < 1:
            errors["level"] = "Level minimal 1."

        if self.minimum_approvals is not None and self.minimum_approvals < 1:
            errors["minimum_approvals"] = "Minimal 1 persetujuan."

        if errors:
            raise ValidationError(errors)

    def fallback_chain(self) -> list[tuple]:
        """
        Cadangan step ini sebagai deret `(role, cakupan)`, urut.

        Baris `WorkflowStepFallback` menang kalau ada; kalau tidak,
        `fallback_role` lama dipakai apa adanya dengan cakupan Company —
        persis perilaku sebelum jenjang ini ada, supaya alur yang sudah
        berjalan tidak berubah hanya karena modelnya bertambah.
        """
        rows = [
            (row.role, row.approver_scope)
            for row in self.fallbacks.filter(
                is_deleted=False,
                is_active=True,
            ).select_related("role")
        ]

        if rows:
            return rows

        if self.fallback_role_id:
            return [(self.fallback_role, ApproverScope.COMPANY)]

        return []

    def __str__(self) -> str:
        return f"#{self.sequence} {self.name}"


class WorkflowStepFallback(BaseModel):
    """
    Cadangan berjenjang untuk satu step, ketika cadangan tunggal tidak
    cukup.

    `WorkflowStep.fallback_role` hanya menampung **satu** role dan
    selalu dicari se-company. Itu cukup untuk "kalau atasannya belum
    diisi, jatuh ke HR Manager", tapi tidak untuk turunan yang memang
    berjenjang: meja Admin Section pada alur site harus jatuh ke **Admin
    Department pegawainya** dulu, baru ke HR — dan yang di tengah itu
    tidak boleh se-company, kalau tidak admin department site sebelah
    ikut tertarik.

    Karena itu tiap baris membawa cakupannya sendiri. Yang tidak punya
    baris sama sekali tetap memakai `fallback_role` lama apa adanya,
    jadi seluruh alur yang sudah berjalan tidak berubah perilakunya.

    **Urutannya menentukan, dan yang pertama ketemu yang menang.**
    Menggabungkan semua tingkat jadi satu kumpulan approver akan
    membuat meja yang seharusnya jatuh ke satu orang berisi lima orang
    dari lima tingkat sekaligus.
    """

    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.CASCADE,
        related_name="fallbacks",
    )

    sequence = models.PositiveSmallIntegerField(
        default=1,
        help_text="Urutan pencarian; yang terkecil dicoba lebih dulu.",
    )

    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        related_name="workflow_step_fallback_links",
    )

    approver_scope = models.CharField(
        max_length=20,
        choices=ApproverScope.choices,
        default=ApproverScope.COMPANY,
        help_text=(
            "Sejauh mana pemegang role cadangan ini dicari. Company "
            "untuk jaring terakhir; Department atau Section untuk "
            "turunan yang memang harus tetap di unit pegawainya."
        ),
    )

    class Meta:
        db_table = "workflow_step_fallback"
        ordering = ["step", "sequence"]

        constraints = [
            models.UniqueConstraint(
                fields=["step", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_workflow_step_fallback_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.sequence} {self.role_id}"
