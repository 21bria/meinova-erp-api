"""
Aturan kehadiran: berapa menit masih ditoleransi, sejak menit ke berapa
dihitung lembur.

Sebelum ini angkanya tidak ada di mana pun. Yang paling dekat
`WorkScheduleDay.tolerance_in_minutes` — sudah lama tersimpan, bahkan
sudah diseed 15 menit untuk salah satu jadwal, dan **tidak ada satu
baris kode pun yang membacanya**. Tempatnya pun salah untuk kebutuhan
yang sebenarnya: ia menempel pada hari dalam sebuah Work Schedule,
sementara yang berbeda di lapangan adalah **tempatnya** — kantor pusat
memberi kelonggaran macet Jakarta, site tidak, karena orangnya tinggal
di mess seratus meter dari pos.

Kenapa master tersendiri, bukan kolom di Location
-------------------------------------------------
Struktur organisasi sudah final, dan toleransi bukan properti sebuah
tempat — ia kebijakan yang **kebetulan** dibedakan per tempat. Besok
pembedanya bisa golongan pegawai (staf vs harian), dan menambah kolom
lagi ke Location berarti struktur organisasi ikut berubah tiap kali
aturan kehadiran berubah.

Pencocokannya berjenjang lewat skor `specificity`, pola yang sama
dengan `LeavePolicy`, `RosterPolicy`, `EmployeeActionPolicy`, dan
`WorkflowDefinition`: kosong berarti **berlaku untuk semua**, bukan
"tidak berlaku". Itu jebakan yang sudah berkali-kali muncul di master
berjenjang lain di sistem ini, jadi ditulis di help text tiap field.

Yang **tidak** disimpan di sini: jam kerjanya sendiri. Jam masuk dan
jam pulang milik jadwal (`Shift` / `WorkScheduleDay`), dan menyalinnya
ke sini berarti dua sumber untuk angka yang sama — cepat atau lambat
yang satu berubah dan yang lain tidak.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class AttendancePolicy(BaseModel):
    # ------------------------------------------------------------------
    # Untuk siapa
    # ------------------------------------------------------------------

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attendance_policies",
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
        related_name="attendance_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua lokasi. Diisi untuk "
            "membedakan kantor pusat dari site — inilah pembeda yang "
            "paling sering dipakai."
        ),
    )

    employee_group = models.ForeignKey(
        "administration.EmployeeGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attendance_policies",
        help_text="Dikosongkan = berlaku untuk semua golongan.",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Keterlambatan
    # ------------------------------------------------------------------

    late_tolerance_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Datang dalam batas ini masih dihitung hadir tepat waktu. "
            "Jam tap yang sebenarnya tetap tersimpan apa adanya — yang "
            "dipengaruhi hanya status dan menit keterlambatannya."
        ),
    )

    late_counts_from_tolerance = models.BooleanField(
        default=True,
        help_text=(
            "Menyala: menit telat dihitung dari batas toleransi "
            "(toleransi 15, datang 20 → telat 5). Mati: dihitung dari "
            "jam jadwal (→ telat 20), jadi toleransi hanya menentukan "
            "status. Pilih yang sesuai cara payroll memotongnya."
        ),
    )

    # ------------------------------------------------------------------
    # Pulang cepat
    # ------------------------------------------------------------------

    early_leave_tolerance_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Pulang lebih awal dalam batas ini tidak dihitung sebagai "
            "pulang cepat."
        ),
    )

    # ------------------------------------------------------------------
    # Terlambat/pulang cepat yang berat: dianggap mengambil cuti
    #
    # Toleransi menjawab "masih dimaafkan atau tidak". Dua kolom di
    # bawah menjawab pertanyaan yang berbeda: **kapan keterlambatannya
    # berhenti jadi keterlambatan dan berubah jadi setengah hari yang
    # tidak dijalani.** Perusahaan lazim menaruh batasnya di 2 jam.
    #
    # Nol = mati, dan itu bawaannya — tenant yang sudah berjalan tidak
    # tiba-tiba mulai menandai orang.
    # ------------------------------------------------------------------

    late_leave_threshold_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Telat lebih dari sekian menit dianggap mengambil cuti "
            "sebesar 'Leave Deduction'. Dihitung dari jam jadwal, bukan "
            "dari batas toleransi. Dikosongkan (0) = tidak dipakai."
        ),
    )

    early_leave_leave_threshold_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Pulang lebih awal dari sekian menit dianggap mengambil "
            "cuti sebesar 'Leave Deduction'. Dikosongkan (0) = tidak "
            "dipakai."
        ),
    )

    leave_deduction_days = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.5"),
        help_text=(
            "Berapa hari cuti yang harus diambil begitu salah satu "
            "ambang di atas terlampaui. Bawaannya setengah hari."
        ),
    )

    # Jenis cuti yang dipotong. **Wajib begitu salah satu ambang di atas
    # menyala** — "wajib ambil cuti" tanpa menyebut saldo yang mana
    # tidak bisa dieksekusi siapa pun, dan tombol Issue Leave tidak
    # punya isian untuk kolom yang paling menentukan.
    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_policies",
        help_text=(
            "Jenis cuti yang diterbitkan saat kewajiban ini "
            "ditindaklanjuti."
        ),
    )

    # ------------------------------------------------------------------
    # Peninjauan & pemberitahuan
    # ------------------------------------------------------------------
    #
    # Penandanya sendiri tersimpan di kolom yang tidak dibuka siapa pun
    # sampai ada yang kebetulan membuka layar Attendance. Tiga saklar di
    # bawah yang membuatnya sampai ke orangnya.

    require_supervisor_review = models.BooleanField(
        default=True,
        help_text=(
            "Kewajiban cuti harus ditinjau atasan langsung sebelum "
            "ditindaklanjuti. Dimatikan = HR langsung yang memutuskan."
        ),
    )

    notify_employee = models.BooleanField(
        default=True,
        help_text="Beri tahu pegawainya saat pengecualian terdeteksi.",
    )

    notify_supervisor = models.BooleanField(
        default=True,
        help_text=(
            "Beri tahu atasan langsung (Reports To pegawainya). Bukan "
            "field supervisor tersendiri — garis pelaporan yang sudah "
            "ada yang dipakai."
        ),
    )

    notify_hr = models.BooleanField(
        default=False,
        help_text=(
            "Beri tahu HR juga. Dimatikan bawaannya: di tenant besar "
            "ini menghasilkan puluhan surat sehari untuk hal yang sudah "
            "ditangani atasannya."
        ),
    )

    # ------------------------------------------------------------------
    # Lembur
    # ------------------------------------------------------------------

    overtime_threshold_minutes = models.PositiveSmallIntegerField(
        default=30,
        help_text=(
            "Lewat jadwal minimal sekian menit baru dihitung lembur. "
            "Tanpa ambang, kolom lembur terisi satu-dua menit di "
            "hampir setiap baris dan lembur sungguhan tidak bisa "
            "dibedakan dari derau."
        ),
    )

    overtime_rounding_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Pembulatan ke bawah, mis. 30 berarti 95 menit dihitung "
            "90. Dikosongkan (0) = tanpa pembulatan."
        ),
    )

    break_minutes = models.PositiveSmallIntegerField(
        default=60,
        help_text=(
            "Potongan istirahat untuk menghitung jam kerja bersih, "
            "dipakai kalau catatannya tidak membawa angka sendiri."
        ),
    )

    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Attendance Policy"
        verbose_name_plural = "Attendance Policies"
        ordering = ["sort_order", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_attendance_policy_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def specificity(self) -> int:
        """
        Seberapa khusus aturan ini. Makin tinggi makin menang.

        Bobotnya mengikuti `WorkflowDefinition` dan policy lain:
        company mengalahkan lokasi, lokasi mengalahkan golongan.
        Dipakai supaya pilihannya tidak bergantung pada urutan baris di
        database.
        """
        return (
            (4 if self.company_id else 0)
            + (2 if self.location_id else 0)
            + (1 if self.employee_group_id else 0)
        )

    def clean(self):
        super().clean()

        errors = {}

        # Pembulatan yang lebih besar dari ambangnya membuat lembur di
        # antara keduanya hilang tanpa jejak: lewat ambang, tapi
        # dibulatkan ke bawah jadi nol. Kalau memang itu yang
        # diinginkan, ambangnya yang dinaikkan — di situ niatnya
        # terbaca.
        if (
            self.overtime_rounding_minutes
            and self.overtime_threshold_minutes
            and self.overtime_rounding_minutes
            > self.overtime_threshold_minutes
        ):
            errors["overtime_rounding_minutes"] = (
                "Pembulatan tidak boleh melebihi ambang lembur — "
                "lembur di antara keduanya akan dibulatkan jadi nol."
            )

        if self.location_id and not self.company_id:
            errors["company"] = (
                "Lokasi selalu milik sebuah company, jadi sebutkan "
                "company-nya juga."
            )

        # Ambang "dianggap ambil cuti" yang berada **di bawah**
        # toleransinya sendiri tidak bisa dieksekusi: keterlambatan di
        # antara keduanya sekaligus dimaafkan dan memotong setengah
        # hari. Ditolak di sini supaya pertentangannya terbaca di layar
        # tempat angkanya diketik, bukan muncul sebagai potongan cuti
        # yang tidak bisa dijelaskan sebulan kemudian.
        if (
            self.late_leave_threshold_minutes
            and self.late_leave_threshold_minutes
            <= self.late_tolerance_minutes
        ):
            errors["late_leave_threshold_minutes"] = (
                "Ambang cuti harus lebih besar daripada toleransi "
                f"keterlambatan ({self.late_tolerance_minutes} menit)."
            )

        if (
            self.early_leave_leave_threshold_minutes
            and self.early_leave_leave_threshold_minutes
            <= self.early_leave_tolerance_minutes
        ):
            errors["early_leave_leave_threshold_minutes"] = (
                "Ambang cuti harus lebih besar daripada toleransi "
                "pulang cepat "
                f"({self.early_leave_tolerance_minutes} menit)."
            )

        # Ambang menyala tapi potongannya nol berarti aturannya jalan
        # dan tidak menghasilkan apa-apa — penanda yang selalu berbunyi
        # "0 hari" lebih buruk daripada aturan yang memang dimatikan.
        if (
            (
                self.late_leave_threshold_minutes
                or self.early_leave_leave_threshold_minutes
            )
            and not self.leave_deduction_days
        ):
            errors["leave_deduction_days"] = (
                "Isi berapa hari yang dipotong, atau kosongkan "
                "ambangnya kalau aturan ini memang tidak dipakai."
            )

        # Ambang menyala tanpa menyebut jenis cutinya menghasilkan
        # penanda yang tidak bisa ditindaklanjuti: tombol yang
        # menerbitkan dokumen cutinya tidak punya isian untuk kolom yang
        # paling menentukan, dan penolakannya baru muncul saat ada yang
        # menekannya.
        if (
            (
                self.late_leave_threshold_minutes
                or self.early_leave_leave_threshold_minutes
            )
            and not self.leave_type_id
        ):
            errors["leave_type"] = (
                "Sebutkan jenis cuti yang dipotong — 'wajib ambil "
                "cuti' tanpa menyebut saldo yang mana tidak bisa "
                "dieksekusi."
            )

        if errors:
            raise ValidationError(errors)
