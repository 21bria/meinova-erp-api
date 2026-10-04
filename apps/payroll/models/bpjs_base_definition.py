from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import BpjsDailyBasicMethod


class BpjsBaseDefinition(BaseModel):
    """
    Komposisi dasar iuran: gaji pokok ditambah komponen earning yang
    **disebut satu per satu**.

    **Kenapa bukan persentase dari gross.** Gross memuat lembur dan
    input variabel, jadi dasarnya berayun tiap bulan mengikuti hal yang
    tidak ada hubungannya dengan upah yang dilaporkan. Di sini lembur
    dan input **tidak bisa masuk sama sekali** — bukan disaring, tapi
    memang tidak pernah termasuk kandidat (lihat `BpjsResolver`).

    **Kenapa versi, dan kenapa tidak bisa disunting.** Begitu sebuah
    komposisi dipakai `BpjsRule` yang tersimpan, mengubah isinya berarti
    menulis ulang arti aturan yang sudah pernah berlaku: payroll bulan
    lalu yang dihitung ulang tiba-tiba memakai dasar yang berbeda tanpa
    satu baris aturan pun berubah, dan tidak ada layar yang bisa
    memperlihatkan penyebabnya. Perubahan karena itu **menerbitkan versi
    baru**, dan aturan lama tetap menunjuk versi lamanya.

    Kekunciannya **tidak** bergantung tanggal. Sempat dirancang mengunci
    saat `effective_from <= hari ini`, dan itu salah: arti masa lalu
    berubah karena waktu berjalan, dan hasil test bergantung kapan ia
    dijalankan. Yang mengunci adalah **adanya rujukan**, bukan
    berlalunya waktu.
    """

    code = models.CharField(
        max_length=30,
        help_text="Mis. UPAH-POKOK-TETAP.",
    )
    version = models.PositiveIntegerField(default=1)

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    include_basic = models.BooleanField(
        default=True,
        help_text=(
            "Gaji pokok ikut jadi dasar iuran. Yang dipakai gaji pokok "
            "sebulan menurut kontrak, bukan yang sudah diprorata."
        ),
    )

    # ------------------------------------------------------------------
    # Pegawai harian
    # ------------------------------------------------------------------

    # Ditaruh **di sini**, bukan di aturan, dan itu yang membuatnya aman
    # terhadap sejarah: definisi ini sudah bervesi dan terkunci begitu
    # dirujuk, jadi mengubah cara dasar harian dibentuk otomatis
    # menerbitkan versi baru dan aturan lama tetap menunjuk versi
    # lamanya. Di aturan, jaminan yang sama cuma jadi kebiasaan.
    daily_basic_method = models.CharField(
        max_length=30,
        choices=BpjsDailyBasicMethod.choices,
        default=BpjsDailyBasicMethod.NONE,
        help_text=(
            "Cara membentuk dasar iuran untuk pegawai berbasis harian. "
            "Hanya dibaca kalau kebijakan pegawainya memang harian."
        ),
    )

    # Tanpa bawaan, dan itu disengaja. Bawaan 21/25/30 apa pun adalah
    # angka regulasi yang menyelinap masuk lewat kode.
    daily_basic_factor = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=(
            "Pengali upah sehari jadi dasar iuran sebulan. Wajib diisi "
            "kalau caranya Upah Harian x Pengali."
        ),
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_bpjs_base_definition"
        ordering = ["code", "-version"]
        verbose_name = "BPJS Base Definition"
        verbose_name_plural = "BPJS Base Definitions"

        constraints = [
            models.UniqueConstraint(
                fields=["code", "version"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_bpjs_base_definition_version",
            ),
        ]

    # ------------------------------------------------------------------
    # Kekunciannya
    # ------------------------------------------------------------------

    @property
    def is_referenced(self) -> bool:
        """
        Sudah ditunjuk `BpjsRule` yang tersimpan?

        Termasuk aturan yang sudah di-soft delete. Aturan yang dihapus
        tetap pernah melahirkan komponen payroll, dan yang dijaga di
        sini arti definisinya — bukan apakah ia masih dipakai hari ini.
        """
        if not self.pk:
            return False

        return self.rules.exists()

    def clean(self):
        super().clean()

        if (
            self.daily_basic_method == BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR
            and not self.daily_basic_factor
        ):
            # Tanpa pengali, caranya tidak bisa dijalankan — dan kalau
            # dibiarkan lolos, ia menghasilkan dasar nol yang terbaca
            # seperti pegawai yang memang tidak diikutkan.
            raise ValidationError(
                {
                    "daily_basic_factor": (
                        "Cara ini memerlukan pengali. Angkanya "
                        "kebijakan yang harus ditulis, bukan sesuatu "
                        "yang boleh ditebak sistem."
                    ),
                },
            )

        if (
            self.daily_basic_method != BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR
            and self.daily_basic_factor is not None
        ):
            raise ValidationError(
                {
                    "daily_basic_factor": (
                        "Pengali hanya dipakai cara Upah Harian x "
                        "Pengali. Kosongkan."
                    ),
                },
            )

        if not self.pk:
            return

        # Perbandingan terhadap baris yang tersimpan, bukan terhadap
        # penanda apa pun: yang dilarang **perubahan isinya**, sementara
        # menyunting keterangan atau menonaktifkannya tetap boleh.
        stored = (
            type(self).objects
            .filter(pk=self.pk)
            .values(
                "include_basic",
                "daily_basic_method",
                "daily_basic_factor",
            )
            .first()
        )

        if not stored:
            return

        # Ketiganya sama-sama **isi komposisi**: masing-masing mengubah
        # angka dasar yang dihasilkan definisi ini. Menjaga
        # `include_basic` saja berarti arti historis tetap bisa ditulis
        # ulang lewat pengali harian.
        for field in ("include_basic", "daily_basic_method", "daily_basic_factor"):
            if stored[field] != getattr(self, field) and self.is_referenced:
                raise ValidationError(
                    {
                        field: (
                            "Komposisi ini sudah dipakai aturan BPJS dan "
                            "tidak bisa diubah. Terbitkan versi baru, lalu "
                            "buat aturan berlaku yang menunjuk versi itu."
                        ),
                    },
                )

    def __str__(self) -> str:
        return f"{self.code} v{self.version} - {self.name}"


class BpjsBaseComponent(BaseModel):
    """
    Satu komponen earning yang ikut membentuk dasar iuran.

    Ditunjuk lewat **kode komponen tunjangan**, dan itu pilihan sadar
    beserta harganya. Baris tunjangan hidup per template, jadi tunjangan
    yang sama secara konsep adalah baris berbeda di tiap template;
    menunjuk baris lewat FK berarti satu definisi dasar hanya berlaku
    untuk satu template. Kodenya yang dipakai bersama.

    Bedanya dengan tebakan nama yang dibuang `BpjsProgram`: kode di sini
    **ditulis orang yang mengonfigurasi** sebagai identitas komponen,
    bukan dicocokkan mesin dari kata yang kebetulan ada. Risikonya tetap
    ada — kode yang diganti nama diam-diam mengecilkan dasar iuran — dan
    itu yang dijaga temuan `bpjs_base_component_unknown`.
    """

    definition = models.ForeignKey(
        BpjsBaseDefinition,
        on_delete=models.CASCADE,
        related_name="components",
    )

    allowance_code = models.CharField(
        max_length=30,
        help_text=(
            "Kode komponen tunjangan yang ikut jadi dasar iuran, "
            "persis seperti tertulis di Allowance Component."
        ),
    )

    sequence = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "payroll_bpjs_base_component"
        ordering = ["definition", "sequence", "allowance_code"]
        verbose_name = "BPJS Base Component"
        verbose_name_plural = "BPJS Base Components"

        constraints = [
            models.UniqueConstraint(
                fields=["definition", "allowance_code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_bpjs_base_component",
            ),
        ]

    def clean(self):
        super().clean()

        if self.definition_id and self.definition.is_referenced:
            raise ValidationError(
                "Komposisi ini sudah dipakai aturan BPJS dan tidak bisa "
                "diubah. Terbitkan versi baru dari definisinya.",
            )

    def __str__(self) -> str:
        return f"{self.definition_id} - {self.allowance_code}"
