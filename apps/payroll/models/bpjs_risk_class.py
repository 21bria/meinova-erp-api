from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class BpjsRiskClass(BaseModel):
    """
    Kelas risiko kerja — identitasnya saja, tanpa satu pun angka.

    Ada karena satu perusahaan bisa punya **beberapa kelas sekaligus**:
    populasi kantor dan populasi lapangan berada di badan hukum yang
    sama tapi tidak menanggung risiko yang sama. Rancangan yang menaruh
    tarif risiko di perusahaan menghasilkan satu angka yang benar dan
    satu angka yang salah, dan yang salah tidak kelihatan salah di layar
    mana pun.

    **Tarifnya tidak di sini.** Sama seperti `BpjsProgram`: yang berubah
    mengikuti regulasi adalah tarifnya, dan yang bisa bertanggal berlaku
    adalah `BpjsRule`. Menyimpan tarif di kelas berarti mengubah tarif
    menulis ulang arti masa lalu.

    Kelas seorang pegawai menempel di `BpjsEnrollment`, bukan di kartu
    pegawai, dan alasannya sama: kepesertaan sudah bertanggal berlaku,
    jadi perpindahan kelas cukup menutup baris lama dan membuka yang
    baru. Menaruhnya di kartu pegawai membuat reklasifikasi hari ini
    menulis ulang JKK tahun lalu.
    """

    code = models.CharField(
        max_length=30,
        help_text="Kode kelas risiko menurut konfigurasi yang berlaku.",
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    sequence = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_bpjs_risk_class"
        ordering = ["sequence", "code"]
        verbose_name = "BPJS Risk Class"
        verbose_name_plural = "BPJS Risk Classes"

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_bpjs_risk_class_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
