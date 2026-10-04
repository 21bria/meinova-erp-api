from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .bpjs_program import BpjsProgram


class BpjsEnrollment(BaseModel):
    """
    Kepesertaan seorang pegawai pada satu program, bertanggal berlaku.

    **Tidak ada baris aktif = tidak ikut.** Itu keputusan, bukan
    kelalaian: kepesertaan yang diasumsikan dari ketiadaan data berarti
    setiap pegawai baru otomatis dipotong iuran program yang mungkin
    tidak pernah didaftarkan untuknya. Ketiadaan baris karena itu
    keadaan normal yang sah, dan **tidak** menerbitkan temuan apa pun —
    resolver cuma tidak menghitung program itu untuknya.

    Karena artinya begitu, cutover **wajib** menerbitkan baris untuk
    semua orang yang hari ini memang dipotong; itu tugas
    `bpjs_migrate_templates`, bukan tugas migration.

    **Nomor kepesertaan kosong tidak membatalkan iuran** dan tidak
    memblokir payroll — ia menerbitkan peringatan. Iuran yang hilang
    diam-diam karena satu kolom administratif belum diisi adalah gaji
    yang salah; peringatan yang harus diakui adalah harga yang benar.
    """

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="bpjs_enrollments",
    )

    program = models.ForeignKey(
        BpjsProgram,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )

    participates = models.BooleanField(
        default=True,
        help_text=(
            "Dimatikan = tidak ikut program ini, tanpa menghapus "
            "riwayat kepesertaannya."
        ),
    )

    enrolled_from = models.DateField()
    enrolled_to = models.DateField(
        null=True,
        blank=True,
        help_text="Kosong = masih terdaftar.",
    )

    # Kelas risiko kerja pegawai ini pada program ini. Menempel di
    # kepesertaan, bukan di kartu pegawai, karena kepesertaan **sudah**
    # bertanggal berlaku: perpindahan kelas ditulis sebagai penutupan
    # baris lama dan pembukaan baris baru, jadi JKK tahun lalu tetap
    # diresolusi dengan kelas yang berlaku waktu itu. Di kartu pegawai,
    # reklasifikasi hari ini akan menulis ulang masa lalu.
    risk_class = models.ForeignKey(
        "payroll.BpjsRiskClass",
        on_delete=models.PROTECT,
        related_name="bpjs_enrollments",
        null=True,
        blank=True,
        help_text=(
            "Wajib untuk program yang memakai kelas risiko, dan harus "
            "kosong untuk program yang tidak."
        ),
    )

    membership_number = models.CharField(max_length=50, blank=True)

    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_bpjs_enrollment"
        ordering = ["employee", "program__sequence", "-enrolled_from"]
        verbose_name = "BPJS Enrollment"
        verbose_name_plural = "BPJS Enrollments"

        constraints = [
            models.UniqueConstraint(
                fields=["employee", "program", "enrolled_from"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_bpjs_enrollment",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.enrolled_to and self.enrolled_to < self.enrolled_from:
            errors["enrolled_to"] = (
                "Tanggal berakhir tidak boleh lebih awal dari tanggal "
                "mulai."
            )

        if self.program_id:
            from .bpjs_program import BpjsProgram

            uses_risk_class = (
                BpjsProgram.objects
                .filter(pk=self.program_id)
                .values_list("uses_risk_class", flat=True)
                .first()
            )

            if uses_risk_class and self.risk_class_id is None:
                # Tanpa kelas, resolver tidak akan menemukan aturan
                # yang cocok dan menerbitkan ERROR. Ditolak di sini
                # supaya kegagalannya muncul di layar yang menulisnya,
                # bukan sebulan kemudian di tengah payroll.
                errors["risk_class"] = (
                    "Program ini memakai kelas risiko, jadi "
                    "kepesertaannya wajib menyebut kelas risikonya."
                )

            if not uses_risk_class and self.risk_class_id is not None:
                errors["risk_class"] = (
                    "Program ini tidak memakai kelas risiko. Kosongkan "
                    "kelas risikonya."
                )

        if self.employee_id and self.program_id and not errors:
            overlap = self._overlapping()

            if overlap is not None:
                errors["enrolled_from"] = (
                    "Rentangnya bertindih dengan kepesertaan yang sudah "
                    f"ada ({overlap.enrolled_from} s.d. "
                    f"{overlap.enrolled_to or 'seterusnya'})."
                )

        if errors:
            raise ValidationError(errors)

    def _overlapping(self):
        others = (
            type(self).objects
            .filter(
                employee_id=self.employee_id,
                program_id=self.program_id,
                is_deleted=False,
            )
            .exclude(pk=self.pk)
        )

        for other in others:
            starts_after_other_ends = (
                other.enrolled_to is not None
                and self.enrolled_from > other.enrolled_to
            )

            ends_before_other_starts = (
                self.enrolled_to is not None
                and self.enrolled_to < other.enrolled_from
            )

            if not (starts_after_other_ends or ends_before_other_starts):
                return other

        return None

    def __str__(self) -> str:
        return f"{self.employee_id} - {self.program_id}"
