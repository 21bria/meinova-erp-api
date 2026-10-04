"""
Perubahan operasional pada jadwal roster yang sudah berjalan.

Beda dengan perubahan policy permanen, dan ini yang paling sering
tertukar:

* **Adjustment** — kapal delay, blok diperpanjang, cuti dimundurkan.
  Polanya tidak berubah; yang berubah tanggal-tanggalnya, mulai dari
  satu titik ke depan. Versi baru pada rencana yang sama.
* **Perubahan policy permanen** (8:2 → 6:2) — era lama ditutup, era
  baru dibuka sebagai rencana tersendiri. Riwayatnya tetap utuh karena
  jadwal lama tidak pernah ditulis ulang.

Mencampur keduanya berarti kehilangan salah satu: kalau semua jadi
adjustment, "pola apa yang berlaku tahun lalu" tidak bisa dijawab;
kalau semua jadi era baru, setiap kapal yang telat melahirkan dokumen
rencana baru.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee
from .rotation import SiteRotation


class AdjustmentKind(models.TextChoices):
    """
    Yang membedakan bukan berapa harinya, melainkan **siapa
    penyebabnya** — dan itu tidak bisa disimpulkan sistem dari selisih
    tanggal, jadi harus disebut pemakainya.

    Empat yang pertama diturunkan langsung dari aturan #13, #14, #17,
    dan #18 dokumen "Substansi Roster".
    """

    WORK_EXTENSION = "work_extension", "Work Extension"
    EARLY_RETURN = "early_return", "Early Return"
    DEFERRED_LEAVE = "deferred_leave", "Deferred Leave (KTT approved)"
    LATE_RETURN = "late_return", "Late Return (employee fault)"
    LOYALTY = "loyalty", "Deferred Leave (no approval)"
    NO_IMPACT = "no_impact", "No Impact (beyond employee control)"
    SCHEDULE_SHIFT = "schedule_shift", "Schedule Shift"
    CREDIT_USE = "credit_use", "Use Rotation Credit"


class CreditImpact(models.TextChoices):
    NONE = "none", "No Credit Impact"
    EARN = "earn", "Earn Credit"
    USE = "use", "Use Credit"


class AdjustmentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"
    APPLIED = "applied", "Applied"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


# Jenis yang memang tidak mengubah satu tanggal pun. Tetap dicatat dan
# tetap punya penjelasan tertulis — "kenapa jadwal saya tidak berubah"
# harus ada jawabannya, dan diam adalah jawaban terburuk.
NO_SCHEDULE_CHANGE = {
    AdjustmentKind.LOYALTY,
    AdjustmentKind.NO_IMPACT,
}


class RosterAdjustment(BaseModel):
    document_number = models.CharField(max_length=50, blank=True, default="")

    plan = models.ForeignKey(
        SiteRotation,
        on_delete=models.CASCADE,
        related_name="adjustments",
    )

    # Didenormalisasi dari rencana, supaya penyaringan cakupan data
    # dan filter tabel tidak perlu menembus dokumen induknya.
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="roster_adjustments",
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_adjustments",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_adjustments",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_adjustments",
    )

    adjustment_kind = models.CharField(
        max_length=30,
        choices=AdjustmentKind.choices,
    )

    # Titik mulai perhitungan ulang. Segmen yang berakhir sebelum
    # tanggal ini tidak disentuh sama sekali — itu yang membuat
    # "historical locked" bukan sekadar janji.
    effective_date = models.DateField(
        help_text=(
            "Perubahan berlaku dari tanggal ini ke depan. Jadwal "
            "sebelumnya tidak disentuh."
        ),
    )

    segment = models.ForeignKey(
        "hr.RotationPeriod",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
        help_text=(
            "Segmen sasaran. Dikosongkan = ditentukan dari Effective "
            "Date."
        ),
    )

    days = models.PositiveSmallIntegerField(
        default=0,
        help_text="Selalu positif. Arahnya ditentukan jenis penyesuaian.",
    )

    new_cycle_start = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Untuk kasus jangkar digeser, bukan blok diperpanjang. "
            "Dikosongkan = jangkar dihitung dari jadwal yang bertahan."
        ),
    )

    credit_impact = models.CharField(
        max_length=10,
        choices=CreditImpact.choices,
        default=CreditImpact.NONE,
    )

    # Diisi service dari konversi, read-only di form. Dibekukan supaya
    # rasio yang berubah tahun depan tidak mengubah arti angka yang
    # sudah tercatat.
    credit_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    # **Wajib.** Penyesuaian tanpa alasan tidak menjelaskan apa pun, dan
    # enam bulan kemudian tidak ada yang bisa menjawab kenapa jadwalnya
    # bergeser.
    reason = models.TextField()

    reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Nomor TR, nomor tiket, atau nomor memo.",
    )

    status = models.CharField(
        max_length=20,
        choices=AdjustmentStatus.choices,
        default=AdjustmentStatus.DRAFT,
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Penjaga idempotensi. **Bukan `status`** — dua permintaan
    # bersamaan sama-sama membaca status "approved" sebelum salah
    # satunya sempat mengubahnya, dan jadwalnya digeser dua kali.
    applied_at = models.DateTimeField(null=True, blank=True)

    # Kegagalan penerapan ditempel ke dokumennya sendiri, bukan cuma ke
    # log server. Alurnya sudah selesai dan keputusan approver sah;
    # melempar di titik itu menampilkan error pada orang yang tidak bisa
    # memperbaikinya.
    apply_error = models.TextField(blank=True, default="")

    resulting_version = models.ForeignKey(
        "hr.RosterPlanVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
    )

    class Meta:
        db_table = "hr_roster_adjustment"

        ordering = ["-effective_date", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_roster_adjustment_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["plan", "effective_date"],
                name="idx_roster_adj_plan_date",
            ),
            models.Index(
                fields=["status"],
                name="idx_roster_adj_status",
            ),
            models.Index(
                fields=["employee"],
                name="idx_roster_adj_employee",
            ),
        ]

    @property
    def is_editable(self) -> bool:
        return self.status in {
            AdjustmentStatus.DRAFT,
            AdjustmentStatus.REJECTED,
        }

    @property
    def changes_schedule(self) -> bool:
        return self.adjustment_kind not in NO_SCHEDULE_CHANGE

    def clean(self):
        super().clean()

        errors = {}

        if not (self.reason or "").strip():
            errors["reason"] = (
                "Alasan wajib diisi — jadwal yang bergeser tanpa alasan "
                "tidak bisa dijelaskan ke siapa pun enam bulan lagi."
            )

        if self.changes_schedule and not self.days and not self.new_cycle_start:
            errors["days"] = (
                "Sebutkan jumlah hari, atau tanggal jangkar yang baru."
            )

        if (
            self.plan_id
            and self.employee_id
            and self.plan.employee_id != self.employee_id
        ):
            errors["employee"] = (
                "Rencana itu milik pegawai lain."
            )

        if (
            self.segment_id
            and self.plan_id
            and self.segment.rotation_id != self.plan_id
        ):
            errors["segment"] = (
                "Segmen itu bukan milik rencana yang dipilih."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.document_number or 'RAJ'} — "
            f"{self.get_adjustment_kind_display()} "
            f"({self.effective_date})"
        )
