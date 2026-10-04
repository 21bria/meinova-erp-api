from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .allowance_template import AllowanceTemplate
from .choices import (
    DEDUCTION_ONLY_BASES,
    PERCENT_BASES,
    RESOLVER_ONLY_BASES,
    PayrollBasis,
)


class AllowanceTemplateLine(BaseModel):
    """
    Satu komponen tunjangan di dalam sebuah `AllowanceTemplate`.

    **Kenapa tabel anak, bukan master komponen baru.**
    `AllowanceTemplate` yang sudah ada memang sebuah *paket*, bukan satu
    komponen — kodenya STANDARD / STAFF / SUPERVISOR, dan
    `PayrollAssignment.allowance_template` menunjuknya sebagai satu
    pilihan per pegawai. Yang tidak dimilikinya cuma **angka**: tanpa
    baris ini tidak ada satu pun nilai yang bisa dihitung, dan payroll
    hanya bisa menghasilkan gaji pokok.

    Master induknya tidak disentuh sama sekali — tidak ada kolom yang
    berubah, tidak ada yang dihapus, dan tenant yang belum mengisi baris
    apa pun tetap berjalan seperti sebelumnya (paket tanpa baris =
    tidak ada tunjangan, bukan error).
    """

    template = models.ForeignKey(
        AllowanceTemplate,
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

    # Nilai satuan untuk basis FIXED dan seluruh basis PER_*.
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
    )

    # Persen untuk basis PERCENT_*. Dipisah dari `amount` supaya angka
    # 5 tidak pernah ambigu antara "Rp 5" dan "5%".
    rate = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        default=0,
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

    is_taxable = models.BooleanField(default=True)

    # Dipotong proporsional untuk pegawai yang baru masuk atau berhenti
    # di tengah periode. Bawaannya menyala — tunjangan bulanan memang
    # mengikuti hari kerja; yang tidak (mis. reimburse tetap) dimatikan
    # per baris.
    is_prorated = models.BooleanField(default=True)

    description = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_allowance_template_line"
        ordering = ["template__code", "sequence", "code"]
        verbose_name = "Allowance Component"
        verbose_name_plural = "Allowance Components"

        constraints = [
            models.UniqueConstraint(
                fields=["template", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_allowance_line_code",
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

        if self.basis in DEDUCTION_ONLY_BASES:
            errors["basis"] = (
                "Basis ini hanya berlaku untuk komponen potongan."
            )

        if self.basis in PERCENT_BASES and not self.rate:
            errors["rate"] = (
                "Basis persentase membutuhkan Rate yang tidak nol."
            )

        if self.basis not in PERCENT_BASES and not self.amount:
            errors["amount"] = (
                "Basis ini membutuhkan Amount yang tidak nol."
            )

        if (
            self.minimum_amount is not None
            and self.maximum_amount is not None
            and self.maximum_amount < self.minimum_amount
        ):
            errors["maximum_amount"] = (
                "Maximum Amount tidak boleh lebih kecil dari "
                "Minimum Amount."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.template_id} - {self.code} - {self.name}"
