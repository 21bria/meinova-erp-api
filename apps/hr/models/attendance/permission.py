"""
Attendance Permission — izin kehadiran yang **bukan** cuti.

Izin masuk terlambat, pulang lebih awal, keluar sementara, atau tidak
masuk satu hari tanpa memotong saldo cuti. Domain tersendiri di dalam
modul Attendance, dan itu keputusan yang sengaja diambil.

Kenapa bukan `LeaveType` baru
-----------------------------
Cuti punya **saldo**, punya **entitlement bertahun**, punya carry over,
opening balance, dan go-live date. Izin tidak punya satu pun dari
semuanya: yang ditanyakan izin adalah "jam berapa dia boleh datang hari
ini", bukan "berapa sisa haknya tahun ini". Menumpangkannya ke
`LeaveType` berarti setiap perhitungan saldo harus mengecualikan tipe
itu dengan `if`, dan `LeaveBalance` terisi baris yang angkanya tidak
pernah berarti apa-apa. Sudah pernah terjadi di modul lain: lihat
alasan `VisitorRequest` tidak menumpang `TravelRequest`.

Yang **tidak** dilakukan dokumen ini
------------------------------------
Ia tidak menyentuh satu baris pun presensi mentah. Tap sidik jari
adalah fakta transaksi; izin hanya memberi **konteks** atas pengecualian
yang lahir dari fakta itu. Konsekuensinya `late_minutes` tidak pernah
berkurang karena ada izin — yang berubah klasifikasinya
(`excused` vs `unauthorized`), dan itu ditulis di kolom terpisah supaya
angka menurut mesin tetap terbaca di sebelah keputusan orang. Pelajaran
yang sama dengan `leave_required_days` vs `leave_required_override`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel
from apps.uploads.models.uploaded_file import UploadedFile


class AttendancePermissionType(models.TextChoices):
    """
    Empat bentuk izin, dan yang membedakannya **kolom jam mana yang
    dipakai** — bukan sekadar label.

    * `LATE_ARRIVAL`   — `end_time` = boleh datang paling lambat jam
    * `EARLY_LEAVE`    — `start_time` = boleh pulang mulai jam
    * `TEMPORARY_OUT`  — keduanya, sebuah jendela di tengah jam kerja
    * `FULL_DAY`       — tidak satu pun; yang diizinkan seharian

    Ditulis sebagai `TextChoices`, bukan master: keempatnya menentukan
    **cara hitung** yang berbeda di resolver, dan aturan hitung tidak
    bisa dikarang tenant lewat layar master. Yang memang boleh berbeda
    per tenant adalah perlakuan payroll-nya, dan itu tinggal di
    `PayrollPermissionRule`.
    """

    LATE_ARRIVAL = "late_arrival", "Late Arrival"
    EARLY_LEAVE = "early_leave", "Early Leave"
    TEMPORARY_OUT = "temporary_out", "Temporary Out"
    FULL_DAY = "full_day", "Full Day Permission"


class AttendancePermissionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    IN_REVIEW = "in_review", "In Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


# Status yang membuat dokumennya masih "hidup" — dipakai menolak izin
# kedua yang tumpang tindih pada tanggal yang sama.
#
# REJECTED dan CANCELLED sengaja tidak ikut: pengajuan yang ditolak
# harus bisa diajukan ulang untuk jendela yang sama, dan yang dibatalkan
# tidak lagi menahan apa pun.
PERMISSION_ACTIVE_STATUSES = [
    AttendancePermissionStatus.DRAFT,
    AttendancePermissionStatus.SUBMITTED,
    AttendancePermissionStatus.IN_REVIEW,
    AttendancePermissionStatus.APPROVED,
]


# Satu-satunya status yang boleh dibaca mesin presensi.
#
# Pengajuan yang masih berjalan **tidak** memaafkan apa pun — kalau ia
# ikut dibaca, setiap orang bisa membebaskan keterlambatannya sendiri
# dengan mengetik dokumen yang tidak pernah disetujui siapa pun.
PERMISSION_EFFECTIVE_STATUSES = [
    AttendancePermissionStatus.APPROVED,
]


# Status yang layak ditampilkan sebagai badge "Permission Pending" di
# layar presensi. Bukan pembebasan — penjelasan kenapa baris yang
# tampak melanggar sedang menunggu keputusan.
PERMISSION_PENDING_STATUSES = [
    AttendancePermissionStatus.SUBMITTED,
    AttendancePermissionStatus.IN_REVIEW,
]


class AttendancePermission(BaseModel):
    document_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_permissions",
    )

    # Snapshot organisasi, pola yang sama dengan EmployeeAttendance dan
    # EmployeeLeave: cakupan data menyaring baris lewat kolom di
    # dokumennya sendiri, bukan lewat join ke penempatan yang bisa
    # berubah setelah dokumennya terbit.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_permissions",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_permissions",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_permissions",
    )

    permission_type = models.CharField(
        max_length=20,
        choices=AttendancePermissionType.choices,
        db_index=True,
    )

    # **Tanggal shift, bukan tanggal kalender jam-nya.** Shift malam
    # 20:00–05:00 yang izin keluarnya 00:30 tetap bertanggal hari
    # shift-nya dimulai — sama persis dengan `EmployeeAttendance
    # .work_date`. Kalau tidak, satu shift punya dua tanggal dan tidak
    # ada satu pun query yang bisa mempertemukan izin dengan presensinya.
    date = models.DateField(db_index=True)

    start_time = models.TimeField(
        null=True,
        blank=True,
        help_text=(
            "Early Leave: boleh pulang mulai jam ini. Temporary Out: "
            "jam mulai izin. Late Arrival & Full Day: dikosongkan."
        ),
    )

    end_time = models.TimeField(
        null=True,
        blank=True,
        help_text=(
            "Late Arrival: boleh datang paling lambat jam ini. "
            "Temporary Out: jam kembali. Early Leave & Full Day: "
            "dikosongkan."
        ),
    )

    reason = models.TextField()

    notes = models.TextField(blank=True, default="")

    supporting_document = models.OneToOneField(
        UploadedFile,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=AttendancePermissionStatus.choices,
        default=AttendancePermissionStatus.DRAFT,
        db_index=True,
    )

    # ------------------------------------------------------------------
    # Izin di luar jendela shift
    # ------------------------------------------------------------------
    #
    # Bawaannya ditolak (lihat `AttendancePermissionService`): izin
    # 18:00–20:00 untuk orang bershift 08:00–17:00 hampir selalu salah
    # ketik tanggal, dan menerimanya diam-diam menghasilkan dokumen yang
    # tidak memaafkan apa pun lalu jadi keluhan sebulan kemudian.
    #
    # Saklarnya ada karena kasus sahnya juga nyata: shift yang baru
    # diubah sesudah izinnya disetujui, atau pegawai yang jadwalnya
    # memang belum tersusun di master. Yang boleh menyalakannya HR, dan
    # alasannya wajib ditulis.
    allow_outside_shift = models.BooleanField(
        default=False,
        help_text=(
            "Override HR: terima izin yang jam-nya di luar jendela "
            "shift pegawai. Wajib disertai alasan."
        ),
    )

    outside_shift_reason = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Wajib diisi saat override dinyalakan. Override tanpa "
            "alasan tertulis tidak bisa dijelaskan saat diaudit."
        ),
    )

    # ------------------------------------------------------------------
    # Jejak waktu keputusan
    # ------------------------------------------------------------------
    #
    # Empat kolom, bukan satu `decided_at` plus status: pengajuan yang
    # disetujui lalu dibatalkan harus tetap memperlihatkan **kapan**
    # ia pernah disetujui. Satu kolom yang ditimpa membuang jejak itu.

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_attendance_permission"

        verbose_name = "Attendance Permission"
        verbose_name_plural = "Attendance Permissions"

        ordering = ["-date", "employee_id", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_attendance_permission_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "date"],
                name="idx_att_perm_employee_date",
            ),
            models.Index(
                fields=["company", "date"],
                name="idx_att_perm_company_date",
            ),
            models.Index(
                fields=["status", "date"],
                name="idx_att_perm_status_date",
            ),
        ]

        # Menerbitkan izin **di luar jam kerja** pegawainya.
        #
        # Izin tersendiri karena ia bukan bagian dari CRUD: yang boleh
        # mengajukan izin (`add_attendancepermission` — setiap pegawai,
        # untuk dirinya sendiri) tidak dengan sendirinya boleh
        # mem-bypass `assert_within_shift`, satu-satunya penjagaan yang
        # memastikan izin berada di dalam jam kerja. Sampai izin ini
        # ada, keduanya satu kotak yang sama dan `allow_outside_shift`
        # cukup dikirim dari formulir.
        #
        # Izin Django biasa, jadi ia muncul di layar Roles dan bisa
        # dicentang per tenant — bukan daftar kode role di dalam kode.
        permissions = [
            (
                "override_attendancepermission",
                "Can allow attendance permission outside shift",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.document_number or self.pk} - "
            f"{self.employee_id} - {self.date} - "
            f"{self.get_permission_type_display()}"
        )

    # ------------------------------------------------------------------
    # Bentuk yang diharapkan tiap tipe
    # ------------------------------------------------------------------

    #: Kolom jam yang **wajib** diisi per tipe.
    REQUIRED_TIMES = {
        AttendancePermissionType.LATE_ARRIVAL: ("end_time",),
        AttendancePermissionType.EARLY_LEAVE: ("start_time",),
        AttendancePermissionType.TEMPORARY_OUT: ("start_time", "end_time"),
        AttendancePermissionType.FULL_DAY: (),
    }

    #: Kolom jam yang harus **kosong** per tipe. Diturunkan, bukan
    #: didaftar terpisah: dua daftar yang harus konsisten selalu
    #: berakhir tidak konsisten.
    @classmethod
    def forbidden_times(cls, permission_type) -> tuple[str, ...]:
        required = cls.REQUIRED_TIMES.get(permission_type, ())

        return tuple(
            field
            for field in ("start_time", "end_time")
            if field not in required
        )

    @property
    def is_editable(self) -> bool:
        """
        Hanya draft yang boleh disunting.

        Yang sudah diajukan menunggu tanda tangan atas isi yang
        diajukan; mengubahnya di tengah jalan membuat approver
        menyetujui sesuatu yang berbeda dari yang dibacanya.
        """
        return self.status == AttendancePermissionStatus.DRAFT

    @property
    def is_effective(self) -> bool:
        return self.status in PERMISSION_EFFECTIVE_STATUSES

    @property
    def is_pending(self) -> bool:
        return self.status in PERMISSION_PENDING_STATUSES

    @property
    def duration_minutes(self) -> int:
        """
        Lama izin dalam menit, untuk tipe yang punya jendela tertutup.

        Hanya `TEMPORARY_OUT` yang punya jawaban di level model —
        dua tipe lain jendelanya baru terbentuk setelah dipertemukan
        dengan jam shift pegawainya, dan itu urusan resolver yang punya
        akses ke jadwal. `FULL_DAY` sengaja **tidak** dikarang jadi
        480 menit: berapa panjang sehari adalah properti shift-nya.
        """
        if self.permission_type != AttendancePermissionType.TEMPORARY_OUT:
            return 0

        if not self.start_time or not self.end_time:
            return 0

        base = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)

        # Jendela yang berakhir sebelum ia dimulai berarti melewati
        # tengah malam — shift malam, dan itu keadaan yang lazim di
        # site. Lihat `shift_span()` yang memakai aturan yang sama.
        if end <= base:
            end += timedelta(days=1)

        return int((end - base).total_seconds() // 60)

    def clean(self):
        super().clean()

        errors = {}

        permission_type = self.permission_type

        if permission_type:
            for name in self.REQUIRED_TIMES.get(permission_type, ()):
                if getattr(self, name) is None:
                    errors[name] = (
                        "Wajib diisi untuk izin "
                        f"{self.get_permission_type_display()}."
                    )

            # Kolom yang tidak dipakai tipenya **dikosongkan**, bukan
            # ditolak: form mengirim seluruh isinya apa adanya, dan
            # mengganti tipe izin di form yang sama akan meninggalkan
            # jam lama menempel. Menolaknya berarti pengguna harus
            # mengosongkan field yang sudah disembunyikan form.
            for name in self.forbidden_times(permission_type):
                setattr(self, name, None)

        if (
            permission_type == AttendancePermissionType.TEMPORARY_OUT
            and self.start_time
            and self.end_time
            and self.start_time == self.end_time
        ):
            errors["end_time"] = (
                "Jam kembali tidak boleh sama dengan jam keluar."
            )

        if not (self.reason or "").strip():
            errors["reason"] = "Alasan izin wajib diisi."

        if (
            self.allow_outside_shift
            and not (self.outside_shift_reason or "").strip()
        ):
            errors["outside_shift_reason"] = (
                "Alasan override wajib diisi."
            )

        if errors:
            raise ValidationError(errors)
