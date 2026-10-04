"""
Employee Action — dokumen perubahan data kepegawaian.

Bedanya dengan `EmploymentAssignment` di sebelah, dan ini yang harus
tetap terpisah: `EmploymentAssignment` adalah **keadaan sekarang** —
satu baris per pegawai, isinya nilai yang berlaku hari ini.
`EmployeeAction` adalah **transaksi yang mengubahnya** — banyak baris
per pegawai, masing-masing menyimpan nilai lama, nilai usulan, tanggal
berlaku, alasannya, dan siapa yang menyetujuinya.

Tanpa pemisahan itu, memperpanjang kontrak berarti menimpa
`contract_end` yang lama dan riwayatnya hilang: pegawai yang sudah tiga
kali diperpanjang lalu diangkat tetap terlihat seperti tidak pernah
berkontrak sama sekali, dan tidak ada satu baris pun yang bisa ditunjuk
saat orangnya bertanya "sejak kapan saya permanen".

Dokumen ini **bukan** history model kedua. Riwayat kepegawaian dibaca
dari baris yang sudah `APPLIED` — satu tabel, satu kebenaran. Yang
belum disetujui memang belum jadi riwayat apa-apa.

Approval-nya lewat engine generik `apps/workflow`
(``module="hr"``, ``document_type="employee_action"``), sama seperti
Cuti dan Travel Request. Tidak ada mesin persetujuan sendiri di sini.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class EmployeeActionType(models.TextChoices):
    """
    Jenis perubahan yang bisa diajukan.

    Dipecah sehalus ini — bukan satu "CHANGE" dengan isian bebas —
    karena tiap jenis punya kolom wajib, aturan validasi, dan sering
    jalur persetujuan yang berbeda. `WorkflowStep.condition` membaca
    `action_type` dari context, jadi "kenaikan gaji naik sampai HR
    Manager, perpanjangan kontrak tidak" bisa dikonfigurasi dari layar
    tanpa menyentuh kode.
    """

    CONTRACT_EXTENSION = "contract_extension", "Contract Extension"
    CONTRACT_CHANGE = "contract_change", "Contract Change"
    EMPLOYMENT_TYPE_CHANGE = (
        "employment_type_change",
        "Employment Type Change",
    )
    PROBATION_CHANGE = "probation_change", "Probation Change"
    STATUS_CHANGE = "status_change", "Employment Status Change"

    TRANSFER = "transfer", "Transfer"
    PROMOTION = "promotion", "Promotion"
    DEMOTION = "demotion", "Demotion"
    POSITION_CHANGE = "position_change", "Position Change"

    SALARY_CHANGE = "salary_change", "Salary Change"

    RESIGNATION = "resignation", "Resignation"
    TERMINATION = "termination", "Termination"


class EmployeeActionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"

    # Perubahannya sudah benar-benar ditulis ke data pegawai. Dipisah
    # dari APPROVED dengan sengaja: alur bisa selesai tapi penerapannya
    # gagal (master belum lengkap, tanggal bentrok), dan dokumen yang
    # tercatat "approved" padahal datanya belum berubah harus bisa
    # dibedakan dari yang sudah — kalau tidak, tidak ada yang tahu ada
    # yang harus diulang.
    APPLIED = "applied", "Applied"

    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


# Status yang isinya masih boleh disunting. Sama pola dengan
# `TravelRequest.is_editable`: yang sudah diajukan atau sudah diterapkan
# harus tetap menunjuk isi yang ditandatangani.
ACTION_EDITABLE_STATUSES = {
    EmployeeActionStatus.DRAFT,
    EmployeeActionStatus.REJECTED,
}


# Status yang dianggap "masih berjalan" — dipakai menolak dua dokumen
# terbuka untuk pegawai dan jenis yang sama.
ACTION_OPEN_STATUSES = {
    EmployeeActionStatus.DRAFT,
    EmployeeActionStatus.SUBMITTED,
    EmployeeActionStatus.APPROVED,
}


# ---------------------------------------------------------------------
# Kolom wajib per jenis
# ---------------------------------------------------------------------
#
# Ditulis sebagai tabel, bukan sebagai rantai `if` di `clean()`: daftar
# ini juga dibaca serializer dan schema UI, jadi menaruhnya di satu
# tempat membuat pesan validasi backend dan kolom yang tampil di form
# tidak bisa berbeda pendapat.
#
# Kunci `fields` = kolom usulan yang relevan untuk jenis itu. Kunci
# `required` = yang tidak boleh kosong.

ACTION_FIELD_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    EmployeeActionType.CONTRACT_EXTENSION: {
        "fields": (
            "proposed_contract_type",
            "proposed_contract_start",
            "proposed_contract_end",
        ),
        "required": ("proposed_contract_end",),
    },
    EmployeeActionType.CONTRACT_CHANGE: {
        "fields": (
            "proposed_contract_type",
            "proposed_contract_start",
            "proposed_contract_end",
        ),
        "required": (
            "proposed_contract_type",
            "proposed_contract_start",
            "proposed_contract_end",
        ),
    },
    EmployeeActionType.EMPLOYMENT_TYPE_CHANGE: {
        "fields": (
            "proposed_employment_type",
            "proposed_employee_group",
            "confirmation_date",
        ),
        "required": ("proposed_employment_type",),
    },
    EmployeeActionType.PROBATION_CHANGE: {
        "fields": (
            "proposed_probation_type",
            "proposed_probation_start",
            "proposed_probation_end",
        ),
        "required": ("proposed_probation_type",),
    },
    EmployeeActionType.STATUS_CHANGE: {
        "fields": ("proposed_employment_status",),
        "required": ("proposed_employment_status",),
    },
    EmployeeActionType.TRANSFER: {
        "fields": (
            "proposed_company",
            "proposed_branch",
            "proposed_location",
            "proposed_division",
            "proposed_department",
            "proposed_section",
            "proposed_position",
            "proposed_cost_center",
            "proposed_reports_to",
        ),
        "required": (),
    },
    EmployeeActionType.PROMOTION: {
        "fields": (
            "proposed_position",
            "proposed_job_level",
            "proposed_job_grade",
            "proposed_department",
            "proposed_section",
            "proposed_reports_to",
        ),
        "required": ("proposed_position",),
    },
    EmployeeActionType.DEMOTION: {
        "fields": (
            "proposed_position",
            "proposed_job_level",
            "proposed_job_grade",
            "proposed_reports_to",
        ),
        "required": ("proposed_position",),
    },
    EmployeeActionType.POSITION_CHANGE: {
        "fields": (
            "proposed_position",
            "proposed_job_level",
            "proposed_job_grade",
            "proposed_reports_to",
        ),
        "required": ("proposed_position",),
    },
    EmployeeActionType.SALARY_CHANGE: {
        "fields": (
            "proposed_basic_salary",
            "proposed_salary_grade",
            "proposed_salary_level",
            "proposed_payroll_group",
        ),
        "required": ("proposed_basic_salary",),
    },
    EmployeeActionType.RESIGNATION: {
        "fields": (
            "last_working_date",
            "termination_reason",
            "proposed_employment_status",
        ),
        "required": ("last_working_date",),
    },
    EmployeeActionType.TERMINATION: {
        "fields": (
            "last_working_date",
            "termination_reason",
            "proposed_employment_status",
        ),
        "required": ("last_working_date", "termination_reason"),
    },
}


# Jenis yang menyentuh penempatan organisasi. Dipakai service untuk
# memilih assignment mana yang ditulis saat action diterapkan.
ORGANIZATION_ACTION_TYPES = {
    EmployeeActionType.TRANSFER,
    EmployeeActionType.PROMOTION,
    EmployeeActionType.DEMOTION,
    EmployeeActionType.POSITION_CHANGE,
}


class EmployeeAction(BaseModel):
    document_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="actions",
    )

    # Yang **mengusulkan**, bukan yang mengetik.
    #
    # Dua-duanya perlu dan sering berbeda: kepala departemen
    # menyampaikan usulan kenaikan gaji lisan, HR yang memasukkannya ke
    # sistem. `created_by` mencatat yang mengetik; kolom ini mencatat
    # yang bertanggung jawab atas usulannya, dan itu yang dibaca
    # `EmployeeActionPolicy` maupun kotak tanda tangan di dokumen
    # tercetak.
    #
    # Pegawai, bukan User: dokumen tercetak menulis nama dan jabatan,
    # dan pengusul yang belum punya akun tetap harus bisa disebut.
    requested_by = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requested_actions",
        help_text=(
            "Yang mengusulkan perubahan ini. Dikosongkan = yang "
            "membuat dokumennya sendiri yang mengusulkan."
        ),
    )

    action_type = models.CharField(
        max_length=40,
        choices=EmployeeActionType.choices,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=EmployeeActionStatus.choices,
        default=EmployeeActionStatus.DRAFT,
        db_index=True,
    )

    # Sejak kapan perubahannya berlaku. Bukan tanggal pengajuan dan
    # bukan tanggal persetujuan — dokumen yang disetujui 20 Agustus
    # untuk pengangkatan 1 September harus tetap menunjuk 1 September.
    effective_date = models.DateField()

    reason = models.TextField(
        blank=True,
        default="",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    # ------------------------------------------------------------------
    # Cakupan data
    # ------------------------------------------------------------------
    #
    # Didenormalisasi dari OrganizationAssignment saat dokumen dibuat,
    # pola yang sama dengan EmployeeLeave/TravelRequest — supaya
    # cakupan data bisa menyaring baris tanpa menembus dua
    # relasi di setiap query daftar.

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    # ------------------------------------------------------------------
    # Usulan — Employment
    # ------------------------------------------------------------------

    proposed_employment_type = models.ForeignKey(
        "administration.EmploymentType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_employment_status = models.ForeignKey(
        "administration.EmploymentStatus",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_employee_group = models.ForeignKey(
        "administration.EmployeeGroup",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    confirmation_date = models.DateField(
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------
    # Usulan — Contract & Probation
    # ------------------------------------------------------------------

    proposed_contract_type = models.ForeignKey(
        "administration.ContractType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_contract_start = models.DateField(
        null=True,
        blank=True,
    )

    proposed_contract_end = models.DateField(
        null=True,
        blank=True,
    )

    proposed_probation_type = models.ForeignKey(
        "administration.ProbationType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_probation_start = models.DateField(
        null=True,
        blank=True,
    )

    proposed_probation_end = models.DateField(
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------
    # Usulan — Organisasi
    # ------------------------------------------------------------------

    proposed_company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_division = models.ForeignKey(
        "administration.Division",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_section = models.ForeignKey(
        "administration.Section",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_position = models.ForeignKey(
        "administration.Position",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_job_level = models.ForeignKey(
        "administration.JobLevel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_job_grade = models.ForeignKey(
        "administration.JobGrade",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_cost_center = models.ForeignKey(
        "administration.CostCenter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    proposed_reports_to = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # ------------------------------------------------------------------
    # Usulan — Payroll
    # ------------------------------------------------------------------

    proposed_payroll_group = models.ForeignKey(
        "payroll.PayrollGroup",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_salary_grade = models.ForeignKey(
        "payroll.SalaryGrade",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_salary_level = models.ForeignKey(
        "payroll.SalaryLevel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    proposed_basic_salary = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------
    # Usulan — Pemutusan
    # ------------------------------------------------------------------

    termination_reason = models.ForeignKey(
        "administration.TerminationReason",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_actions",
    )

    last_working_date = models.DateField(
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------
    # Jejak penerapan
    # ------------------------------------------------------------------
    #
    # `values_before` dibekukan tepat sebelum data pegawai diubah, bukan
    # dihitung ulang saat dibaca: nilai "sebelum"-nya harus tetap
    # menunjuk keadaan waktu itu walau sesudahnya ada tiga perubahan
    # lain. Ini yang membuat riwayat lama tidak ikut berubah saat
    # current state berubah.

    values_before = models.JSONField(
        default=dict,
        blank=True,
    )

    values_after = models.JSONField(
        default=dict,
        blank=True,
    )

    applied_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    applied_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_employee_actions",
    )

    # Kegagalan penerapan setelah alurnya selesai. Disimpan, bukan cuma
    # dicatat di log: yang harus menindaklanjuti adalah HR yang membuka
    # dokumennya, bukan orang yang membaca log server.
    apply_error = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_action"

        ordering = [
            "-effective_date",
            "-created_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_employee_action_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "effective_date"],
                name="idx_emp_action_emp_date",
            ),
            models.Index(
                fields=["action_type", "status"],
                name="idx_emp_action_type_status",
            ),
        ]

    def __str__(self):
        return (
            f"{self.document_number or f'#{self.pk}'} — "
            f"{self.get_action_type_display()}"
        )

    # ------------------------------------------------------------------
    # Keadaan
    # ------------------------------------------------------------------

    @property
    def is_editable(self) -> bool:
        return self.status in ACTION_EDITABLE_STATUSES

    @property
    def is_applied(self) -> bool:
        """
        Penjaga idempotensi.

        Dibaca `applied_at`, bukan `status`: status bisa dipindahkan
        jalur lain, sedangkan stempel waktu ini hanya ditulis sekali oleh
        `EmployeeActionService.apply()` — dan itu satu-satunya penanda
        bahwa data pegawainya memang sudah berubah.
        """
        return self.applied_at is not None

    def rule(self) -> dict[str, tuple[str, ...]]:
        return ACTION_FIELD_RULES.get(
            self.action_type,
            {"fields": (), "required": ()},
        )

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    def clean(self):
        super().clean()

        errors = {}

        rule = self.rule()

        for field_name in rule["required"]:
            if getattr(self, f"{field_name}_id", None) is not None:
                continue

            if getattr(self, field_name, None) not in (None, ""):
                continue

            errors[field_name] = (
                "Wajib diisi untuk "
                f"{self.get_action_type_display()}."
            )

        # ---------------------------------------------------------
        # Kontrak
        # ---------------------------------------------------------

        if (
            self.proposed_contract_start
            and self.proposed_contract_end
            and self.proposed_contract_end < self.proposed_contract_start
        ):
            errors["proposed_contract_end"] = (
                "Contract End tidak boleh lebih awal dari Contract "
                "Start."
            )

        # ---------------------------------------------------------
        # Probation
        # ---------------------------------------------------------
        #
        # Tanggal hanya wajib kalau probation-nya memang dipakai.
        # "Probation Type kosong" adalah jawaban yang sah — pegawai yang
        # tidak menjalani masa percobaan tidak boleh dipaksa mengarang
        # dua tanggal.

        if (
            self.proposed_probation_start
            and self.proposed_probation_end
            and self.proposed_probation_end < self.proposed_probation_start
        ):
            errors["proposed_probation_end"] = (
                "Probation End tidak boleh lebih awal dari Probation "
                "Start."
            )

        if self.proposed_probation_type_id:
            for field_name, label in (
                ("proposed_probation_start", "Probation Start"),
                ("proposed_probation_end", "Probation End"),
            ):
                if getattr(self, field_name) is None:
                    errors[field_name] = (
                        f"{label} wajib diisi kalau Probation Type "
                        "dipilih."
                    )

        # ---------------------------------------------------------
        # Pemutusan
        # ---------------------------------------------------------

        if (
            self.action_type
            in {
                EmployeeActionType.RESIGNATION,
                EmployeeActionType.TERMINATION,
            }
            and self.last_working_date
            and self.effective_date
            and self.last_working_date < self.effective_date
        ):
            errors["last_working_date"] = (
                "Last Working Date tidak boleh lebih awal dari "
                "Effective Date."
            )

        if errors:
            raise ValidationError(errors)
