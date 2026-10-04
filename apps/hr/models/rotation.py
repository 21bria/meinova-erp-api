"""
Roster kerja pegawai site (tambang, port, camp).

Bedanya dengan `RosterCrew` di `administration`: yang di sana adalah
**master gelombang** — pola siklus (`WorkSchedule` tipe ROSTER) plus satu
tanggal jangkar, dipakai banyak pegawai sekaligus. Yang di sini adalah
**jadwal milik satu pegawai**: baris ON/OFF yang benar-benar
dijadwalkan sepanjang tahun.

Keduanya dibutuhkan. Pola siklus saja tidak bisa menampung kenyataan
lapangan: swing yang mundur karena cuaca, blok yang digeser sehari.
Itu tanggal aktual, bukan rumus.

**Ini alat perencanaan, bukan dokumen pengajuan.** Tiket, akomodasi,
alasan kepulangan, dan tanda tangan persetujuan ada di
`TravelRequest` (`travel_request.py`) — satu dokumen per kepulangan,
bukan satu per tahun. Jadwal di sini hanya menghitung **perkiraan**
jendela travel di antara dua blok (lihat `RotationPeriod`); yang
benar-benar disimpan sebagai tanggal penerbangan adalah yang diajukan
dan disetujui di TR. Menyimpannya di dua tempat berarti dua tanggal
keberangkatan untuk penerbangan yang sama.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class SiteRotationStatus(models.TextChoices):
    """
    Siklus hidup satu rencana roster.

    Alurnya `DRAFT → SUBMITTED → APPROVED → ACTIVE`, lalu `COMPLETED`
    saat eranya ditutup karena polanya berubah permanen. `PLANNED`
    dipertahankan untuk dokumen lama yang dibuat sebelum ada approval.
    """

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"

    PLANNED = "planned", "Planned (legacy)"


# Status yang berarti rencananya sedang berlaku. Dipakai pemeriksaan
# tumpang tindih: dua rencana aktif untuk satu pegawai di periode yang
# sama berarti dua jadwal yang sama-sama mengaku benar.
ROSTER_LIVE_STATUSES = [
    SiteRotationStatus.APPROVED,
    SiteRotationStatus.ACTIVE,
    SiteRotationStatus.PLANNED,
]


class RosterVersionSource(models.TextChoices):
    """Apa yang melahirkan sebuah versi."""

    INITIAL = "initial", "Initial Baseline"
    ADJUSTMENT = "adjustment", "Operational Adjustment"
    POLICY_CHANGE = "policy_change", "Policy Change"
    HORIZON_EXTENSION = "horizon_extension", "Horizon Extension"
    CORRECTION = "correction", "Correction"


class RosterSegmentType(models.TextChoices):
    """
    Empat jenis segmen jadwal.

    `OFF` yang lama dipecah jadi `FIELD_BREAK` plus dua jenis travel,
    karena ketiganya berperilaku berbeda: field break adalah jatah
    istirahat, travel adalah hari perjalanan yang menurut policy bisa
    dihitung on-site (aturan #4) atau tidak (aturan #1). Menyatukannya
    jadi satu nilai membuat kedua aturan itu tidak bisa dibedakan sama
    sekali.

    **Segmen travel di sini adalah pita kalender rencana, bukan
    booking.** Nomor tiket, moda transportasi, dan akomodasi tetap
    milik `TravelArrangement` di dalam Travel Request — dan karena
    tidak ada tabel travel di sisi jadwal, tidak ada tempat untuk
    menaruhnya. Pencegahannya struktural, bukan disiplin.
    """

    WORK = "work", "On Site"
    FIELD_BREAK = "field_break", "Field Break"
    TRAVEL_OUT = "travel_out", "Travel Out"
    TRAVEL_IN = "travel_in", "Travel In"


class RotationPeriodType(models.TextChoices):
    """
    Kolom lama, dipertahankan sebagai **turunan** dari `segment_type`.

    Isinya sekarang menjawab satu pertanyaan saja: hari-hari di baris
    ini dihitung sebagai hari kerja atau tidak. `RotationPeriodService`
    yang mengisinya, dan pengisiannya ikut memperhitungkan
    `counts_as_roster_day` — jadi hari perjalanan yang menurut policy
    sudah On Site tetap terbaca `work` di sini.

    Yang membacanya `LeaveDayCalculator` dan laporan lama. Jangan diisi
    tangan; ubah `segment_type` dan biarkan service yang menurunkannya.
    """

    WORK = "work", "On Site"
    OFF = "off", "Off"


class RotationPeriodStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    ONGOING = "ongoing", "Ongoing"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class SiteRotation(BaseModel):
    # Nomor dokumen yang dicetak di kepala Travel Request. Diisi
    # `DocumentNumberService` dari NumberingSequence ("hr"/"site_rotation")
    # saat dokumen dibuat, tapi tetap boleh ditulis tangan: dokumen yang
    # dipindahkan dari sistem lama membawa nomornya sendiri.
    document_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="site_rotations",
    )

    # Didenormalisasi dari OrganizationAssignment aktif, pola yang sama
    # dengan EmployeeLeave/EmployeeAttendance. `location` di sini adalah
    # site tempat pegawai bekerja — yang jadi tujuan travel in.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="site_rotations",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="site_rotations",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="site_rotations",
    )

    # Asal pola siklusnya. Kosong = pola diisi manual di dokumen ini,
    # untuk pegawai yang rotasinya tidak mengikuti gelombang mana pun.
    roster_crew = models.ForeignKey(
        "administration.RosterCrew",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="site_rotations",
    )

    # ------------------------------------------------------------------
    # Pola yang dibekukan
    # ------------------------------------------------------------------
    #
    # Semuanya disalin dari policy saat dokumen dibuat, bukan dibaca
    # lewat relasi setiap kali. Rencana yang sudah disetujui dan sudah
    # dibelikan tiket tidak boleh berubah gara-gara ada yang mengoreksi
    # master bulan depan.

    roster_policy = models.ForeignKey(
        "administration.RosterPolicy",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_plans",
    )

    cycle_start = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Current Cycle Start yang dibekukan ke rencana ini."
        ),
    )

    roster_start_basis = models.CharField(
        max_length=20,
        blank=True,
        default="work_start",
    )

    travel_out_days = models.PositiveSmallIntegerField(default=0)
    travel_in_days = models.PositiveSmallIntegerField(default=0)

    travel_day_mode = models.CharField(
        max_length=20,
        blank=True,
        default="fixed",
    )

    travel_creates_segment = models.BooleanField(default=True)
    travel_out_counts_as_roster_day = models.BooleanField(default=False)
    travel_in_counts_as_roster_day = models.BooleanField(default=False)

    # ------------------------------------------------------------------
    # Era & horizon
    # ------------------------------------------------------------------
    #
    # Satu rencana = satu **era**: rentang waktu satu pola berlaku untuk
    # satu pegawai. Pola yang berubah permanen (8:2 → 6:2) menutup era
    # lama dan membuka era baru, bukan menulis ulang yang lama — riwayat
    # kontrak dan tiket yang sudah dibeli menunjuk jadwal yang lama, dan
    # jadwal itu harus tetap terbaca apa adanya.

    effective_from = models.DateField(null=True, blank=True)

    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text="Kosong = era berjalan.",
    )

    horizon_end = models.DateField(
        null=True,
        blank=True,
        help_text="Sampai kapan segmen sudah digenerate.",
    )

    # ------------------------------------------------------------------
    # Versi & baseline
    # ------------------------------------------------------------------

    current_version = models.ForeignKey(
        "hr.RosterPlanVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_of",
    )

    # Versi pertama yang disetujui. **Tidak pernah berubah** — itulah
    # yang membuat "jadwal yang disepakati" masih bisa ditunjukkan
    # setelah lima kali penyesuaian lapangan.
    baseline_version = models.ForeignKey(
        "hr.RosterPlanVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baseline_of",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Saat baseline dikunci. Sesudah ini jadwal hanya berubah "
            "lewat dokumen Adjustment."
        ),
    )

    # Dokumen setup massal yang melahirkan rencana ini, kalau ada.
    setup_line = models.ForeignKey(
        "hr.RosterSetupLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plans",
    )

    # Disalin dari crew saat dokumen dibuat, bukan dibaca ulang setiap
    # kali: dokumen roster membentang berbulan-bulan, dan mengubah
    # WorkSchedule master tahun depan tidak boleh diam-diam mengubah
    # jadwal yang sudah disepakati dan sudah dibelikan tiket.
    cycle_work_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Jumlah hari blok kerja, mis. 42 untuk 6 minggu.",
    )

    cycle_off_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Jumlah hari blok off, mis. 14 untuk 2 minggu.",
    )

    # Hari perjalanan **pulang-pergi**, di luar hitungan blok kerja
    # maupun blok off. Dipecah generator jadi dua jendela: keluar di
    # ujung blok kerja, kembali di ujung blok off — jadi panjang
    # siklusnya work + off + travel.
    #
    # Sengaja hari kalender tersendiri, bukan potongan dari Work Days:
    # pegawai 45/14 yang menghabiskan dua hari di kapal tetap menjalani
    # 45 hari di site. Memotongnya dari Work Days akan membuat rekap
    # "hari kerja setahun" mengecil padahal orangnya bekerja sama lama,
    # dan angka 45 yang tertulis di kontrak tidak lagi cocok dengan
    # angka mana pun di sistem.
    cycle_travel_days = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Total hari perjalanan pulang-pergi, di luar Work Days dan "
            "Off Days. 2 = sehari keluar, sehari kembali. Angka ganjil "
            "condong ke sisi keluar (3 = 2 keluar, 1 kembali). "
            "0 = travel dianggap masuk blok kerja."
        ),
    )

    start_date = models.DateField(
        help_text="Hari pertama blok kerja pada siklus pertama.",
    )

    # Berapa siklus (ON+OFF) yang digenerate sekali jalan. Bukan batas
    # permanen — dokumen bisa di-generate ulang dengan angka lebih besar
    # saat rosternya diperpanjang.
    cycle_count = models.PositiveSmallIntegerField(
        default=4,
    )

    # Diisi generator dari periode terakhir. Read-only di form, tapi
    # disimpan supaya daftar roster bisa disortir dan difilter tanpa
    # menembus tabel periode.
    end_date = models.DateField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=SiteRotationStatus.choices,
        default=SiteRotationStatus.PLANNED,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_site_rotation"

        ordering = [
            "-start_date",
            "employee",
        ]

        constraints = [
            # Dikondisikan ke dokumen aktif yang nomornya memang terisi:
            # nomor kosong sah (sequence-nya belum diseed) dan tidak boleh
            # saling bentrok sebagai "duplikat".
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_site_rotation_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_site_rotation_employee",
            ),
            models.Index(
                fields=["start_date", "end_date"],
                name="idx_site_rotation_period",
            ),
            models.Index(
                fields=["status"],
                name="idx_site_rotation_status",
            ),
        ]

    @property
    def cycle_length(self) -> int | None:
        """
        Panjang satu putaran penuh dalam hari kalender.

        `cycle_travel_days` adalah **total pulang-pergi**, jadi cukup
        ditambahkan sekali. Angka inilah yang dipakai
        `next_cycle_start()` untuk menggeser jangkar crew; memakai
        work+off saja akan membuat jangkarnya meleset sebanyak travel
        setiap siklus.
        """
        work = self.cycle_work_days or 0
        off = self.cycle_off_days or 0
        travel = self.cycle_travel_days or 0

        return (work + off + travel) or None

    def clean(self):
        super().clean()

        errors = {}

        # Serializer sengaja membolehkan kolom ini kosong supaya service
        # bisa menurunkannya dari jangkar crew. Kalau sampai di sini
        # masih kosong berarti tidak ada crew yang bisa jadi acuan, dan
        # pesan bawaan Django ("This field cannot be null") tidak
        # memberi tahu apa yang harus dilakukan.
        if not self.start_date:
            errors["start_date"] = (
                "Start Date wajib diisi. Pilih Roster Crew supaya "
                "terisi otomatis dari jangkar siklusnya, atau isi "
                "manual."
            )

        # Nol hari kerja atau nol hari off bukan roster — siklusnya tidak
        # pernah berganti, dan generator akan berputar tanpa henti.
        if not self.cycle_work_days:
            errors["cycle_work_days"] = (
                "Cycle Work Days wajib diisi. Pilih Roster Crew supaya "
                "terisi otomatis dari pola kerjanya, atau isi manual."
            )

        if not self.cycle_off_days:
            errors["cycle_off_days"] = (
                "Cycle Off Days wajib diisi. Pilih Roster Crew supaya "
                "terisi otomatis dari pola kerjanya, atau isi manual."
            )

        if not self.cycle_count:
            errors["cycle_count"] = (
                "Cycle Count minimal 1."
            )

        if (
            self.end_date
            and self.start_date
            and self.end_date < self.start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if (
            self.location_id
            and self.company_id
            and self.location.company_id != self.company_id
        ):
            errors["location"] = (
                "Location tidak termasuk dalam Company yang dipilih."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"Rotation {self.start_date}"
        )


class RotationPeriod(BaseModel):
    rotation = models.ForeignKey(
        SiteRotation,
        on_delete=models.CASCADE,
        related_name="periods",
    )

    # Didenormalisasi dari `rotation.employee` supaya pertanyaan
    # operasional yang paling sering ditanya — "siapa saja yang di site
    # hari ini?" — jadi satu query satu tabel, bukan join ke dokumen.
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="rotation_periods",
    )

    # Menghitung ON dan OFF bersama-sama: 1 = ON#1, 2 = OFF#1, 3 = ON#2.
    # Urutan gabungan seperti ini membuat baris tabelnya bisa diurutkan
    # apa adanya tanpa mengurutkan dua kolom.
    sequence = models.PositiveSmallIntegerField()

    period_type = models.CharField(
        max_length=10,
        choices=RotationPeriodType.choices,
        help_text=(
            "Turunan dari Segment Type — diisi service, jangan diketik."
        ),
    )

    # Jenis segmen yang sebenarnya. `period_type` di atas cuma
    # ringkasannya jadi dua nilai untuk pemanggil lama.
    #
    # Empat jenis, bukan dua: field break adalah jatah istirahat,
    # sedangkan travel adalah hari perjalanan yang menurut policy bisa
    # dihitung on-site. Menyatukannya jadi "off" membuat aturan #1 dan
    # #4 dokumen Substansi Roster tidak bisa dibedakan sama sekali.
    segment_type = models.CharField(
        max_length=20,
        choices=RosterSegmentType.choices,
        default=RosterSegmentType.WORK,
        db_index=True,
    )

    # Hari di baris ini dihitung sebagai hari on-site di rekap.
    # **Tidak** memendekkan blok kerja — pegawai 45/14 yang dua hari di
    # kapal tetap menjalani 45 hari di site.
    counts_as_roster_day = models.BooleanField(
        default=True,
    )

    # Putaran ke berapa baris ini. Disimpan, bukan dihitung dari
    # sequence: setelah ada penyisipan dan penggeseran, nomor urut tidak
    # lagi kelipatan tetap dari jumlah segmen per putaran.
    cycle_number = models.PositiveSmallIntegerField(
        default=1,
    )

    # ------------------------------------------------------------------
    # Interval versi
    # ------------------------------------------------------------------
    #
    # **Segmen tidak pernah disunting tanggalnya di tempat.** Yang ada
    # cuma tutup-dan-ganti: baris lama ditutup (`version_to` diisi),
    # baris pengganti masuk dengan `version_from` versi baru. Itu yang
    # membuat "jadwal yang disetujui" tetap bisa dibaca setelah lima
    # kali penyesuaian, tanpa menyalin seluruh isi dokumen tiap versi.
    #
    # Konsekuensi yang menguntungkan: segmen masa lalu tidak pernah
    # diganti, jadi `TravelRequest.rotation_period` yang menunjuknya
    # tetap valid setelah adjustment.
    version_from = models.ForeignKey(
        "hr.RosterPlanVersion",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="segments_added",
    )

    version_to = models.ForeignKey(
        "hr.RosterPlanVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segments_closed",
        help_text="Kosong = masih berlaku pada versi berjalan.",
    )

    # Nilai saat baris ini pertama kali dibaselinekan. Dipakai layar
    # pembanding "rencana vs sekarang"; tanpa disimpan, pergeseran
    # akibat adjustment tidak bisa ditunjukkan sebagai selisih.
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)

    # Baris yang sudah dijalani atau sudah dibaselinekan. Yang terkunci
    # tidak boleh ikut berubah saat jadwal dihitung ulang dari satu
    # titik ke depan.
    is_locked = models.BooleanField(default=False)

    # Kolom "Travel Purpose" di form Travel Request. Blok off yang sama
    # bisa dipecah jadi beberapa baris dengan alasan berbeda — 7 hari
    # field break lalu 12 hari cuti tahunan — dan itu yang menentukan
    # saldo mana yang terpakai. Blok kerja tidak punya alasan; yang
    # menjaganya `clean()`.
    #
    # Menunjuk `RotationPurpose`, bukan `LeaveType`: field break adalah
    # blok off rosternya sendiri dan tidak memotong saldo apa pun,
    # sedangkan cuti tahunan memotong. Yang membedakan keduanya
    # `RotationPurpose.deducts_leave`.
    purpose = models.ForeignKey(
        "administration.RotationPurpose",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rotation_periods",
    )

    # Record cuti yang benar-benar memotong saldo. Sengaja tautan, bukan
    # perhitungan sendiri: `EmployeeLeave` sudah punya kalkulator hari
    # kerja dan penjumlah ulang saldo, dan menyalin logikanya ke sini
    # berarti dua sumber angka untuk cuti yang sama.
    #
    # SET_NULL, bukan CASCADE: menghapus catatan cuti tidak boleh ikut
    # menghapus blok off dari jadwal rotasi — orangnya tetap tidak di
    # site pada tanggal itu.
    employee_leave = models.ForeignKey(
        "hr.EmployeeLeave",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_periods",
    )

    start_date = models.DateField()
    end_date = models.DateField()

    # Disimpan, bukan properti: kolom ini dipakai untuk sortir dan
    # rekap hari kerja di tabel.
    total_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    # Ditandai begitu barisnya disunting tangan. Generator memakai tanda
    # ini untuk menolak menimpa penyesuaian yang sudah dibuat orang.
    is_manual_override = models.BooleanField(
        default=False,
    )

    status = models.CharField(
        max_length=20,
        choices=RotationPeriodStatus.choices,
        default=RotationPeriodStatus.SCHEDULED,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_rotation_period"

        # Kronologis dulu, baru nomor urut. Baris hasil generate sudah
        # urut dua-duanya, tapi baris sisipan — blok off yang dipecah jadi
        # field break + cuti tahunan — mendapat nomor urut terakhir yang
        # bebas, dan mengurutkannya dari nomor akan melemparnya ke dasar
        # tabel, jauh dari blok yang dipecahnya.
        ordering = [
            "rotation",
            "start_date",
            "sequence",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["rotation", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_rotation_period_sequence",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "start_date", "end_date"],
                name="idx_rotation_period_emp_range",
            ),
            models.Index(
                fields=["period_type"],
                name="idx_rotation_period_type",
            ),
        ]

    @property
    def day_count(self) -> int | None:
        if not self.start_date or not self.end_date:
            return None

        return (self.end_date - self.start_date).days + 1

    # ------------------------------------------------------------------
    # Jendela travel — dihitung, tidak disimpan
    # ------------------------------------------------------------------
    #
    # Hari perjalanan menempati hari kalender di antara dua blok, jadi
    # jendelanya sudah tersirat dari `cycle_travel_days` dokumen induk
    # dan tidak perlu baris tersendiri. Yang benar-benar disimpan
    # sebagai tanggal penerbangan adalah `TravelArrangement` di dalam
    # Travel Request — itu yang diajukan, disetujui, dan dibelikan
    # tiket. Angka di sini cuma perkiraan untuk ditampilkan dan untuk
    # mengisi awal formulir TR.

    @property
    def travel_days(self) -> int:
        """
        Jendela travel yang mengekor di ujung blok **ini** saja.

        `cycle_travel_days` adalah total pulang-pergi; blok kerja
        diikuti porsi keluar, blok off diikuti porsi kembali. Ganjil
        condong ke sisi keluar.
        """
        rotation = self.rotation

        if rotation is None:
            return 0

        total = rotation.cycle_travel_days or 0

        if self.period_type == RotationPeriodType.WORK:
            return -(-total // 2)

        return total // 2

    @property
    def travel_window_start(self):
        """Hari pertama perjalanan yang mengekor di ujung blok ini."""
        from datetime import timedelta

        if not self.travel_days or not self.end_date:
            return None

        return self.end_date + timedelta(days=1)

    @property
    def travel_window_end(self):
        from datetime import timedelta

        if not self.travel_days or not self.end_date:
            return None

        return self.end_date + timedelta(days=self.travel_days)

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.start_date
            and self.end_date
            and self.end_date < self.start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if self.total_days is not None and self.total_days < 1:
            errors["total_days"] = (
                "Total Days minimal 1."
            )

        # Alasan hanya melekat pada blok off. Blok kerja yang diberi
        # "Cuti Tahunan" akan tampil di laporan sebagai hari yang memotong
        # saldo padahal orangnya sedang di site.
        if (
            self.period_type == RotationPeriodType.WORK
            and (self.purpose_id or self.employee_leave_id)
        ):
            errors["purpose"] = (
                "Travel Purpose hanya berlaku untuk periode Off."
            )

        # Cuti milik orang lain yang nyantol ke periode ini akan
        # menampilkan saldo yang bukan miliknya di dokumen.
        if (
            self.employee_leave_id
            and self.employee_id
            and self.employee_leave.employee_id != self.employee_id
        ):
            errors["employee_leave"] = (
                "Catatan cuti itu milik pegawai lain."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} #{self.sequence} "
            f"{self.get_period_type_display()} "
            f"({self.start_date} s/d {self.end_date})"
        )
