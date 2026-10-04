from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import (
    EARNING_ONLY_BASES,
    PERCENT_BASES,
    RESOLVER_ONLY_BASES,
    PayrollBasis,
)
from .deduction_template import DeductionTemplate


class DeductionTemplateLine(BaseModel):
    """
    Satu komponen potongan di dalam sebuah `DeductionTemplate`.

    Kembaran `AllowanceTemplateLine`, dan sengaja ditulis kembar supaya
    keduanya terbaca sebagai satu aturan. Bedanya dua kolom:
    `reduces_taxable` (iuran yang mengurangi dasar pajak) menggantikan
    `is_taxable`, dan proration bawaannya **mati** — potongan tetap
    seperti cicilan tidak berkurang hanya karena pegawainya masuk
    pertengahan bulan.

    Di sinilah BPJS dan PPh21 dikonfigurasi kalau tenant memakainya:
    BPJS sebagai persentase gaji pokok dengan batas atas, PPh21 lewat
    basis `pph21_progressive` yang membaca `TaxStatus.non_taxable_income`
    dan `PayrollTaxBracket`.
    """

    template = models.ForeignKey(
        DeductionTemplate,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)

    sequence = models.PositiveIntegerField(default=1)

    basis = models.CharField(
        max_length=30,
        choices=PayrollBasis.choices,
        default=PayrollBasis.FIXED,
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
    )

    rate = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        default=0,
    )

    # Batas dasar perhitungan, bukan batas hasilnya — inilah bentuk
    # plafon BPJS ("1% dari gaji, maksimal dari Rp 12.000.000").
    minimum_base = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    maximum_base = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    minimum_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    maximum_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    reduces_taxable = models.BooleanField(default=False)

    # Iuran yang **dibayar perusahaan**, bukan dipotong dari pegawai.
    # Dikonfigurasi di sini karena di sinilah BPJS hidup — porsi
    # perusahaan dan porsi pegawai satu paket, dan memisahkan tempat
    # konfigurasinya berarti dua layar yang harus tetap sepakat.
    # Angkanya lahir sebagai komponen `EMPLOYER_CONTRIBUTION`, jadi ia
    # tidak pernah ikut `total_deduction` maupun `net_pay`.
    is_employer_cost = models.BooleanField(default=False)

    is_prorated = models.BooleanField(default=False)

    description = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_deduction_template_line"
        ordering = ["template__code", "sequence", "code"]
        verbose_name = "Deduction Component"
        verbose_name_plural = "Deduction Components"

        constraints = [
            models.UniqueConstraint(
                fields=["template", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_deduction_line_code",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.basis in RESOLVER_ONLY_BASES:
            # Basis ini dasarnya dititipkan lapisan kebijakan saat
            # payroll dihitung. Baris master tidak pernah menerima
            # titipan itu, jadi hasilnya selalu nol — dan nol yang
            # lahir dari konfigurasi mustahil terbaca seperti nol
            # yang memang benar.
            errors["basis"] = (
                "Basis ini hanya dipakai aturan yang diresolusi "
                "sistem (mis. BPJS), bukan komponen master."
            )

        if self.basis in EARNING_ONLY_BASES:
            errors["basis"] = (
                "Basis ini hanya berlaku untuk komponen earning."
            )

        if self.basis in PERCENT_BASES and not self.rate:
            errors["rate"] = (
                "Basis persentase membutuhkan Rate yang tidak nol."
            )

        # PPh21 tidak memakai `amount` maupun `rate` — angkanya datang
        # dari bracket dan PTKP. Karena itu ia dikecualikan dari syarat
        # "harus ada nilai" yang berlaku untuk basis lain.
        needs_amount = (
            self.basis not in PERCENT_BASES
            and self.basis != PayrollBasis.PPH21_PROGRESSIVE
        )

        if needs_amount and not self.amount:
            errors["amount"] = (
                "Basis ini membutuhkan Amount yang tidak nol."
            )

        if self.is_employer_cost:
            # Ditolak, bukan diabaikan diam-diam. `reduces_taxable`
            # mengurangi dasar pajak **pegawai**; iuran yang tidak
            # pernah menyentuh gaji pegawai tidak punya urusan dengan
            # dasar pajaknya. Dibiarkan menyala, kolomnya terbaca
            # sebagai kebijakan yang sudah berlaku padahal mesin
            # hitung mengabaikannya.
            if self.reduces_taxable:
                errors["reduces_taxable"] = (
                    "Beban perusahaan tidak mengurangi dasar pajak "
                    "pegawai. Matikan salah satu."
                )

            if self.basis == PayrollBasis.PPH21_PROGRESSIVE:
                errors["basis"] = (
                    "PPh21 adalah pajak pegawai, bukan beban "
                    "perusahaan."
                )

        for low, high, key in (
            (self.minimum_base, self.maximum_base, "maximum_base"),
            (self.minimum_amount, self.maximum_amount, "maximum_amount"),
        ):
            if low is not None and high is not None and high < low:
                errors[key] = (
                    "Nilai maksimum tidak boleh lebih kecil dari "
                    "nilai minimum."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.template_id} - {self.code} - {self.name}"
