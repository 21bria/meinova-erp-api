from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel
from apps.uploads.models import UploadedFile

from .employee import Employee


class VacancyStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    ON_HOLD = "on_hold", "On Hold"
    FILLED = "filled", "Filled"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


class InterviewResult(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    NO_SHOW = "no_show", "No Show"
    CANCELLED = "cancelled", "Cancelled"


class JobVacancy(BaseModel):
    code = models.CharField(max_length=50)
    title = models.CharField(max_length=200)

    # Company wajib, level di bawahnya boleh kosong — mengikuti aturan
    # struktur organisasi di CLAUDE.md.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="job_vacancies",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_vacancies",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_vacancies",
    )

    division = models.ForeignKey(
        "administration.Division",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_vacancies",
    )

    department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_vacancies",
    )

    position = models.ForeignKey(
        "administration.Position",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_vacancies",
    )

    employment_type = models.ForeignKey(
        "administration.EmploymentType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_vacancies",
    )

    quota = models.PositiveSmallIntegerField(default=1)

    open_date = models.DateField()
    close_date = models.DateField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=VacancyStatus.choices,
        default=VacancyStatus.DRAFT,
    )

    description = models.TextField(
        blank=True,
        default="",
    )

    requirements = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_job_vacancy"

        ordering = [
            "-open_date",
            "title",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_job_vacancy_code",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company"],
                name="idx_vacancy_company",
            ),
            models.Index(
                fields=["status"],
                name="idx_vacancy_status",
            ),
            models.Index(
                fields=["open_date"],
                name="idx_vacancy_open_date",
            ),
        ]

    @property
    def candidate_count(self) -> int:
        return self.candidates.filter(is_deleted=False).count()

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.open_date
            and self.close_date
            and self.close_date < self.open_date
        ):
            errors["close_date"] = (
                "Close Date tidak boleh lebih awal dari Open Date."
            )

        if self.quota is not None and self.quota <= 0:
            errors["quota"] = "Quota harus lebih besar dari nol."

        # Penjagaan yang sama dengan OrganizationAssignment: unit kerja
        # yang dipilih harus benar-benar milik induknya.
        if (
            self.branch_id
            and self.company_id
            and self.branch.company_id != self.company_id
        ):
            errors["branch"] = (
                "Branch tidak termasuk dalam Company yang dipilih."
            )

        if (
            self.location_id
            and self.branch_id
            and self.location.branch_id
            and self.location.branch_id != self.branch_id
        ):
            errors["location"] = (
                "Location tidak termasuk dalam Branch yang dipilih."
            )

        if (
            self.department_id
            and self.division_id
            and self.department.division_id
            and self.department.division_id != self.division_id
        ):
            errors["department"] = (
                "Department tidak termasuk dalam Division yang dipilih."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.code} - {self.title}"


class Candidate(BaseModel):
    candidate_number = models.CharField(max_length=50)

    vacancy = models.ForeignKey(
        JobVacancy,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    full_name = models.CharField(max_length=200)

    email = models.EmailField(
        blank=True,
        default="",
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    gender = models.ForeignKey(
        "administration.Gender",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    birth_date = models.DateField(
        null=True,
        blank=True,
    )

    education = models.ForeignKey(
        "administration.Education",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    source = models.ForeignKey(
        "administration.RecruitmentSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    status = models.ForeignKey(
        "administration.CandidateStatus",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    applied_date = models.DateField()

    expected_salary = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    currency = models.ForeignKey(
        "administration.Currency",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    rejection_reason = models.ForeignKey(
        "administration.RejectionReason",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
    )

    resume_file = models.OneToOneField(
        UploadedFile,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )

    # Terisi setelah kandidat diterima dan datanya dibuat jadi pegawai.
    # Jadi jejak "dari kandidat mana pegawai ini berasal" tidak hilang.
    hired_employee = models.OneToOneField(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidate_origin",
    )

    hired_date = models.DateField(
        null=True,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_candidate"

        ordering = [
            "-applied_date",
            "full_name",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["candidate_number"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_candidate_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["vacancy"],
                name="idx_candidate_vacancy",
            ),
            models.Index(
                fields=["status"],
                name="idx_candidate_status",
            ),
            models.Index(
                fields=["applied_date"],
                name="idx_candidate_applied",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.applied_date
            and self.hired_date
            and self.hired_date < self.applied_date
        ):
            errors["hired_date"] = (
                "Hired Date tidak boleh lebih awal dari Applied Date."
            )

        if (
            self.expected_salary is not None
            and self.expected_salary < 0
        ):
            errors["expected_salary"] = (
                "Expected Salary tidak boleh negatif."
            )

        if (
            self.expected_salary is not None
            and self.expected_salary > 0
            and self.currency_id is None
        ):
            errors["currency"] = (
                "Currency wajib diisi jika Expected Salary diisi."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.candidate_number} - {self.full_name}"


class CandidateInterview(BaseModel):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="interviews",
    )

    interview_type = models.ForeignKey(
        "administration.InterviewType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidate_interviews",
    )

    # Urutan tahap (1, 2, 3...) — dipakai untuk mengurutkan tampilan,
    # bukan untuk memaksa jumlah tahap tertentu.
    stage = models.PositiveSmallIntegerField(default=1)

    scheduled_at = models.DateTimeField()

    interviewer = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidate_interviews",
    )

    result = models.CharField(
        max_length=20,
        choices=InterviewResult.choices,
        default=InterviewResult.SCHEDULED,
    )

    score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_candidate_interview"

        ordering = [
            "candidate",
            "stage",
            "scheduled_at",
        ]

        indexes = [
            models.Index(
                fields=["candidate"],
                name="idx_interview_candidate",
            ),
            models.Index(
                fields=["scheduled_at"],
                name="idx_interview_scheduled",
            ),
            models.Index(
                fields=["result"],
                name="idx_interview_result",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.stage is not None and self.stage <= 0:
            errors["stage"] = "Stage harus lebih besar dari nol."

        if self.score is not None and self.score < 0:
            errors["score"] = "Score tidak boleh negatif."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.candidate.candidate_number} - "
            f"Stage {self.stage}"
        )
