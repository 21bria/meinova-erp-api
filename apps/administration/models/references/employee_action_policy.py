"""
Siapa yang boleh **mengajukan** perubahan kepegawaian.

Sebelum ini cuma ada satu saklar untuk dua belas jenis: izin model
`hr.add_employeeaction`. Siapa pun yang memegangnya bisa mengajukan
apa saja — HR admin bisa mengusulkan kenaikan gaji dan promosi, dan
tidak ada satu pun tempat di sistem yang menyebut bahwa usulan itu
seharusnya datang dari atasan atau kepala departemen. Yang tercatat
di dokumennya cuma "dibuat oleh", dan itu memang orang yang mengetik.

Yang disimpan di sini **aturannya**, bukan izinnya. Django Permission
tidak mengenal `action_type`, jadi memecah izin per model tidak akan
pernah bisa membedakan kenaikan gaji dari perpanjangan kontrak — itu
sebabnya aturannya jadi master tersendiri, bukan role baru.

Pencocokannya berjenjang lewat skor `specificity`, pola yang sama
dengan `LeavePolicy`, `RosterPolicy`, dan `WorkflowDefinition`: kosong
berarti **berlaku untuk semua**, bukan "tidak berlaku".
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class ActionInitiator(models.TextChoices):
    """
    Kosakatanya sengaja dipinjam dari `ApproverType` di engine
    workflow. Pertanyaannya memang sama — "orang mana, relatif terhadap
    pegawai ini" — dan dua kosakata untuk satu pertanyaan berarti dua
    tempat yang harus dijaga tetap sama.
    """

    # Siapa pun yang punya izin model. Perilaku lama, dan tetap benar
    # untuk koreksi administratif.
    ANY = "any", "Anyone With Permission"

    # Atasan langsung pegawai yang datanya diubah (`reports_to`).
    MANAGER = "manager", "Direct Manager"

    # Pemegang jabatan bertanda Manager di department pegawainya.
    DEPARTMENT_HEAD = "department_head", "Department Head"

    # Pemegang role tertentu — mis. HR-MANAGER untuk koreksi status.
    ROLE = "role", "Role Holder"

    # Pegawainya sendiri. Untuk pengunduran diri: yang mengajukan
    # memang orang yang bersangkutan.
    EMPLOYEE = "employee", "The Employee"


class EmployeeActionPolicy(BaseModel):
    """
    Satu aturan pengaju untuk satu jenis Employee Action.
    """

    # ------------------------------------------------------------------
    # Untuk siapa
    # ------------------------------------------------------------------

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employee_action_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak "
            "punya aturannya sendiri."
        ),
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employee_action_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua lokasi. Diisi kalau "
            "site tertentu punya jalur usulan sendiri."
        ),
    )

    employee_group = models.ForeignKey(
        "administration.EmployeeGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employee_action_policies",
        help_text="Dikosongkan = berlaku untuk semua golongan.",
    )

    # ------------------------------------------------------------------
    # Untuk jenis apa
    # ------------------------------------------------------------------

    action_type = models.CharField(
        max_length=40,
        help_text=(
            "Jenis perubahan yang diatur baris ini. Satu baris satu "
            "jenis — kenaikan gaji dan perpanjangan kontrak memang "
            "diusulkan orang yang berbeda."
        ),
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Siapa yang mengusulkan
    # ------------------------------------------------------------------

    initiator_type = models.CharField(
        max_length=20,
        choices=ActionInitiator.choices,
        default=ActionInitiator.ANY,
        help_text=(
            "Orang yang usulannya sah untuk jenis ini. Dinilai "
            "terhadap pegawai yang datanya diubah, bukan terhadap yang "
            "mengetik dokumennya."
        ),
    )

    initiator_role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="initiated_action_policies",
        help_text="Wajib diisi kalau pengusulnya ditentukan lewat Role.",
    )

    # ------------------------------------------------------------------
    # Atas nama
    # ------------------------------------------------------------------

    allow_on_behalf = models.BooleanField(
        default=True,
        help_text=(
            "HR boleh mengetikkan dokumennya untuk pengusul yang "
            "menyampaikan lisan, asalkan kolom Requested By diisi. "
            "Matikan kalau usulannya harus dibuat sendiri oleh yang "
            "bersangkutan."
        ),
    )

    on_behalf_role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="on_behalf_action_policies",
        help_text=(
            "Yang boleh mengetikkan atas nama orang lain. Dikosongkan "
            "= siapa pun yang punya izin membuat Employee Action."
        ),
    )

    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Employee Action Policy"
        verbose_name_plural = "Employee Action Policies"
        ordering = ["action_type", "sort_order", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_employee_action_policy_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def specificity(self) -> int:
        """
        Seberapa khusus aturan ini. Makin tinggi makin menang.

        Bobotnya mengikuti `WorkflowDefinition`: company mengalahkan
        lokasi, lokasi mengalahkan golongan. Dipakai supaya pilihannya
        tidak bergantung pada urutan baris di database.
        """
        return (
            (4 if self.company_id else 0)
            + (2 if self.location_id else 0)
            + (1 if self.employee_group_id else 0)
        )

    def clean(self):
        super().clean()

        errors = {}

        from apps.hr.models import EmployeeActionType

        valid = {str(value) for value, _ in EmployeeActionType.choices}

        if self.action_type and self.action_type not in valid:
            errors["action_type"] = (
                f"Jenis '{self.action_type}' tidak dikenal."
            )

        # Role Holder tanpa rolenya tidak bisa dieksekusi: tidak ada
        # yang memenuhi syaratnya, jadi jenis itu tidak bisa diajukan
        # siapa pun — dan kegagalannya baru muncul saat ada yang
        # mencoba.
        if (
            self.initiator_type == ActionInitiator.ROLE
            and not self.initiator_role_id
        ):
            errors["initiator_role"] = (
                "Pengusul lewat Role harus menyebut role-nya."
            )

        if (
            self.initiator_type != ActionInitiator.ROLE
            and self.initiator_role_id
        ):
            errors["initiator_role"] = (
                "Role hanya dipakai kalau pengusulnya ditentukan lewat "
                "Role."
            )

        # Membatasi siapa yang boleh mengetik atas nama, sementara
        # mengetik atas nama sendiri dimatikan, tidak berpengaruh
        # apa-apa — dan yang mengisinya mengira sudah mengatur sesuatu.
        if not self.allow_on_behalf and self.on_behalf_role_id:
            errors["on_behalf_role"] = (
                "Pengisian atas nama dimatikan, jadi role ini tidak "
                "pernah dipakai."
            )

        if errors:
            raise ValidationError(errors)
