"""
Kebijakan perhitungan untuk **sekelompok** pegawai di dalam satu
perusahaan.

Kenapa lapisan ketiga
---------------------
`PayrollSetting` menjawab "bagaimana perusahaan ini menghitung gaji" —
satu baris per company, dan itu benar selama seluruh isi perusahaan
dihitung dengan cara yang sama. Yang ternyata tidak selalu benar: satu
badan hukum bisa berisi staf kantor pusat yang diprorata dengan hari
kalender, staf lokal yang diprorata dengan hari kerja, dan pekerja
harian yang gajinya tidak diprorata sama sekali karena memang dibentuk
dari hari.

Yang **tidak** dilakukan untuk menjawab itu:

* menambah kolom ke `PayrollSetting` — satu baris per company tidak
  bisa berisi tiga cara sekaligus;
* memakai `PayrollGroup` — group menentukan **periode** mana yang
  memuat pegawainya (`PayrollPeriod.payroll_group`), jadi memakainya
  sebagai penentu cara hitung berarti pegawai bulanan dan harian
  mustahil berada di satu run;
* mengenali golongan, lokasi, atau jenis kepegawaian di mesin hitung —
  Payroll tidak boleh tahu nama kategori apa pun. Yang memilih
  kebijakan tetap orang HR, lewat `PayrollAssignment`.

Yang tidak disalin ke sini
--------------------------
`AllowanceTemplate`, `DeductionTemplate`, `OvertimeGroup`, dan
`TaxStatus` sudah punya tempatnya di `PayrollAssignment` dan tetap di
sana. Kebijakan ini hanya berisi **aturan perhitungan yang memang
dipakai bersama**; menyalin seluruh isi assignment ke sini berarti dua
tempat yang harus sepakat tentang hal yang sama.

Kosong berarti ikut perusahaan
------------------------------
Semua kolom penimpa di bawah boleh kosong, dan kosong **selalu**
berarti "ikut `PayrollSetting` perusahaan" — bukan "matikan". Itu yang
membuat kebijakan bisa dibuat untuk satu perbedaan saja tanpa menyalin
ulang seluruh keputusan perusahaan, dan yang membuat perubahan
kebijakan perusahaan tetap menetes ke bawah.

Effective date-nya bukan di sini
--------------------------------
Baris ini tidak punya rentang berlaku, dan itu disengaja: yang
effective-dated `PayrollAssignment`, dan di situlah pegawai memilih
kebijakannya. Assignment yang berlaku 1 Juli membawa kebijakan barunya
untuk payroll Juli, sementara payroll Juni tetap membaca assignment
lama beserta kebijakan lamanya. Menaruh rentang berlaku di dua tempat
berarti dua jawaban untuk satu pertanyaan.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import (
    PayrollDailyRateMethod,
    PayrollPayBasis,
    PayrollPolicyToggle,
    PayrollProrationMethod,
)


class PayrollPolicy(BaseModel):
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        related_name="payroll_policies",
        help_text=(
            "Kebijakan ini milik satu perusahaan dan hanya boleh "
            "dipakai pegawai perusahaan itu."
        ),
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    # ------------------------------------------------------------------
    # Dasar perhitungan
    # ------------------------------------------------------------------

    # Bawaan MONTHLY **bukan** keputusan bisnis: seluruh perhitungan
    # sebelum kebijakan ini ada memang bulanan. Bawaan lain berarti
    # sebuah tabel yang lahir mengubah angka payroll yang sedang
    # berjalan.
    pay_basis = models.CharField(
        max_length=20,
        choices=PayrollPayBasis.choices,
        default=PayrollPayBasis.MONTHLY,
        help_text=(
            "Bulanan: gaji sebulan dipecah jadi hak harian kalau masa "
            "kerjanya tidak penuh. Harian: upah dibentuk dari hari "
            "yang benar-benar dibayar, jadi tidak ada prorata dan "
            "tidak ada potongan ketidakhadiran."
        ),
    )

    # ------------------------------------------------------------------
    # Penimpa aturan bulanan. Kosong = ikut PayrollSetting perusahaan.
    # ------------------------------------------------------------------

    proration_method = models.CharField(
        max_length=20,
        choices=PayrollProrationMethod.choices,
        blank=True,
        default="",
        help_text=(
            "Dikosongkan = ikut kebijakan perusahaan di Payroll "
            "Settings."
        ),
    )

    # Tiga keadaan, bukan dua: ya, tidak, dan **ikut perusahaan** —
    # dan yang ketiga yang paling sering, karena kebijakan biasanya
    # dibuat untuk satu perbedaan saja. Kotak centang tidak bisa
    # menyampaikan tiga keadaan, dan kotak yang tidak dicentang
    # terbaca sebagai "tidak".
    prorate_on_join = models.CharField(
        max_length=10,
        choices=PayrollPolicyToggle.choices,
        default=PayrollPolicyToggle.INHERIT,
        help_text="Pegawai yang masuk di tengah periode diprorata.",
    )

    prorate_on_termination = models.CharField(
        max_length=10,
        choices=PayrollPolicyToggle.choices,
        default=PayrollPolicyToggle.INHERIT,
        help_text="Pegawai yang berhenti di tengah periode diprorata.",
    )

    attendance_deduction_method = models.CharField(
        max_length=20,
        choices=PayrollProrationMethod.choices,
        blank=True,
        default="",
        help_text=(
            "Pembagi nilai sehari untuk potongan absen dan cuti tidak "
            "dibayar. Dikosongkan = ikut kebijakan perusahaan."
        ),
    )

    deduct_absence = models.CharField(
        max_length=10,
        choices=PayrollPolicyToggle.choices,
        default=PayrollPolicyToggle.INHERIT,
        help_text="Hari alpa memotong gaji.",
    )

    deduct_unpaid_leave = models.CharField(
        max_length=10,
        choices=PayrollPolicyToggle.choices,
        default=PayrollPolicyToggle.INHERIT,
        help_text=(
            "Hari cuti berjenis tidak dibayar memotong gaji. Jenis "
            "cuti mana yang tidak dibayar tetap ditentukan Payroll "
            "Leave Rule."
        ),
    )

    # ------------------------------------------------------------------
    # Aturan harian
    # ------------------------------------------------------------------

    # Sengaja **tanpa bawaan**, seperti `OvertimeGroup.tier_basis`:
    # kedua caranya lazim dan menghasilkan angka yang berbeda, jadi
    # memilihkan salah satunya diam-diam berarti mengambil keputusan
    # bisnis atas nama perusahaan. Kebijakan harian yang belum memilih
    # ditolak validasi run.
    daily_rate_method = models.CharField(
        max_length=20,
        choices=PayrollDailyRateMethod.choices,
        blank=True,
        default="",
        help_text=(
            "Wajib diisi kalau dasar perhitungannya Harian. Sistem "
            "tidak memilihkan — kedua caranya lazim dan hasilnya "
            "berbeda."
        ),
    )

    daily_rate_divisor = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Pembagi gaji sebulan jadi upah sehari, mis. 25 atau 30. "
            "Hanya dipakai kalau tarif harian diturunkan dari gaji "
            "sebulan."
        ),
    )

    # BUSINESS SUB-DECISION — DAILY PAID LEAVE.
    #
    # Tidak ada aturan authoritative di sistem ini yang menyatakan
    # pekerja harian dibayar atau tidak pada hari cuti yang disetujui.
    # `PayrollLeaveRule` cuma menyatakan jenis cutinya dibayar atau
    # tidak untuk pegawai **bulanan** — di sana "dibayar" berarti
    # "tidak memotong", pernyataan yang tidak punya arti pada gaji yang
    # dibentuk dari hari.
    #
    # Karena itu tanpa bawaan, dan kebijakan harian yang belum
    # memilihnya ditolak validasi. Menebak di sini berarti seseorang
    # dibayar atau tidak dibayar karena sebuah nilai bawaan.
    pay_paid_leave = models.CharField(
        max_length=10,
        choices=[
            ("yes", "Dibayar - hari cuti tetap menghasilkan upah sehari"),
            ("no", "Tidak dibayar - hanya hari kerja nyata yang dibayar"),
        ],
        blank=True,
        default="",
        help_text=(
            "Wajib diisi kalau dasar perhitungannya Harian. Sistem "
            "tidak memilihkan — keduanya lazim dan menentukan apakah "
            "seseorang dibayar."
        ),
    )

    is_active = models.BooleanField(default=True)

    # ------------------------------------------------------------------

    @property
    def is_daily(self) -> bool:
        return self.pay_basis == PayrollPayBasis.DAILY

    @property
    def pays_paid_leave(self) -> bool | None:
        """
        `True`, `False`, atau `None` untuk **belum ditentukan**.

        Yang ketiga bukan kelalaian yang perlu ditutup dengan bawaan:
        ia keadaan yang ditolak validasi run, supaya tidak ada orang
        yang dibayar atau tidak dibayar karena sebuah nilai bawaan.
        """
        if not self.pay_paid_leave:
            return None

        return self.pay_paid_leave == "yes"

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.daily_rate_divisor is not None
            and self.daily_rate_divisor <= Decimal("0")
        ):
            errors["daily_rate_divisor"] = (
                "Pembagi harus lebih besar dari nol."
            )

        if (
            self.daily_rate_method == PayrollDailyRateMethod.FROM_MONTHLY
            and not self.daily_rate_divisor
        ):
            errors["daily_rate_divisor"] = (
                "Pembagi wajib diisi kalau tarif harian diturunkan "
                "dari gaji sebulan."
            )

        # Konfigurasi yang **pasti diabaikan** ditolak di layar tempat
        # ia ditulis. Aturan harian pada kebijakan bulanan (dan
        # sebaliknya) bukan sekadar tidak terpakai — ia terbaca sebagai
        # janji yang tidak pernah ditepati, dan orang yang membacanya
        # menyangka payroll-nya sudah diatur.
        if self.is_daily:
            for name, label in (
                ("proration_method", "Salary Proration Method"),
                ("attendance_deduction_method", "Absence Deduction Method"),
            ):
                if getattr(self, name):
                    errors[name] = (
                        f"{label} tidak berlaku untuk dasar Harian — "
                        "upah harian dibentuk dari hari yang dibayar, "
                        "bukan diprorata lalu dipotong."
                    )

            for name, label in (
                ("prorate_on_join", "Prorate on Join"),
                ("prorate_on_termination", "Prorate on Termination"),
                ("deduct_absence", "Deduct Absence"),
                ("deduct_unpaid_leave", "Deduct Unpaid Leave"),
            ):
                if getattr(self, name) != PayrollPolicyToggle.INHERIT:
                    errors[name] = (
                        f"{label} tidak berlaku untuk dasar Harian — "
                        "upah harian dibentuk dari hari yang dibayar."
                    )
        else:
            if self.daily_rate_method:
                errors["daily_rate_method"] = (
                    "Daily Rate Method hanya berlaku untuk dasar "
                    "Harian."
                )

            if self.pay_paid_leave:
                errors["pay_paid_leave"] = (
                    "Bayar Hari Cuti hanya berlaku untuk dasar Harian. "
                    "Untuk pegawai bulanan, jenis cuti mana yang "
                    "memotong ditentukan Payroll Leave Rule."
                )

        if errors:
            raise ValidationError(errors)

    class Meta:
        db_table = "payroll_policy"
        ordering = ["company__name", "code"]
        verbose_name = "Payroll Policy"
        verbose_name_plural = "Payroll Policies"

        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_policy_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
