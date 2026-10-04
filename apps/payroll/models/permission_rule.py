"""
Adapter Payroll → Attendance Permission: izin jenis mana yang dibayar.

Pola yang sama persis dengan `PayrollLeaveRule` di sebelah, dan dengan
alasan yang sama: `AttendancePermission` di modul HR tidak menyimpan
penanda dibayar/tidak, dan menambahkannya di sana berarti mengubah modul
sumber hanya untuk kepentingan payroll.

**Bawaan saat tabelnya kosong: `INFORMATION_ONLY`.**

Itu keputusan, bukan kelalaian. Yang paling menggoda adalah membuat
"disetujui = dibayar", dan itu justru yang dilarang spesifikasinya —
izin yang disetujui atasan menyatakan bahwa ketidakhadirannya **sah**,
bukan bahwa perusahaan membayarnya. Dua pertanyaan berbeda, dan yang
kedua kebijakan penggajian.

Bawaan `INFORMATION_ONLY` juga yang menjaga payroll yang sudah berjalan
tidak bergeser angkanya hanya karena tabel baru lahir: sebelum ada baris
di sini, potongan alpa dan potongan telat tetap persis seperti sebelum
modul izin ada. Yang bertambah cuma angka di `PeriodFacts` — fakta yang
bisa dibaca laporan tanpa mengubah satu rupiah pun.

Cakupan berjenjang lewat `specificity`, pola yang sama dengan
`AttendancePolicy`, `LeavePolicy`, `RosterPolicy`, dan
`WorkflowDefinition`: kosong berarti **berlaku untuk semua**, bukan
"tidak berlaku".
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class PermissionPayTreatment(models.TextChoices):
    """
    Tiga perlakuan, dan ketiganya benar-benar berbeda:

    * `PAID`             — waktunya dibayar; tidak ikut dipotong
    * `UNPAID`           — waktunya tidak dibayar; ikut dipotong
    * `INFORMATION_ONLY` — payroll tidak menyentuhnya sama sekali;
      angkanya tetap terbaca sebagai fakta

    Yang ketiga bukan sinonim `UNPAID`. `UNPAID` adalah keputusan
    memotong; `INFORMATION_ONLY` adalah keputusan **belum memutuskan**,
    dan perlakuannya sama dengan sebelum izinnya ada. Menyatukan
    keduanya membuat perusahaan yang belum menetapkan kebijakan tidak
    bisa dibedakan dari yang menetapkan potong.
    """

    PAID = "paid", "Paid"
    UNPAID = "unpaid", "Unpaid"
    INFORMATION_ONLY = "information_only", "Information Only"


class PayrollPermissionRule(BaseModel):
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payroll_permission_rules",
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak "
            "punya aturannya sendiri."
        ),
    )

    payroll_policy = models.ForeignKey(
        "payroll.PayrollPolicy",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="permission_rules",
        help_text=(
            "Dikosongkan = berlaku untuk semua kebijakan payroll. "
            "Diisi untuk membedakan pegawai bulanan dari harian, atau "
            "golongan yang aturannya memang berbeda."
        ),
    )

    permission_type = models.CharField(
        max_length=20,
        help_text=(
            "Nilai `AttendancePermissionType` di modul HR. Disimpan "
            "sebagai teks, bukan FK: jenis izin menentukan cara hitung "
            "dan tidak boleh dikarang lewat layar master."
        ),
    )

    treatment = models.CharField(
        max_length=20,
        choices=PermissionPayTreatment.choices,
        default=PermissionPayTreatment.INFORMATION_ONLY,
    )

    # ------------------------------------------------------------------
    # Ambang "terlalu lama"
    # ------------------------------------------------------------------
    #
    # "Izin keluar > 2 jam tidak dibayar" adalah kebijakan yang lazim,
    # dan tanpa kolomnya ia hanya bisa ditulis sebagai dua baris aturan
    # yang saling bertentangan. Nol = mati, dan itu bawaannya.
    #
    # Yang dipotong **hanya kelebihannya**, bukan seluruh durasinya:
    # memotong dua jam pertama juga membuat ambangnya jadi hukuman,
    # bukan batas — dan orang yang izin 2 jam 1 menit dipotong sama
    # dengan yang izin sehari.
    unpaid_over_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Izin lebih lama dari sekian menit: kelebihannya dihitung "
            "tidak dibayar. Dikosongkan (0) = tidak dipakai."
        ),
    )

    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "payroll_permission_rule"

        ordering = ["company__code", "permission_type"]

        verbose_name = "Payroll Permission Rule"
        verbose_name_plural = "Payroll Permission Rules"

        constraints = [
            models.UniqueConstraint(
                fields=["company", "payroll_policy", "permission_type"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_permission_rule",
            ),
        ]

        indexes = [
            models.Index(
                fields=["permission_type"],
                name="idx_payroll_perm_rule_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.permission_type} - {self.treatment}"

    @property
    def specificity(self) -> int:
        return (
            (2 if self.payroll_policy_id else 0)
            + (1 if self.company_id else 0)
        )

    def clean(self):
        super().clean()

        errors = {}

        from apps.hr.models.attendance.permission import (
            AttendancePermissionType,
        )

        valid = {choice.value for choice in AttendancePermissionType}

        if self.permission_type and self.permission_type not in valid:
            errors["permission_type"] = (
                "Jenis izin tidak dikenal. Pilihannya: "
                + ", ".join(sorted(valid))
                + "."
            )

        # Ambang yang menyala pada aturan yang perlakuannya sudah
        # `UNPAID` tidak melakukan apa pun — seluruh durasinya memang
        # sudah tidak dibayar. Ditolak supaya niatnya tidak terbaca
        # keliru saat orang lain membacanya setahun kemudian.
        if (
            self.unpaid_over_minutes
            and self.treatment == PermissionPayTreatment.UNPAID
        ):
            errors["unpaid_over_minutes"] = (
                "Aturan ini sudah tidak dibayar seluruhnya, jadi "
                "ambangnya tidak berpengaruh. Pilih Paid kalau yang "
                "dimaksud 'dibayar sampai sekian menit'."
            )

        if errors:
            raise ValidationError(errors)
