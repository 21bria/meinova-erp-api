from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .bpjs_base_definition import BpjsBaseDefinition
from .bpjs_program import BpjsProgram


class BpjsRule(BaseModel):
    """
    Tarif satu program BPJS yang berlaku pada satu rentang tanggal,
    untuk satu perusahaan atau untuk seluruh tenant.

    **Dua sisi dalam satu baris, dan itu inti keputusannya.** Sebelum
    ini porsi pegawai dan porsi perusahaan adalah dua
    `DeductionTemplateLine` yang tidak saling mengenal: mengubah yang
    satu meninggalkan yang lain, dan tidak ada apa pun yang berbunyi.
    Satu baris membuat keduanya mustahil berpisah.

    **Masing-masing sisi boleh kosong.** Program bisa bersisi pegawai
    saja, perusahaan saja, atau keduanya — JKK/JKM lazimnya ditanggung
    perusahaan sepenuhnya. Sisi yang kosong **tidak menerbitkan baris
    apa pun**; baris bertarif nol yang dikarang muncul di slip sebagai
    potongan yang tidak pernah ada.

    **Tidak pernah disunting untuk mengubah tarif.** Tarif baru = baris
    baru dengan `effective_from` berikutnya, dan baris lama ditutup
    `effective_to`. Itu yang membuat run periode lama yang dihitung
    ulang tetap memakai tarif periode itu.

    **Override perusahaan mengganti aturan utuh**, bukan menimpa kolom
    per kolom. Aturan gabungan membuat "tarif mana yang berlaku" tidak
    punya jawaban tunggal yang bisa dibaca di satu layar.
    """

    program = models.ForeignKey(
        BpjsProgram,
        on_delete=models.PROTECT,
        related_name="rules",
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        related_name="bpjs_rules",
        null=True,
        blank=True,
        help_text=(
            "Kosong = aturan bawaan seluruh tenant. Diisi = aturan "
            "perusahaan itu, yang menggantikan aturan bawaan secara "
            "utuh."
        ),
    )

    base_definition = models.ForeignKey(
        BpjsBaseDefinition,
        on_delete=models.PROTECT,
        related_name="rules",
    )

    # Kelas risiko kerja. Wajib pada program ber-`uses_risk_class`,
    # dilarang pada yang lain — lihat `clean()`. Nullable di database
    # karena mayoritas program memang tidak mengenal kelas, bukan
    # karena kelasnya boleh dilupakan pada yang mengenalnya.
    risk_class = models.ForeignKey(
        "payroll.BpjsRiskClass",
        on_delete=models.PROTECT,
        related_name="bpjs_rules",
        null=True,
        blank=True,
        help_text=(
            "Wajib untuk program yang memakai kelas risiko, dan harus "
            "kosong untuk program yang tidak."
        ),
    )

    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text="Kosong = masih berlaku.",
    )

    # ------------------------------------------------------------------
    # Sisi pegawai
    # ------------------------------------------------------------------

    employee_rate = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Kosong = program ini tidak dipotong dari pegawai.",
    )

    employee_minimum_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    employee_maximum_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )

    # Dibawa apa adanya dari perilaku hari ini. **Bukan** keputusan
    # pajak baru: metode PPh21 masih PROVISIONAL dan dibekukan (#4).
    reduces_taxable = models.BooleanField(
        default=False,
        help_text="Iuran pegawai ini mengurangi dasar perhitungan PPh21.",
    )

    # ------------------------------------------------------------------
    # Sisi perusahaan
    # ------------------------------------------------------------------

    employer_rate = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Kosong = program ini tidak ditanggung perusahaan.",
    )

    employer_minimum_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    employer_maximum_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )

    # ------------------------------------------------------------------
    # Batas dasar — berlaku untuk kedua sisi
    # ------------------------------------------------------------------

    # Plafon BPJS bentuknya batas **dasar**, bukan batas hasil: "1% dari
    # gaji, maksimal dari Rp 12.000.000". Batas hasil tetap disediakan
    # terpisah untuk aturan yang memang menyebut nilai iurannya.
    base_minimum = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    base_maximum = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_bpjs_rule"
        ordering = ["program__sequence", "program__code", "-effective_from"]
        verbose_name = "BPJS Rule"
        verbose_name_plural = "BPJS Rules"

        constraints = [
            # Kunci alami satu aturan. Tumpang tindih sesungguhnya
            # diperiksa `clean()` — rentang yang berpotongan tidak bisa
            # dinyatakan constraint unik biasa, apalagi bersama
            # `nulls_distinct` untuk company yang boleh kosong.
            models.UniqueConstraint(
                fields=["program", "company", "risk_class", "effective_from"],
                condition=Q(is_deleted=False),
                nulls_distinct=False,
                name="uniq_active_payroll_bpjs_rule_effective",
            ),
        ]

    # ------------------------------------------------------------------

    @property
    def has_employee_side(self) -> bool:
        return self.employee_rate is not None

    @property
    def has_employer_side(self) -> bool:
        return self.employer_rate is not None

    @property
    def scope_label(self) -> str:
        return self.company.code if self.company_id else "All Companies"

    def clean(self):
        super().clean()

        errors = {}

        if self.effective_to and self.effective_to < self.effective_from:
            errors["effective_to"] = (
                "Tanggal berakhir tidak boleh lebih awal dari tanggal "
                "berlaku."
            )

        if not self.has_employee_side and not self.has_employer_side:
            # Aturan tanpa satu sisi pun tidak menghasilkan apa-apa, dan
            # yang menulisnya menyangka iurannya sudah terkonfigurasi.
            errors["employee_rate"] = (
                "Isi minimal salah satu: tarif pegawai atau tarif "
                "perusahaan."
            )

        for low, high, key in (
            (self.base_minimum, self.base_maximum, "base_maximum"),
            (
                self.employee_minimum_amount,
                self.employee_maximum_amount,
                "employee_maximum_amount",
            ),
            (
                self.employer_minimum_amount,
                self.employer_maximum_amount,
                "employer_maximum_amount",
            ),
        ):
            if low is not None and high is not None and high < low:
                errors[key] = (
                    "Nilai maksimum tidak boleh lebih kecil dari nilai "
                    "minimum."
                )

        if self.program_id:
            # Dibaca lewat query, bukan `self.program`: `full_clean()`
            # jalan juga saat program belum ter-`select_related`, dan
            # menyentuh atributnya di situ menarik satu query per baris
            # tanpa kelihatan.
            uses_risk_class = (
                BpjsProgram.objects
                .filter(pk=self.program_id)
                .values_list("uses_risk_class", flat=True)
                .first()
            )

            if uses_risk_class and self.risk_class_id is None:
                # Dibiarkan kosong, aturan ini tidak akan pernah
                # terpilih resolver — dan yang menulisnya menyangka
                # tarif JKK-nya sudah terkonfigurasi.
                errors["risk_class"] = (
                    "Program ini memakai kelas risiko, jadi aturannya "
                    "wajib menyebut kelas risiko yang mana."
                )

            if not uses_risk_class and self.risk_class_id is not None:
                errors["risk_class"] = (
                    "Program ini tidak memakai kelas risiko. Kosongkan "
                    "kelas risikonya."
                )

        if not self.has_employee_side and self.reduces_taxable:
            errors["reduces_taxable"] = (
                "Tidak ada iuran pegawai yang bisa mengurangi dasar "
                "pajak."
            )

        if self.program_id and self.effective_from and not errors:
            overlap = self._overlapping()

            if overlap is not None:
                errors["effective_from"] = (
                    "Rentangnya bertindih dengan aturan yang sudah ada "
                    f"({overlap.effective_from} s.d. "
                    f"{overlap.effective_to or 'seterusnya'}). Tutup "
                    "aturan lama lebih dulu dengan mengisi tanggal "
                    "berakhirnya."
                )

        if errors:
            raise ValidationError(errors)

    def _overlapping(self):
        """
        Aturan lain bercakupan sama yang rentangnya berpotongan.

        Diperiksa di sini, bukan di resolver: resolver yang menemukan
        dua aturan berlaku harus memilih salah satu, dan pilihan apa
        pun yang ia buat adalah tebakan. Yang benar adalah keadaan itu
        tidak pernah tersimpan.
        """
        others = (
            type(self).objects
            .filter(
                program_id=self.program_id,
                company_id=self.company_id,
                # Kelas risiko ikut jadi kunci cakupan: dua kelas
                # berbeda pada program yang sama memang berlaku
                # bersamaan, dan itu justru bentuk yang benar.
                risk_class_id=self.risk_class_id,
                is_deleted=False,
            )
            .exclude(pk=self.pk)
        )

        for other in others:
            starts_after_other_ends = (
                other.effective_to is not None
                and self.effective_from > other.effective_to
            )

            ends_before_other_starts = (
                self.effective_to is not None
                and self.effective_to < other.effective_from
            )

            if not (starts_after_other_ends or ends_before_other_starts):
                return other

        return None

    def __str__(self) -> str:
        return (
            f"{self.program_id} - {self.scope_label} - "
            f"{self.effective_from}"
        )
