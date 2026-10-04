from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .choices import (
    AttendanceApprovalStatus,
    AttendanceSource,
    AttendanceStatus,
)

class EmployeeAttendance(models.Model):
    """
    Rekap presensi harian karyawan.

    Satu employee hanya memiliki satu attendance per work_date.
    Record ini merupakan hasil olahan dari AttendanceLog, import,
    device, mobile, atau input manual.
    """

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="attendances",
    )

    # Snapshot organisasi saat transaksi dibuat.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="employee_attendances",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        related_name="employee_attendances",
        null=True,
        blank=True,
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="employee_attendances",
        null=True,
        blank=True,
    )

    work_date = models.DateField(
        db_index=True,
    )

    shift = models.ForeignKey(
        "administration.Shift",
        on_delete=models.SET_NULL,
        related_name="employee_attendances",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
        db_index=True,
    )

    source = models.CharField(
        max_length=20,
        choices=AttendanceSource.choices,
        default=AttendanceSource.MANUAL,
        db_index=True,
    )

    approval_status = models.CharField(
        max_length=20,
        choices=AttendanceApprovalStatus.choices,
        default=AttendanceApprovalStatus.DRAFT,
        db_index=True,
    )

    # Jadwal/schedule snapshot.
    scheduled_check_in = models.DateTimeField(null=True,blank=True,)
    scheduled_check_out = models.DateTimeField(null=True,blank=True)

    # Hasil aktual.
    check_in = models.DateTimeField(null=True,blank=True,db_index=True,)
    check_out = models.DateTimeField(null=True,blank=True,db_index=True,)

    first_check_in = models.DateTimeField(null=True,blank=True)

    last_check_out = models.DateTimeField(null=True,blank=True)

    worked_minutes = models.PositiveIntegerField(default=0)

    break_minutes = models.PositiveIntegerField(default=0)

    late_minutes = models.PositiveIntegerField(default=0,)

    early_leave_minutes = models.PositiveIntegerField(default=0)

    overtime_minutes = models.PositiveIntegerField(default=0,)

    # ------------------------------------------------------------------
    # Klasifikasi pengecualian: dengan izin atau tanpa izin
    #
    # Empat kolom di bawah **tidak menggantikan** angka di atasnya.
    # `late_minutes` tetap menyimpan keterlambatan menurut mesin dan
    # tetap ditimpa tiap perhitungan ulang — itu faktanya, dan izin
    # tidak boleh menghapusnya. Yang ditulis di sini cuma **berapa
    # bagiannya yang dimaafkan sebuah dokumen izin**.
    #
    # Konsekuensi yang diinginkan: "terlambat 2 jam karena izin" dan
    # "terlambat 2 jam tanpa izin" tetap dua baris yang angkanya sama
    # dan perlakuannya berbeda — dan payroll bisa membedakannya tanpa
    # membaca ulang dokumen izinnya satu per satu.
    #
    # Diisi `AttendancePermissionResolver`, bukan `AttendancePolicy
    # Resolver`: yang satu membaca aturan perusahaan, yang satu lagi
    # membaca dokumen yang disetujui orang. Menyatukannya membuat
    # perhitungan menit yang murni fungsi jadi butuh query.
    # ------------------------------------------------------------------

    excused_late_minutes = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Bagian dari `late_minutes` yang tertutup izin yang "
            "disetujui. Sisanya keterlambatan tanpa izin."
        ),
    )

    excused_early_leave_minutes = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Bagian dari `early_leave_minutes` yang tertutup izin yang "
            "disetujui."
        ),
    )

    # Menit izin yang **tidak** tampak sebagai telat atau pulang cepat:
    # izin keluar sementara di tengah jam kerja. Dipisah dari kedua
    # kolom di atas karena payroll memperlakukannya berbeda — yang satu
    # potongan yang dimaafkan, yang satu jam kerja yang memang tidak
    # dijalani.
    permission_minutes = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Menit izin keluar sementara yang disetujui pada hari ini."
        ),
    )

    is_excused_absence = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Tidak masuk dengan izin yang disetujui — bukan mangkir. "
            "Perlakuan payroll-nya tetap mengikuti Payroll Permission "
            "Rule, bukan kolom ini."
        ),
    )

    # Penanda untuk layar, bukan untuk perhitungan.
    #
    # `pending` yang tidak punya kolomnya sendiri hanya bisa ditemukan
    # dengan membuka dokumen izin tiap baris — dan itu persis pekerjaan
    # yang membuat daftar pengecualian tidak pernah dibaca siapa pun.
    permission_state = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        choices=[
            ("pending", "Izin menunggu persetujuan"),
            ("excused", "Tertutup izin"),
            ("partial", "Sebagian tertutup izin"),
            ("unauthorized", "Tanpa izin"),
        ],
        help_text=(
            "Kosong = tidak ada pengecualian yang perlu dijelaskan."
        ),
    )

    # ------------------------------------------------------------------
    # Penanda "seharusnya mengambil cuti"
    #
    # Dihitung `AttendancePolicyResolver` saat keterlambatan atau pulang
    # cepatnya melewati ambang di `AttendancePolicy`.
    #
    # **Penanda, bukan eksekusi.** Yang memotong saldo tetap dokumen
    # cuti yang diajukan dan disetujui — di seluruh sistem ini saldo
    # tidak pernah berkurang tanpa persetujuan, dan kasus yang memang
    # ada alasannya (ban bocor, kapal digeser) harus bisa dianulir tanpa
    # menghapus catatan presensinya. Menerbitkan cuti dari sini juga
    # berarti pegawainya baru tahu saldonya berkurang setelah kejadian.
    # ------------------------------------------------------------------

    leave_required_days = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0,
        help_text=(
            "Hari cuti yang seharusnya diambil untuk hari ini menurut "
            "Attendance Policy. Nol = tidak ada."
        ),
    )

    leave_required_reason = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=[
            ("late", "Terlambat"),
            ("early_leave", "Pulang cepat"),
            ("both", "Terlambat & pulang cepat"),
        ],
        help_text=(
            "Sebabnya, supaya baris yang ditandai bisa dijelaskan tanpa "
            "membandingkan jam tap dengan jadwalnya satu per satu."
        ),
    )

    # ------------------------------------------------------------------
    # Keputusan atasan
    # ------------------------------------------------------------------
    #
    # Ketiga kolom di bawah **tidak boleh disentuh `compute()`**.
    # `leave_required_days` tetap menyimpan angka **menurut aturan** dan
    # tetap ditimpa tiap perhitungan ulang — itu faktanya, dan faktanya
    # tidak boleh hilang. Kalau keputusan orang ditulis ke kolom yang
    # sama, "menurut aturan seharusnya berapa" lenyap, dan **pembebasan
    # tidak bisa dibedakan dari aturan yang memang tidak menyala**.
    #
    # Konsekuensi yang diinginkan: `recalculate_attendance` aman
    # dijalankan kapan saja tanpa menghapus keputusan orang. Pelajaran
    # yang sama dengan `LeaveBalance.adjustment` dan
    # `RotationTravel.is_manual_override`.

    leave_required_override = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Angka yang ditetapkan atasan/HR, menggantikan hitungan "
            "aturan. Dikosongkan = ikut aturan."
        ),
    )

    leave_required_waived = models.BooleanField(
        default=False,
        help_text=(
            "Dibebaskan — tidak perlu mengajukan cuti untuk hari ini."
        ),
    )

    leave_required_waiver_reason = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Wajib diisi saat membebaskan. Pembebasan tanpa alasan "
            "tertulis membuat aturan ini kehilangan wibawanya dalam "
            "tiga bulan."
        ),
    )

    review_decision = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=[
            ("valid", "Pengecualian sah"),
            ("require_leave", "Harus mengajukan cuti"),
        ],
        help_text="Kosong = belum ditinjau atasan.",
    )

    review_notes = models.TextField(
        blank=True,
        default="",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # Dokumen cuti yang lahir dari baris ini.
    #
    # FK, bukan penanda boolean: tanpa tautannya, "sudah diselesaikan"
    # tidak bisa dibedakan dari "sudah diselesaikan lalu cutinya
    # ditolak", dan tidak ada jalan dari baris presensi ke dokumen yang
    # menyelesaikannya. `SET_NULL` karena menghapus catatan cuti tidak
    # boleh menghapus catatan presensinya.
    leave = models.ForeignKey(
        "hr.EmployeeLeave",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attendance_obligations",
    )

    # Business Trip yang mengizinkan hari ini (BT-3). Konteks dan jejak,
    # bukan kehadiran: baris BUSINESS_TRIP tulisan penutup hari menunjuk
    # perjalanannya, dan baris yang kemudian mendapat tap fisik tetap
    # menyimpannya sebagai konteks. `SET_NULL` — menghapus dokumen
    # perjalanan tidak boleh menghapus catatan presensinya.
    business_trip = models.ForeignKey(
        "hr.BusinessTrip",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attendance_days",
    )

    # Data lokasi untuk mobile/web attendance.
    check_in_latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )

    check_in_longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )

    check_out_latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )

    check_out_longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )

    check_in_address = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    check_out_address = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    is_geofence_valid = models.BooleanField(default=True)

    # Identitas sumber eksternal.
    external_id = models.CharField(
        max_length=150,
        blank=True,
        default="",
        db_index=True,
    )

    device_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )

    import_batch_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )

    is_manual_adjustment = models.BooleanField(
        default=False,
    )

    adjustment_reason = models.TextField(
        blank=True,
        default="",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_employee_attendances",
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_employee_attendances",
        null=True,
        blank=True,
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="updated_employee_attendances",
        null=True,
        blank=True,
    )

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="deleted_employee_attendances",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
    )

    class Meta:
        db_table = "hr_employee_attendance"

        ordering = [
            "-work_date",
            "employee_id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "employee",
                    "work_date",
                ],
                condition=Q(is_deleted=False),
                name=(
                    "uq_hr_attendance_employee_"
                    "work_date_active"
                ),
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "company",
                    "work_date",
                ],
                name="idx_hr_att_company_date",
            ),
            models.Index(
                fields=[
                    "location",
                    "work_date",
                ],
                name="idx_hr_att_location_date",
            ),
            models.Index(
                fields=[
                    "employee",
                    "work_date",
                    "status",
                ],
                name="idx_hr_att_emp_date_status",
            ),
            models.Index(
                fields=[
                    "source",
                    "external_id",
                ],
                name="idx_hr_att_source_external",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.employee} - "
            f"{self.work_date} - "
            f"{self.get_status_display()}"
        )

    def clean(self):
        errors = {}

        if (
            self.check_in
            and self.check_out
            and self.check_out < self.check_in
        ):
            errors["check_out"] = (
                "Check Out cannot be earlier "
                "than Check In."
            )

        if (
            self.scheduled_check_in
            and self.scheduled_check_out
            and self.scheduled_check_out
            < self.scheduled_check_in
        ):
            errors["scheduled_check_out"] = (
                "Scheduled Check Out cannot be "
                "earlier than Scheduled Check In."
            )

        if (
            self.status == AttendanceStatus.ABSENT
            and (
                self.check_in
                or self.check_out
            )
        ):
            errors["status"] = (
                "Absent attendance cannot contain "
                "Check In or Check Out."
            )

        if (
            self.leave_required_waived
            and not (self.leave_required_waiver_reason or "").strip()
        ):
            errors["leave_required_waiver_reason"] = (
                "Alasan pembebasan wajib diisi."
            )

        if (
            self.leave_required_override is not None
            and self.leave_required_override < 0
        ):
            errors["leave_required_override"] = (
                "Tidak boleh negatif."
            )

        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # Kewajiban cuti
    # ------------------------------------------------------------------

    @property
    def leave_required_effective(self):
        """
        Angka yang benar-benar berlaku untuk hari ini.

        Urutannya: pembebasan menang atas apa pun, lalu angka yang
        ditetapkan orang, lalu hitungan aturan. `leave_required_days`
        tetap utuh di belakang ketiganya.
        """
        from decimal import Decimal

        if self.leave_required_waived:
            return Decimal("0.00")

        if self.leave_required_override is not None:
            return self.leave_required_override

        return self.leave_required_days or Decimal("0.00")

    @property
    def leave_obligation_status(self) -> str:
        """
        Keadaan kewajiban cuti hari ini, **diturunkan** — tidak disimpan.

        Menyimpannya berarti satu lagi kolom yang bisa hanyut dari
        kenyataan: statusnya bergantung pada status dokumen cutinya, dan
        dokumen itu bisa berubah tanpa menyentuh baris presensi.

        * `none`         — tidak ada kewajiban
        * `waived`       — dibebaskan atasan
        * `outstanding`  — ada kewajiban, belum diselesaikan
        * `leave_issued` — dokumen cutinya sudah dibuat, belum disetujui
        * `settled`      — cutinya sudah disetujui/tercatat
        """
        from decimal import Decimal

        if self.leave_required_waived:
            return "waived"

        if (self.leave_required_effective or Decimal("0.00")) <= 0:
            return "none"

        leave = self.leave

        if leave is not None and not leave.is_deleted:
            # Yang sudah memotong saldo berarti selesai. Yang ditolak
            # atau dibatalkan mengembalikan barisnya jadi pekerjaan lagi
            # — itu benar: kewajibannya belum diselesaikan siapa pun.
            if leave.deducts_balance:
                return "settled"

            from apps.hr.models.leave import LeaveStatus

            if leave.status in (
                LeaveStatus.DRAFT,
                LeaveStatus.SUBMITTED,
            ):
                return "leave_issued"

        return "outstanding"

    # ------------------------------------------------------------------
    # Pengecualian tanpa izin
    # ------------------------------------------------------------------
    #
    # **Diturunkan, bukan disimpan.** Angkanya persis selisih dua kolom
    # yang sudah ada, dan kolom ketiga yang harus konsisten dengan
    # keduanya adalah kolom yang cepat atau lambat menyimpang — biasanya
    # setelah satu perhitungan ulang yang lupa menyentuhnya. Yang butuh
    # menyaringnya menyaring lewat `permission_state`, yang memang punya
    # indeksnya sendiri.

    @property
    def unauthorized_late_minutes(self) -> int:
        return max(
            0,
            int(self.late_minutes or 0)
            - int(self.excused_late_minutes or 0),
        )

    @property
    def unauthorized_early_leave_minutes(self) -> int:
        return max(
            0,
            int(self.early_leave_minutes or 0)
            - int(self.excused_early_leave_minutes or 0),
        )

    @property
    def is_unauthorized_absence(self) -> bool:
        """
        Mangkir yang benar-benar tidak dijelaskan siapa pun.

        Baris cuti sudah punya statusnya sendiri dan tidak pernah
        ABSENT, jadi yang perlu dikecualikan di sini cuma izin.
        """
        return (
            self.status == AttendanceStatus.ABSENT
            and not self.is_excused_absence
        )

    @property
    def permission_state_label(self) -> str:
        return {
            "pending": "Menunggu izin",
            "excused": "Ada izin",
            "partial": "Sebagian ada izin",
            "unauthorized": "Tanpa izin",
        }.get(self.permission_state, "")

    @property
    def leave_obligation_label(self) -> str:
        return {
            "none": "Tidak ada",
            "waived": "Dibebaskan",
            "outstanding": "Belum diselesaikan",
            "leave_issued": "Cuti dibuat",
            "settled": "Selesai",
        }.get(self.leave_obligation_status, "")

