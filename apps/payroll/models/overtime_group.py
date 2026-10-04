from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import OvertimeTierBasis


class OvertimeGroup(BaseModel):
    """
    Aturan upah lembur satu kelompok pegawai.

    **Header, bukan satu tarif.** `hourly_multiplier` di bawah adalah
    pengali tunggal yang dipakai sejak sebelum keputusan #4, dan ia
    tetap ada: kelompok yang belum punya baris `OvertimeGroupTier`
    dihitung persis seperti sebelumnya, jadi tidak ada tenant yang
    angkanya bergeser hanya karena tabel tingkat lahir kosong.

    Pegawai memilih kelompok lewat `PayrollAssignment.overtime_group` —
    tidak ada konfigurasi lembur per pegawai.
    """
    code = models.CharField(
        max_length=30,
    )
    name = models.CharField(
        max_length=150,
    )
    description = models.TextField(
        blank=True,
    )

    # Pengali tunggal. **Fallback**, bukan peninggalan: kelompok tanpa
    # baris tingkat memakainya apa adanya, dan itu yang menjaga angka
    # tenant existing tidak bergerak. Begitu ada tingkat yang aktif,
    # tingkatnya yang berlaku dan kolom ini tidak dibaca.
    hourly_multiplier = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
        help_text=(
            "Pengali upah per jam kalau kelompok ini belum punya "
            "tingkat. Diabaikan begitu ada tingkat yang aktif."
        ),
    )

    # Pembagi gaji pokok jadi upah sejam. 173 adalah angka statuter
    # Indonesia (Kepmenaker 102/2004) dan itu yang jadi bawaannya, jadi
    # baris yang sudah ada tidak berubah perilakunya.
    #
    # Ditaruh di master ini, bukan di settings atau di kode mesin
    # hitung: perusahaan yang memakai basis lain (jam kerja per bulan
    # sendiri) mengubahnya dari layar seperti konfigurasi payroll yang
    # lain. Nol/kosong = lembur tidak bisa dihitung, dan itu dilaporkan
    # sebagai temuan pada run, bukan pembagian nol yang meledak.
    hourly_divisor = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=173,
        help_text=(
            "Pembagi gaji pokok untuk mendapatkan upah per jam. "
            "Bawaan 173 (statuter Indonesia)."
        ),
    )
    maximum_hours_per_day = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    maximum_hours_per_month = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Tingkat dihitung per hari lembur atau dari total sebulan.
    # **Sengaja tanpa bawaan.** Keduanya lazim dan menghasilkan angka
    # yang jauh berbeda; memilihkan salah satunya diam-diam berarti
    # mengambil keputusan bisnis atas nama perusahaan. Kosong sah
    # selama kelompok ini belum punya tingkat — begitu punya, validasi
    # run menuntutnya diisi.
    tier_basis = models.CharField(
        max_length=20,
        choices=OvertimeTierBasis.choices,
        blank=True,
        default="",
        help_text=(
            "Wajib diisi kalau kelompok ini memakai tingkat. Per hari: "
            "tiap hari lembur mulai lagi dari tingkat pertama. Total "
            "sebulan: seluruh jam sebulan disusun sekali."
        ),
    )

    is_active = models.BooleanField(
        default=True,
    )

    @property
    def active_tiers(self):
        """
        Tingkat yang berlaku, terurut. Dipakai service dan validasi —
        keduanya harus melihat daftar yang sama.
        """
        return self.tiers.filter(is_deleted=False, is_active=True).order_by(
            "sequence", "hour_from",
        )

    def clean(self):
        super().clean()

        errors = {}

        # Pembagi nol bukan konfigurasi yang "belum diisi" melainkan
        # pembagian nol yang menunggu. Ditolak di layar tempat ia
        # ditulis, bukan sebulan kemudian saat payroll dihitung.
        if self.hourly_divisor is not None and self.hourly_divisor <= 0:
            errors["hourly_divisor"] = (
                "Hourly Divisor harus lebih besar dari nol."
            )

        if self.hourly_multiplier is not None and self.hourly_multiplier <= 0:
            errors["hourly_multiplier"] = (
                "Pengali harus lebih besar dari nol."
            )

        if errors:
            raise ValidationError(errors)

    class Meta:
        db_table = "payroll_overtime_group"
        ordering = ["code"]
        verbose_name = "Overtime Group"
        verbose_name_plural = "Overtime Groups"

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_overtimegroup_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"