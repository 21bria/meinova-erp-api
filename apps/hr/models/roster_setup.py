"""
Versi rencana roster, dan dokumen setup massal yang melahirkannya.

Dua hal berbeda yang tinggal berdekatan karena dipakai bersamaan:

* ``RosterPlanVersion``  — satu baris per versi sebuah rencana
* ``RosterSetupRequest`` — dokumen bulk Site → Section → Employees
* ``RosterSetupLine``    — satu pegawai di dalam dokumen itu

Kenapa versi, bukan menyunting segmen di tempat
-----------------------------------------------
Karena "tidak ada silent edit" harus dijamin bentuk datanya, bukan
disiplin orang yang menulis service berikutnya. Segmen tidak pernah
di-UPDATE tanggalnya: yang ada tutup-dan-ganti lewat `version_from` /
`version_to` pada `RotationPeriod`.

Yang disalin cuma segmen yang **berubah**. Segmen masa lalu dimiliki
bersama oleh semua versi, jadi jumlah barisnya tidak meledak, dan —
yang lebih penting — `TravelRequest.rotation_period` yang menunjuk blok
lama tetap valid setelah adjustment.

Kenapa satu dokumen untuk 30 pegawai
------------------------------------
Approver tidak boleh menerima tiga puluh item kotak masuk yang isinya
sama. Konsekuensinya dua aturan yang ditegakkan service: satu batch =
satu Site (kalau tidak, cakupan approver tidak bisa ditentukan), dan
alurnya hanya boleh memakai step bertipe Role/User (tidak ada "atasan
langsung" dari tiga puluh orang).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee
from .rotation import RosterVersionSource, SiteRotation


class RosterPlanVersion(BaseModel):
    """
    Satu versi sebuah rencana.

    Versi 1 lahir saat rencana disetujui dan jadi baseline permanen.
    Versi berikutnya lahir dari adjustment, perubahan policy, atau
    perpanjangan horizon — masing-masing menyebut **dari kapan** ia
    berlaku dan **kenapa**.
    """

    plan = models.ForeignKey(
        SiteRotation,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    version_no = models.PositiveSmallIntegerField()

    source = models.CharField(
        max_length=30,
        choices=RosterVersionSource.choices,
        default=RosterVersionSource.INITIAL,
    )

    # Segmen sebelum tanggal ini tidak disentuh sama sekali. Itu yang
    # membuat "historical locked" bukan sekadar janji: perhitungan ulang
    # secara harfiah tidak menyentuh baris yang berakhir sebelumnya.
    effective_from = models.DateField(
        null=True,
        blank=True,
        help_text="Perubahan berlaku dari tanggal ini ke depan.",
    )

    # **Wajib.** Versi tanpa alasan tidak menjelaskan apa pun, dan enam
    # bulan kemudian tidak ada yang bisa menjawab kenapa jadwalnya
    # bergeser.
    reason = models.TextField(blank=True, default="")

    # Dokumen yang melahirkannya, ditunjuk lewat pasangan string —
    # pola yang sama dengan `WorkflowInstance`, supaya tabel ini tidak
    # perlu mengenal model modul mana pun.
    reference_type = models.CharField(max_length=50, blank=True, default="")
    reference_id = models.CharField(max_length=50, blank=True, default="")

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    committed_at = models.DateTimeField(null=True, blank=True)

    # Rekap hasil `RosterCalculationService.summarize()`, dibekukan.
    # Disimpan supaya daftar versi bisa menampilkan "berapa hari kerja
    # menurut versi ini" tanpa membaca ratusan segmen per baris.
    summary = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "hr_roster_plan_version"

        ordering = ["plan", "version_no"]

        constraints = [
            models.UniqueConstraint(
                fields=["plan", "version_no"],
                condition=Q(is_deleted=False),
                name="uniq_active_roster_plan_version",
            ),
        ]

        indexes = [
            models.Index(
                fields=["plan", "version_no"],
                name="idx_roster_version_plan",
            ),
        ]

    def __str__(self):
        return f"{self.plan_id} v{self.version_no}"


class RosterSetupStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"
    COMMITTED = "committed", "Committed"
    PARTIALLY_COMMITTED = "partial", "Partially Committed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class RosterSetupLineStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMMITTED = "committed", "Committed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class RosterSetupRequest(BaseModel):
    """
    Dokumen setup roster massal: Site → Section → Employees.

    Satu dokumen, satu pengajuan, satu item di kotak masuk approver.
    Rencana satuan tetap lewat dokumen yang sama dengan satu baris —
    satu jenis dokumen approval, bukan dua yang harus dijaga tetap sama.
    """

    document_number = models.CharField(max_length=50, blank=True, default="")

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_setups",
    )

    # **Wajib, dan satu per dokumen.** Batch yang mencampur site membuat
    # cakupan approver tidak bisa ditentukan, dan kebocorannya diam:
    # dokumennya tetap tampil, cuma di meja yang salah.
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="roster_setups",
        help_text="Site yang disetup. Satu dokumen = satu site.",
    )

    # Penyaring berjenjang di bawah site: Department dulu, baru Section.
    #
    # Keduanya opsional dan **berdiri sendiri** — Section boleh diisi
    # tanpa Department (di banyak tenant Section menempel langsung ke
    # Location). Yang dijaga cuma konsistensinya: kalau dua-duanya
    # diisi, Section harus milik Department itu.
    department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_setups",
        help_text="Penyaring opsional. Kosong = seluruh site.",
    )

    section = models.ForeignKey(
        "administration.Section",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_setups",
        help_text=(
            "Penyaring opsional, di bawah Department. Kosong = seluruh "
            "department."
        ),
    )

    # Keadaan direkam per tanggal ini. Segmen yang seluruhnya jatuh
    # sebelumnya tidak dibuat — roster ini tidak berpura-pura tahu apa
    # yang terjadi tahun lalu.
    as_of_date = models.DateField(
        help_text=(
            "Keadaan direkam per tanggal ini. Jadwal berangkat dari blok "
            "yang sedang dijalani, bukan dari awal riwayat."
        ),
    )

    horizon_months = models.PositiveSmallIntegerField(
        default=12,
        help_text="Jadwal digenerate sampai sekian bulan ke depan.",
    )

    status = models.CharField(
        max_length=20,
        choices=RosterSetupStatus.choices,
        default=RosterSetupStatus.DRAFT,
    )

    notes = models.TextField(blank=True, default="")

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    committed_at = models.DateTimeField(null=True, blank=True)

    # Kegagalan commit ditempel ke dokumennya sendiri, bukan cuma ke log
    # server. Alurnya sudah selesai dan keputusan approver sah;
    # melempar di titik itu menampilkan error pada orang yang tidak bisa
    # memperbaikinya.
    commit_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_roster_setup_request"

        ordering = ["-as_of_date", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_roster_setup_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["status"],
                name="idx_roster_setup_status",
            ),
            models.Index(
                fields=["location", "as_of_date"],
                name="idx_roster_setup_scope",
            ),
        ]

    @property
    def is_editable(self) -> bool:
        return self.status in {
            RosterSetupStatus.DRAFT,
            RosterSetupStatus.REJECTED,
        }

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.section_id
            and self.location_id
            and self.section.location_id
            and self.section.location_id != self.location_id
        ):
            errors["section"] = (
                "Section itu bukan milik site yang dipilih."
            )

        if (
            self.department_id
            and self.location_id
            and self.department.location_id
            and self.department.location_id != self.location_id
        ):
            errors["department"] = (
                "Department itu bukan milik site yang dipilih."
            )

        # Hanya diperiksa kalau **dua-duanya** diisi. Section boleh
        # berdiri tanpa Department — di banyak tenant ia menempel
        # langsung ke Location, dan mewajibkan induknya di sini membuat
        # penyaring yang seharusnya membantu justru menghalangi.
        if (
            self.section_id
            and self.department_id
            and self.section.department_id
            and self.section.department_id != self.department_id
        ):
            errors["section"] = (
                "Section itu bukan milik department yang dipilih."
            )

        # Lapisan ketiga untuk Company yang sekarang diisi dari form.
        # Dropdown Site sudah disaring per company, tapi penyaringan di
        # form bisa dilewati pemanggil API langsung — dan dokumen yang
        # company-nya berbeda dari site-nya membuat nomor dokumennya
        # diambil dari deret perusahaan yang salah.
        if (
            self.company_id
            and self.location_id
            and self.location.company_id
            and self.location.company_id != self.company_id
        ):
            errors["location"] = (
                "Site itu bukan milik company yang dipilih."
            )

        if self.horizon_months is not None and self.horizon_months < 1:
            errors["horizon_months"] = "Horizon minimal 1 bulan."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.document_number or 'RSU'} — "
            f"{self.location_id} ({self.as_of_date})"
        )


class RosterSetupLine(BaseModel):
    """
    Satu pegawai di dalam dokumen setup.

    Data tetap **per pegawai** walau dibuat massal: Current Cycle Start
    boleh berbeda-beda di dalam satu batch, dan itu justru keadaan
    normal di site yang gelombangnya bergantian.
    """

    request = models.ForeignKey(
        RosterSetupRequest,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="roster_setup_lines",
    )

    roster_policy = models.ForeignKey(
        "administration.RosterPolicy",
        on_delete=models.PROTECT,
        related_name="roster_setup_lines",
    )

    current_cycle_start = models.DateField(
        help_text=(
            "Boleh tanggal lampau — hari pertama blok yang sedang "
            "dijalani pegawai ini sekarang."
        ),
    )

    # Saldo rotation credit yang dibawa dari sistem lama. Dicatat
    # sebagai transaksi OPENING_BALANCE, bukan diketik langsung ke
    # saldo: angka tanpa jejak asal-usul tidak bisa dipertanggung-
    # jawabkan saat pegawainya bertanya.
    opening_rotation_credit = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text="Saldo awal rotation credit dari sistem lama.",
    )

    note = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=RosterSetupLineStatus.choices,
        default=RosterSetupLineStatus.PENDING,
    )

    commit_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_roster_setup_line"

        ordering = ["request", "employee__employee_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["request", "employee"],
                condition=Q(is_deleted=False),
                name="uniq_active_roster_setup_line",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_roster_setup_line_emp",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        policy = self.roster_policy if self.roster_policy_id else None

        if policy is not None and not policy.has_cycle_pattern:
            errors["roster_policy"] = (
                f"{policy.code} belum mengisi pola siklus, jadi tidak "
                "bisa menghasilkan jadwal."
            )

        if (
            self.opening_rotation_credit is not None
            and self.opening_rotation_credit < 0
        ):
            errors["opening_rotation_credit"] = (
                "Saldo awal tidak boleh negatif. Koreksi negatif dicatat "
                "sebagai transaksi penyesuaian, bukan sebagai saldo awal."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.employee_id} — {self.current_cycle_start}"
