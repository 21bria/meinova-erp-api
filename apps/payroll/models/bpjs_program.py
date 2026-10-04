from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class BpjsProgram(BaseModel):
    """
    Identitas satu program BPJS — dan **hanya** identitasnya.

    Ada supaya BPJS berhenti dikenali lewat kode komponen. Sebelum ini
    satu-satunya cara memisahkan BPJS dari potongan lain adalah
    mencocokkan nama: `if "BPJS" in code`. Itu bekerja sampai ada tenant
    yang menamainya "Jamsostek", dan kegagalannya diam — angkanya tetap
    keluar, cuma masuk kotak yang salah. Angka yang lahir dari tebakan
    nama terbaca sebagai angka resmi justru ketika ia keliru.

    Tidak menyimpan satu pun angka. Tarif, plafon, dan komposisi dasar
    tinggal di `BpjsRule` yang bertanggal berlaku; kalau ditaruh di
    sini, mengubah tarif berarti menulis ulang arti masa lalu.
    """

    code = models.CharField(
        max_length=30,
        help_text="Mis. JKN, JHT, JP, JKK, JKM.",
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    sequence = models.PositiveIntegerField(default=1)

    # Program yang tarifnya ditentukan kelas risiko kerja. Saklar ini
    # yang membuat kelas risiko **wajib** — pada aturannya maupun pada
    # kepesertaannya — dan sebaliknya melarangnya pada program yang
    # tidak mengenal kelas. Tanpa saklar, kelas risiko jadi kolom
    # opsional yang boleh kosong, dan JKK tanpa kelas akan diam-diam
    # jatuh ke tarif umum.
    uses_risk_class = models.BooleanField(
        default=False,
        help_text=(
            "Tarif program ini ditentukan kelas risiko kerja. "
            "Kepesertaan dan aturannya wajib menyebut kelasnya."
        ),
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_bpjs_program"
        ordering = ["sequence", "code"]
        verbose_name = "BPJS Program"
        verbose_name_plural = "BPJS Programs"

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_bpjs_program_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
