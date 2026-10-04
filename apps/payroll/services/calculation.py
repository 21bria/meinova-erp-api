"""
Mesin hitung payroll.

Satu pegawai, satu periode, satu keluaran: daftar komponen beserta
totalnya. Tidak menyentuh database sama sekali di luar membaca
konfigurasi — hasilnya dikembalikan sebagai objek, dan yang menyimpannya
`PayrollRunService`. Itu yang membuatnya bisa dijalankan berulang kali
(preview di layar Review, hitung ulang setelah input berubah) tanpa
menyisakan setengah hasil.

**Reproducible.** Semua yang mempengaruhi angka masuk lewat parameter:
konfigurasi dari master, fakta dari adapter, input dari periode. Tidak
ada `timezone.now()` di dalam perhitungan, tidak ada pembacaan
`is_current` yang bisa bergeser besok.

Urutan yang dijamin, dan urutannya penting karena tiap tahap jadi dasar
tahap berikutnya:

    1. Basic salary (diprorata)
    2. Earning dari Allowance Template
    3. Overtime
    4. Earning dari Payroll Input
       → gross & taxable earning terbentuk di sini
    5. Deduction dari Deduction Template (termasuk BPJS)
       → potongan yang `reduces_taxable` mengurangi dasar pajak
    6. Deduction dari absensi dan cuti tidak dibayar — dua komponen
       terpisah, memakai pembagi hari kebijakannya sendiri
    7. Deduction dari Payroll Input
    8. Pajak (PPh21), dihitung terakhir karena dasarnya baru lengkap
       setelah tahap 5
    = Net Pay
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from apps.payroll.models import (
    EARNINGS_REDUCTION_BASES,
    QUANTITY_BASES,
    OvertimeTierBasis,
    PayrollBasis,
    PayrollPayBasis,
    PayrollComponentSource,
    PayrollComponentType,
    PayrollFindingLevel,
)

ZERO = Decimal("0.00")
ONE = Decimal("1")
CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def plain(value) -> str:
    """
    Angka tanpa nol berekor, untuk keterangan yang dibaca orang.

    "1 jam x 1,5" adalah kalimat; "1.00 jam x 1.50" adalah keluaran
    mesin yang kebetulan bisa dibaca. Keterangan perhitungan ada untuk
    dicocokkan dengan hitungan tangan HR, jadi ia harus berbunyi
    seperti hitungan tangan.

    `:f` wajib sesudah `normalize()`: tanpa itu 100 tercetak "1E+2".
    """
    return f"{Decimal(value or 0).normalize():f}"


@dataclass
class ComponentResult:
    component_type: str
    source: str
    code: str
    name: str
    basis: str
    amount: Decimal
    base_amount: Decimal = ZERO
    rate: Decimal = ZERO
    quantity: Decimal = ONE
    sequence: int = 1
    is_taxable: bool = False
    reduces_taxable: bool = False
    is_prorated: bool = False
    reference_type: str = ""
    reference_id: str = ""
    calculation_note: str = ""


@dataclass
class CalculationInput:
    """
    Seluruh bahan perhitungan, dibekukan sebagai satu objek.
    """

    basic_salary: Decimal
    period_days: int
    divisor_days: Decimal
    proration_factor: Decimal

    working_days: Decimal
    paid_days: Decimal
    attendance_days: Decimal
    absent_days: Decimal
    leave_days: Decimal
    unpaid_leave_days: Decimal
    overtime_hours: Decimal

    allowance_lines: list = field(default_factory=list)
    deduction_lines: list = field(default_factory=list)
    inputs: list = field(default_factory=list)

    # Lapisan kebijakan yang menitipkan baris tambahan — BPJS yang
    # pertama. Sebuah **callable**, bukan queryset: mesin hitung ini
    # tidak pernah menyentuh ORM, dan itu satu-satunya alasan aturan
    # BPJS bisa menumpang seluruh jalurnya tanpa mesin hitung kedua.
    #
    # Dipanggil di fase potongan, sesudah penghasilan selesai —
    # dasarnya memang baru lengkap di situ.
    bpjs_lines_provider: object = None

    # Hanya untuk menjelaskan angkanya di `calculation_note`. Faktornya
    # sendiri sudah dihitung service — mesin ini tidak boleh tahu apa
    # itu kalender kerja, apalagi membacanya dari database.
    proration_method: str = ""
    proration_method_label: str = ""
    proration_base_days: Decimal = ZERO

    # --- potongan ketidakhadiran (Business Decision #2) ----------------
    #
    # Pembagi **sendiri**, bukan `proration_base_days` di atas. Prorata
    # menjawab "berapa hak gaji orang yang belum sebulan bekerja";
    # potongan menjawab "berapa nilai sehari yang hilang kalau ia tidak
    # masuk". Perusahaan yang memprorata dengan hari kalender tapi
    # memotong dengan pembagi 30 lazim, dan satu angka untuk dua
    # pertanyaan membuat salah satunya pasti salah.
    #
    # Kosong (nol) berarti jatuh kembali ke `divisor_days` — pembagi
    # hari yang tertulis di periode, perilaku sebelum kebijakan ini ada.
    deduction_base_days: Decimal = ZERO
    deduction_method: str = ""
    deduction_method_label: str = ""

    deduct_absence: bool = True
    deduct_unpaid_leave: bool = True

    # --- dasar perhitungan (Payroll Policy) ---------------------------
    #
    # Bulanan atau harian. Yang menentukan **kebijakan yang dipilih HR**
    # lewat `PayrollAssignment.payroll_policy`, bukan golongan, jenis
    # kepegawaian, atau lokasi — mesin ini tidak mengenal satu pun nama
    # kategori itu, dan tidak boleh.
    #
    # Bawaannya bulanan: seluruh perhitungan sebelum kebijakan ini ada
    # memang bulanan.
    pay_basis: str = PayrollPayBasis.MONTHLY

    # Upah sehari, sudah selesai diresolusi service — entah diambil apa
    # adanya dari assignment atau diturunkan dari gaji sebulan. Sengaja
    # **tidak** dibulatkan di sini: pembulatannya sekali saja, sesudah
    # dikali jumlah hari.
    daily_rate: Decimal = ZERO

    # Hari yang benar-benar membentuk upah harian. Sumber harinya
    # ditentukan adapter (kehadiran, ditambah cuti dibayar kalau
    # kebijakannya begitu); mesin ini menerima angkanya sudah jadi dan
    # tidak mengenal tanggal.
    payable_days: Decimal = ZERO

    # Asal tarif harian, untuk keterangan yang dibaca orang.
    daily_rate_note: str = ""

    overtime_multiplier: Decimal = ONE
    overtime_divisor: Decimal = Decimal("173")
    overtime_eligible: bool = False

    # --- lembur bertingkat (Business Decision #4) ---------------------
    #
    # `overtime_tiers` daftar objek berisi `hour_from`, `hour_to`
    # (boleh None untuk tingkat teratas) dan `multiplier`. Kosong =
    # kelompok ini belum punya tingkat, dan `overtime_multiplier` di
    # atas yang berlaku — itu yang menjaga angka tenant existing tidak
    # bergeser.
    #
    # Tingkatnya **tidak** ditanam di sini: 1,5x dan 2x adalah
    # kebijakan perusahaan, bukan aturan mesin hitung.
    overtime_tiers: list = field(default_factory=list)

    # "daily" = tingkat disusun ulang tiap hari lembur; "monthly" =
    # sekali untuk seluruh jam sebulan. Kosong = tidak memakai tingkat.
    overtime_tier_basis: str = ""

    # Jam lembur per tanggal. Dibutuhkan hanya oleh basis harian, dan
    # sudah jadi angka — mesin ini tetap tidak mengenal tanggal.
    overtime_daily_hours: list = field(default_factory=list)

    # Kelompok lembur memang ada. Dipisah dari `overtime_divisor`
    # supaya "belum punya Overtime Group" bisa disebut dengan namanya
    # sendiri, bukan menyamar jadi "pembagi kosong".
    overtime_group_present: bool = True

    non_taxable_income: Decimal = ZERO
    tax_brackets: list = field(default_factory=list)


@dataclass
class CalculationResult:
    components: list[ComponentResult] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)

    gross_earning: Decimal = ZERO
    taxable_earning: Decimal = ZERO
    total_deduction: Decimal = ZERO
    tax_amount: Decimal = ZERO
    net_pay: Decimal = ZERO

    # Beban perusahaan. Berdiri sendiri karena ia bukan bagian dari
    # gross maupun dari potongan: `net_pay` tidak berubah sedikit pun
    # karenanya, sedangkan biaya tenaga kerja tidak lengkap tanpanya.
    employer_contribution: Decimal = ZERO

    # Dipisah per sumber, bukan dijumlahkan jadi satu angka
    # "ketidakhadiran". Alpa dan cuti tidak dibayar datang dari dua
    # dokumen yang berbeda dan dibantah dengan cara yang berbeda; satu
    # angka gabungan membuat pertanyaan "yang mana yang salah" tidak
    # bisa dijawab.
    absence_deduction: Decimal = ZERO
    unpaid_leave_deduction: Decimal = ZERO

    # Tunjangan, dipisah menurut klasifikasi pajaknya. Diturunkan dari
    # komponen — bukan angka kedua yang harus dijaga tetap sepakat.
    #
    # Ada supaya "tunjangan mana yang menambah dasar PPh21" bisa dijawab
    # tanpa menjumlahkan baris satu-satu, dan supaya test bisa
    # menunjukkan **sumber** pergeseran dasar pajak. Rumus PPh21-nya
    # sendiri tidak menyentuh dua angka ini.
    taxable_allowance: Decimal = ZERO
    non_taxable_allowance: Decimal = ZERO

    def add_finding(self, *, level: str, code: str, message: str) -> None:
        self.findings.append(
            {"level": level, "code": code, "message": message},
        )


class PayrollCalculationService:
    """
    Classmethod-only, tanpa keadaan. Sama seperti service lain di
    codebase ini.
    """

    BASIC_CODE = "BASIC"
    BASIC_NAME = "Basic Salary"
    DAILY_NAME = "Daily Wage"
    OVERTIME_CODE = "OT"
    OVERTIME_NAME = "Overtime"

    # ------------------------------------------------------------------

    @classmethod
    def calculate(cls, data: CalculationInput) -> CalculationResult:
        result = CalculationResult()

        cls._basic(data, result)
        cls._allowances(data, result)
        cls._overtime(data, result)
        cls._input_earnings(data, result)

        # Sebelum `_settle_earnings`, dan itu seluruh isi Business
        # Decision #2: hari yang tidak dijalani bukan penghasilan yang
        # ditahan, melainkan penghasilan yang tidak pernah terbentuk.
        # Gross, taxable, dan semua yang membacanya sesudah ini —
        # potongan berbasis persentase gross, dasar PPh21 — harus
        # melihat gaji yang benar-benar didapat.
        cls._absence_reductions(data, result)

        cls._settle_earnings(result)

        cls._deductions(data, result)
        cls._input_deductions(data, result)

        cls._tax(data, result)

        cls._settle_totals(result)

        return result

    # ------------------------------------------------------------------
    # Earning
    # ------------------------------------------------------------------

    @classmethod
    def _prorate(cls, value: Decimal, data: CalculationInput) -> Decimal:
        """
        Nilai yang sudah diprorata, **dibulatkan sekali saja**.

        Dihitung dari hari (`eligible / pembagi`), bukan dari
        `proration_factor` yang sudah dibulatkan enam desimal. Bedanya
        bukan teoretis: 20/30 dibulatkan jadi 0,666667, dan dikalikan
        gaji 9.000.000 menghasilkan 6.000.003 — tiga rupiah yang tidak
        bisa dijelaskan kepada siapa pun, dan yang jumlahnya berubah
        mengikuti besar gajinya.

        Angka yang tercetak di `calculation_note` juga hari, bukan
        faktor, jadi hitungan tangan HR (9.000.000 × 20 / 30) menghasil-
        kan tepat angka yang sama dengan yang dibayar.
        """
        if data.proration_factor == ONE:
            return value

        if data.proration_base_days > ZERO:
            return value * data.working_days / data.proration_base_days

        return value * data.proration_factor

    @classmethod
    def _proration_applies(
        cls,
        *,
        basis: str,
        is_prorated: bool,
        data: CalculationInput,
    ) -> bool:
        """
        Prorata masa kerja berlaku untuk komponen ini?

        Tiga syarat, dan yang ketiga yang paling mudah terlewat:

        1. barisnya dikonfigurasi `is_prorated`;
        2. bulannya memang tidak dijalani penuh;
        3. **basisnya bernilai bulanan.**

        Basis per hari (`QUANTITY_BASES`) nilainya sudah hasil kali
        dengan hari yang benar-benar terjadi. Tunjangan makan 25.000 x
        hari hadir pada pegawai yang masuk tanggal 16 sudah menghitung
        sebelas hari yang ia masuk; mengalikannya lagi dengan 0,5
        membayar 5,5 hari untuk sebelas hari kerja. Itu potongan kedua
        yang tidak diminta siapa pun, dan angkanya tidak muncul di satu
        layar pun sebagai potongan — ia menyamar sebagai tunjangan yang
        nilainya "memang segitu".

        Seed memang sudah menulis `is_prorated=False` untuk baris per
        hari, tapi itu kesepakatan yang hidup di seed. Perusahaan yang
        membuat komponennya sendiri dapat bawaan `True`, dan tidak ada
        yang menahannya.
        """
        if not is_prorated:
            return False

        if data.proration_factor == ONE:
            return False

        return basis not in QUANTITY_BASES

    @classmethod
    def _basic(cls, data: CalculationInput, result: CalculationResult) -> None:
        """
        Penghasilan pokok. **Dua jalan, dan hanya dasar perhitungannya
        yang memilih** — bukan golongan, jenis kepegawaian, atau lokasi
        pegawainya.

        Bulanan: angka sebulan dipecah jadi hak harian kalau masa
        kerjanya tidak penuh. Harian: upah dibentuk dari hari yang
        dibayar, jadi tidak ada yang perlu diprorata dan tidak ada yang
        perlu dipotong lagi sesudahnya.
        """
        if data.pay_basis == PayrollPayBasis.DAILY:
            cls._daily_wage(data, result)
            return

        amount = money(cls._prorate(data.basic_salary, data))

        note = ""

        if data.proration_factor != ONE:
            # Ditulis lengkap dengan pembilang dan pembagi supaya
            # pertanyaan "kenapa gaji pokoknya 4.500.000" dijawab
            # barisnya sendiri, bukan dihitung ulang orang.
            method = data.proration_method_label or data.proration_method

            basis = ""

            if data.proration_base_days > ZERO:
                basis = (
                    f" ({data.working_days} / {data.proration_base_days} hari"
                    f"{f', {method}' if method else ''})"
                )
            elif method:
                basis = f" ({method})"

            note = (
                f"Prorata {data.proration_factor} "
                f"dari {money(data.basic_salary)}{basis}"
            )

        result.components.append(
            ComponentResult(
                component_type=PayrollComponentType.EARNING,
                source=PayrollComponentSource.BASIC,
                code=cls.BASIC_CODE,
                name=cls.BASIC_NAME,
                basis=PayrollBasis.FIXED,
                base_amount=money(data.basic_salary),
                amount=amount,
                sequence=1,
                is_taxable=True,
                is_prorated=data.proration_factor != ONE,
                calculation_note=note,
            ),
        )

    @classmethod
    def _daily_wage(
        cls,
        data: CalculationInput,
        result: CalculationResult,
    ) -> None:
        """
        Upah pegawai harian: `tarif sehari x hari yang dibayar`.

        **Tidak ada potongan kedua**, dan itu inti bentuk ini. Hari alpa
        dan hari cuti tidak dibayar tidak membentuk upah sejak awal;
        memotongnya lagi berarti satu hari tidak masuk mengurangi dua
        hari upah. Yang menjaganya bukan kehati-hatian di sini
        melainkan `_switched_off` — jalur potongan ketidakhadiran mati
        seluruhnya untuk dasar harian, baik yang otomatis maupun yang
        datang dari Deduction Template.

        Harinya tetap tercatat di barisnya. "Tidak menghasilkan upah"
        dan "tidak pernah terjadi" harus tetap bisa dibedakan orang
        yang membaca slipnya.

        Prorata masa kerja juga tidak dikenakan: pegawai harian yang
        masuk tanggal 16 sudah hanya punya hari sejak tanggal 16.
        """
        if data.daily_rate <= ZERO:
            # Nol tidak diam-diam jadi upah nol. Tarif harian yang
            # belum bisa dihitung adalah konfigurasi yang belum
            # selesai, dan itu menghalangi Finalize.
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="daily_rate_missing",
                message=(
                    "Upah sehari belum bisa dihitung"
                    f"{f' ({data.daily_rate_note})' if data.daily_rate_note else ''}"
                    ". Periksa Payroll Policy dan Payroll Assignment "
                    "pegawai ini."
                ),
            )

        # Satu pembulatan, di akhir. Tarif 3.000.000/26 dibulatkan
        # lebih dulu lalu dikali 26 menghasilkan 2.999.997,74.
        amount = money(data.daily_rate * data.payable_days)

        # Ditulis sebagai ekspresi yang **menghasilkan angkanya
        # sendiri**. Tarif harian yang diturunkan dari gaji sebulan
        # jarang bulat: 3.000.000/26 = 115.384,615..., dan "22 hari x
        # 115.384,62" menghasilkan 2.538.461,64 sementara yang dibayar
        # 2.538.461,54. Keterangan yang tidak cocok dengan angkanya
        # lebih buruk daripada tidak ada keterangan.
        if data.daily_rate <= ZERO:
            # Tarifnya nol: keterangannya **alasan**, bukan ekspresi.
            # "20 hari x cara upah harian belum ditentukan" adalah
            # kalimat yang tidak menjelaskan apa pun.
            note = (
                f"{plain(data.payable_days)} hari x tarif yang belum "
                f"bisa dihitung"
                f"{f' ({data.daily_rate_note})' if data.daily_rate_note else ''}"
            )

        elif data.daily_rate_note:
            note = (
                f"{plain(data.payable_days)} hari x "
                f"{data.daily_rate_note}"
                f"; setara {money(data.daily_rate)}/hari"
            )

        else:
            note = (
                f"{plain(data.payable_days)} hari x "
                f"{money(data.daily_rate)}/hari"
            )

        skipped = []

        if data.absent_days:
            skipped.append(f"{plain(data.absent_days)} hari alpa")

        if data.unpaid_leave_days:
            skipped.append(
                f"{plain(data.unpaid_leave_days)} hari cuti tidak dibayar",
            )

        if skipped:
            # Ditulis di barisnya sendiri supaya "kenapa upahnya cuma
            # 20 hari" tidak perlu dicocokkan dengan layar absensi.
            note = f"{note}; tanpa upah: {', '.join(skipped)}"

        result.components.append(
            ComponentResult(
                component_type=PayrollComponentType.EARNING,
                source=PayrollComponentSource.BASIC,
                code=cls.BASIC_CODE,
                name=cls.DAILY_NAME,
                basis=PayrollBasis.PER_PAID_DAY,
                base_amount=money(data.basic_salary),
                rate=data.daily_rate,
                quantity=data.payable_days,
                amount=amount,
                sequence=1,
                is_taxable=True,
                # Bukan diprorata, dan itu pernyataan yang benar: upah
                # ini memang dibentuk dari hari, tidak pernah dipecah
                # dari angka sebulan.
                is_prorated=False,
                calculation_note=note,
            ),
        )

    @classmethod
    def _allowances(cls, data: CalculationInput, result: CalculationResult) -> None:
        """
        Tunjangan dari paket `AllowanceTemplate` pegawai ini.

        **Urutannya tetap, dan urutannya yang menentukan angkanya:**

            1. nilai mentah dari basisnya (nominal / persen / per hari)
            2. prorata masa kerja — hanya kalau basisnya bulanan
            3. jepit minimum/maksimum
            4. pembulatan uang

        Menjepit sebelum memprorata akan membuat plafon berlaku pada
        angka sebulan lalu hasilnya diprorata di bawah plafon; menjepit
        sesudah memprorata membuat plafon berarti "paling banyak segini
        yang dibayar bulan ini". Yang kedua yang dipakai, dan itu
        perilaku yang sudah berjalan sejak sebelum keputusan #3 —
        tidak diubah, cuma sekarang tertulis dan diuji.
        """
        for index, line in enumerate(data.allowance_lines, start=1):
            amount, base, note = cls._evaluate(
                data=data,
                result=result,
                basis=line.basis,
                unit_amount=Decimal(line.amount or 0),
                rate=Decimal(line.rate or 0),
                code=line.code,
            )

            raw = amount

            prorated = cls._proration_applies(
                basis=line.basis,
                is_prorated=line.is_prorated,
                data=data,
            )

            if prorated:
                amount = money(cls._prorate(amount, data))
                note = f"{note}; {cls._proration_note(data, raw)}".strip("; ")

            elif line.is_prorated and data.proration_factor != ONE:
                # Dikonfigurasi diprorata tapi basisnya sudah per hari.
                # Ditulis di barisnya supaya "kenapa tunjangan ini tidak
                # diprorata padahal Prorated-nya Yes" punya jawaban di
                # tempat angkanya, bukan cuma di kode.
                note = (
                    f"{note}; tanpa prorata (basis sudah per hari nyata)"
                ).strip("; ")

            amount, clamp_note = cls._clamped(
                amount,
                minimum=getattr(line, "minimum_amount", None),
                maximum=getattr(line, "maximum_amount", None),
            )

            if clamp_note:
                note = f"{note}; {clamp_note}".strip("; ")

            result.components.append(
                ComponentResult(
                    component_type=PayrollComponentType.EARNING,
                    source=PayrollComponentSource.ALLOWANCE_TEMPLATE,
                    code=line.code,
                    name=line.name,
                    basis=line.basis,
                    base_amount=base,
                    rate=Decimal(line.rate or 0),
                    quantity=cls._quantity_for(data, line.basis),
                    amount=amount,
                    sequence=line.sequence or (index + 1),
                    is_taxable=line.is_taxable,
                    # Prorata yang **benar-benar dikenakan**, bukan
                    # kolom konfigurasinya. Baris yang bertanda
                    # "diprorata" padahal angkanya utuh adalah jejak
                    # audit yang berdusta; `_basic` sudah lama memakai
                    # arti efektif ini.
                    is_prorated=prorated,
                    reference_type="payroll.allowance_template_line",
                    reference_id=str(line.pk),
                    calculation_note=note,
                ),
            )

    @classmethod
    def _overtime(cls, data: CalculationInput, result: CalculationResult) -> None:
        """
        Upah lembur. **Jamnya datang dari luar; yang dihitung di sini
        harganya.**

        Payroll tidak pernah menentukan jam mana yang lembur — itu
        milik HR/Attendance/Overtime beserta alur persetujuannya.
        Adapter hanya menyerahkan jam yang sudah sah, dan mesin ini
        mengubahnya jadi rupiah.

        Urutannya:

            1. pegawai eligible? kalau tidak, jamnya tetap tercatat
               tapi tidak dibayar, dengan temuan yang menyebutnya
            2. kelompok lembur ada dan pembaginya sah?
            3. jam disusun ke tingkat — atau dikali pengali tunggal
               kalau kelompoknya belum punya tingkat
            4. satu pembulatan, di akhir
        """
        if data.overtime_hours < ZERO:
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="overtime_hours_negative",
                message=(
                    f"Jam lembur bernilai negatif ({data.overtime_hours}). "
                    "Periksa data sumbernya."
                ),
            )
            return

        if not data.overtime_hours:
            return

        if not data.overtime_eligible:
            # Jamnya **tidak** dihapus dan tidak disembunyikan. Yang
            # terjadi cuma tidak dibayar, dan itu harus terbaca —
            # "kenapa lembur saya tidak muncul" adalah pertanyaan yang
            # jawabannya tidak boleh cuma ada di kode.
            result.add_finding(
                level=PayrollFindingLevel.WARNING,
                code="overtime_not_eligible",
                message=(
                    f"Ada {data.overtime_hours} jam lembur tercatat, "
                    "tapi pegawai ini tidak eligible overtime pada "
                    "payroll assignment-nya. Lembur tidak dibayar."
                ),
            )
            return

        if not data.overtime_group_present:
            # Disebut dengan namanya sendiri. Sebelumnya keadaan ini
            # jatuh ke "pembagi kosong" — pesan yang menyuruh orang
            # memperbaiki kolom pada master yang belum dipilihnya.
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="overtime_group_missing",
                message=(
                    f"Ada {data.overtime_hours} jam lembur dan pegawai "
                    "ini eligible, tapi payroll assignment-nya belum "
                    "menunjuk Overtime Group. Aturan pengalinya tidak "
                    "bisa ditentukan."
                ),
            )
            return

        if not data.overtime_divisor or data.overtime_divisor <= ZERO:
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="overtime_divisor_missing",
                message=(
                    "Overtime Group belum punya Hourly Divisor, jadi "
                    "upah per jam tidak bisa dihitung."
                ),
            )
            return

        weighted, note = cls._overtime_weighted_hours(data, result)

        if weighted is None:
            return

        hourly_exact = Decimal(data.basic_salary) / Decimal(
            data.overtime_divisor,
        )

        # **Satu pembulatan.** Nilainya dihitung penuh dari
        # `gaji / pembagi x jam-berbobot`, bukan dari tarif yang sudah
        # dipotong enam desimal lalu dikalikan lagi — pada lembur
        # bertingkat, tiap tingkat akan menyumbang selisihnya sendiri
        # dan totalnya tidak bisa dicocokkan tangan.
        amount = money(hourly_exact * weighted)

        # Tarif per jam tetap ditampilkan enam desimal: itu angka yang
        # dicari orang, dan presisi itu yang membuat hitungan tangan
        # HR jatuh di rupiah yang sama.
        hourly_display = hourly_exact.quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP,
        )

        result.components.append(
            ComponentResult(
                component_type=PayrollComponentType.EARNING,
                source=PayrollComponentSource.OVERTIME,
                code=cls.OVERTIME_CODE,
                name=cls.OVERTIME_NAME,
                basis=PayrollBasis.PER_OVERTIME_HOUR,
                base_amount=money(data.basic_salary),
                rate=hourly_display,
                quantity=data.overtime_hours,
                amount=amount,
                sequence=500,
                is_taxable=True,
                calculation_note=(
                    f"{money(data.basic_salary)} / "
                    f"{plain(data.overtime_divisor)} = "
                    f"{hourly_display}/jam; "
                    f"{note}"
                ),
            ),
        )

    @classmethod
    def _overtime_weighted_hours(
        cls,
        data: CalculationInput,
        result: CalculationResult,
    ):
        """
        Jam lembur **berbobot** — jumlah `jam x pengali` — beserta
        keterangan yang menghasilkannya.

        Mengembalikan `(None, "")` kalau konfigurasinya tidak bisa
        dipakai; temuannya sudah ditambahkan.

        Dipisah dari `_overtime` karena di sinilah satu-satunya
        percabangan kebijakan: pengali tunggal atau bertingkat, dan
        kalau bertingkat, disusun per hari atau dari total sebulan.
        """
        tiers = list(data.overtime_tiers or [])

        if not tiers:
            multiplier = Decimal(data.overtime_multiplier or 0)

            if multiplier <= ZERO:
                result.add_finding(
                    level=PayrollFindingLevel.ERROR,
                    code="overtime_multiplier_invalid",
                    message=(
                        "Overtime Group belum punya pengali yang sah "
                        "dan belum punya tingkat, jadi upah lembur "
                        "tidak bisa dihitung."
                    ),
                )
                return None, ""

            hours = Decimal(data.overtime_hours)

            return (
                hours * multiplier,
                f"{plain(hours)} jam x {plain(multiplier)}",
            )

        basis = data.overtime_tier_basis

        if basis == OvertimeTierBasis.DAILY:
            buckets = [Decimal(hours) for hours in data.overtime_daily_hours]

            if not buckets:
                # Basis harian tanpa rincian per hari berarti angkanya
                # akan disusun seolah seluruh jam terjadi dalam satu
                # hari — diam-diam memberi tarif tingkat atas. Lebih
                # baik berhenti dan menyebutnya.
                result.add_finding(
                    level=PayrollFindingLevel.ERROR,
                    code="overtime_daily_hours_missing",
                    message=(
                        "Overtime Group memakai tingkat per hari, tapi "
                        "rincian jam per tanggal tidak tersedia."
                    ),
                )
                return None, ""

        elif basis == OvertimeTierBasis.MONTHLY:
            buckets = [Decimal(data.overtime_hours)]

        else:
            # Ada tingkat tapi belum dinyatakan disusun per apa. Dua
            # jawabannya menghasilkan angka yang jauh berbeda, jadi
            # menebak salah satunya berarti mengambil keputusan bisnis
            # atas nama perusahaan.
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="overtime_tier_basis_missing",
                message=(
                    "Overtime Group punya tingkat pengali tapi belum "
                    "menyatakan tingkatnya disusun per hari lembur "
                    "atau dari total jam sebulan."
                ),
            )
            return None, ""

        weighted = ZERO
        parts: list[tuple] = []
        uncovered = ZERO
        overlapped = ZERO

        for hours in buckets:
            bucket_weighted, bucket_parts, covered = (
                cls._spread_over_tiers(hours, tiers)
            )

            weighted += bucket_weighted
            parts.extend(bucket_parts)

            if covered > hours:
                overlapped += covered - hours
            else:
                uncovered += hours - covered

        if overlapped > ZERO:
            # Rentang yang bertumpang tindih membuat satu jam dihitung
            # dua kali — pegawai dibayar untuk jam yang tidak pernah
            # ada. Mesin ini berhenti alih-alih membayarnya; validasi
            # run menolak konfigurasinya lebih dulu, dan penjagaan di
            # sini yang memastikan tidak ada jalan memutarinya.
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="overtime_tier_overlap",
                message=(
                    "Rentang tingkat pada Overtime Group ini bertumpang "
                    f"tindih — {overlapped} jam terhitung lebih dari "
                    "sekali. Perbaiki batas tingkatnya."
                ),
            )
            return None, ""

        if uncovered > ZERO:
            # Lubang di antara tingkat, atau tingkat teratas yang
            # berbatas sementara jamnya melewati batas itu. Sisanya
            # **tidak** dibayar dengan pengali karangan.
            result.add_finding(
                level=PayrollFindingLevel.ERROR,
                code="overtime_tier_gap",
                message=(
                    f"{uncovered} jam lembur tidak tercakup tingkat "
                    "mana pun pada Overtime Group ini. Lengkapi "
                    "rentang tingkatnya."
                ),
            )
            return None, ""

        # Bagian yang sama digabung supaya keterangannya tetap terbaca
        # untuk lembur harian yang polanya berulang.
        merged: dict[tuple, Decimal] = {}

        for hours, multiplier in parts:
            merged[multiplier] = merged.get(multiplier, ZERO) + hours

        note = " + ".join(
            f"{plain(hours)} jam x {plain(multiplier)}"
            for multiplier, hours in sorted(merged.items())
        )

        label = (
            "per hari"
            if basis == OvertimeTierBasis.DAILY
            else "total sebulan"
        )

        return weighted, f"{note} (tingkat {label})"

    @staticmethod
    def _spread_over_tiers(hours: Decimal, tiers):
        """
        Menyusun `hours` jam ke dalam tingkat, dari bawah ke atas.

        Mengembalikan `(jam_berbobot, [(jam, pengali)], jam_tercakup)`.

        Yang dikembalikan **jam tercakup**, bukan sisanya, karena
        pemanggil butuh membedakan dua kegagalan yang berbeda: tercakup
        kurang dari jamnya berarti ada lubang antar-tingkat, tercakup
        lebih berarti rentangnya bertumpang tindih dan satu jam
        terhitung dua kali.

        Jam pecahan disusun apa adanya: 2,5 jam dengan tingkat pertama
        0-1 menghasilkan 1 jam di tingkat pertama dan 1,5 jam di
        tingkat berikutnya. Tidak ada pembulatan ke 30 menit atau ke
        jam penuh — modul sumber tidak punya aturan itu, dan
        menciptakannya di sini berarti membayar orang untuk jam yang
        tidak pernah tercatat.
        """
        weighted = ZERO
        parts: list[tuple] = []
        covered = ZERO

        for tier in tiers:
            lower = Decimal(tier.hour_from or 0)

            if hours <= lower:
                continue

            upper = (
                Decimal(tier.hour_to)
                if tier.hour_to is not None
                else hours
            )

            slice_hours = min(hours, upper) - lower

            if slice_hours <= ZERO:
                continue

            multiplier = Decimal(tier.multiplier or 0)

            weighted += slice_hours * multiplier
            parts.append((slice_hours, multiplier))
            covered += slice_hours

        return weighted, parts, covered

    @classmethod
    def _input_earnings(cls, data: CalculationInput, result: CalculationResult) -> None:
        cls._inputs_for_side(
            data=data,
            result=result,
            side=PayrollComponentType.EARNING,
            base_sequence=600,
        )

    # ------------------------------------------------------------------
    # Deduction
    # ------------------------------------------------------------------

    @classmethod
    def _deductions(cls, data: CalculationInput, result: CalculationResult) -> None:
        lines = list(data.deduction_lines)

        if data.bpjs_lines_provider is not None:
            lines.extend(
                data.bpjs_lines_provider(
                    earnings=[
                        component
                        for component in result.components
                        if component.component_type
                        == PayrollComponentType.EARNING
                    ],
                    add_finding=result.add_finding,
                ),
            )

        for index, line in enumerate(lines, start=1):
            if line.basis == PayrollBasis.PPH21_PROGRESSIVE:
                # Ditunda ke `_tax()`: dasarnya baru lengkap setelah
                # seluruh potongan yang mengurangi pajak dihitung.
                continue

            if (
                line.basis in EARNINGS_REDUCTION_BASES
                and not getattr(line, "is_employer_cost", False)
            ):
                # Sudah dikerjakan `_absence_reductions()` sebelum
                # penghasilan ditutup — keputusan #2. Dibiarkan lewat
                # di sini berarti hari yang sama mengurangi gaji dua
                # kali: sekali dari sisi penghasilan, sekali sebagai
                # potongan.
                #
                # Baris yang ditandai beban perusahaan tetap lewat
                # jalur lama: ia tidak pernah memotong pegawai, jadi
                # tidak ada penghasilan yang perlu dikurangi.
                continue

            if cls._switched_off(line.basis, data):
                # Saklar kebijakan mematikan **seluruh jalur** potongan
                # itu, komponen master sekalipun. Kalau tidak, kalimat
                # "perusahaan ini tidak memotong absen" jadi dusta:
                # saklarnya mati tapi baris Deduction Template yang
                # basisnya per hari alpa tetap memotong, dan tidak ada
                # satu layar pun yang memperlihatkan pertentangannya.
                continue

            amount, base, note = cls._evaluate(
                data=data,
                result=result,
                basis=line.basis,
                unit_amount=Decimal(line.amount or 0),
                rate=Decimal(line.rate or 0),
                code=line.code,
                minimum_base=getattr(line, "minimum_base", None),
                maximum_base=getattr(line, "maximum_base", None),
                resolved_base=getattr(line, "resolved_base", None),
                resolved_base_note=getattr(line, "base_note", ""),
            )

            # Penjagaan yang sama seperti tunjangan, dan alasannya
            # sama: basis per hari nilainya sudah mengandung harinya.
            # Potongan cicilan 50.000 x hari alpa yang diprorata lagi
            # menagih pegawai setengah dari yang seharusnya.
            if cls._proration_applies(
                basis=line.basis,
                is_prorated=line.is_prorated,
                data=data,
            ):
                raw = amount
                amount = money(cls._prorate(amount, data))
                note = f"{note}; {cls._proration_note(data, raw)}".strip("; ")

            amount = cls._clamp(
                amount,
                minimum=getattr(line, "minimum_amount", None),
                maximum=getattr(line, "maximum_amount", None),
            )

            employer_cost = bool(getattr(line, "is_employer_cost", False))

            result.components.append(
                ComponentResult(
                    component_type=(
                        PayrollComponentType.EMPLOYER_CONTRIBUTION
                        if employer_cost
                        else PayrollComponentType.DEDUCTION
                    ),
                    # Dibaca dari barisnya, bukan ditanam. Baris yang
                    # datang dari lapisan kebijakan (BPJS) menyebut
                    # sumbernya sendiri; yang tidak menyebut apa-apa
                    # tetap baris Deduction Template seperti sebelumnya.
                    source=getattr(
                        line,
                        "source",
                        PayrollComponentSource.DEDUCTION_TEMPLATE,
                    ),
                    code=line.code,
                    name=line.name,
                    basis=line.basis,
                    base_amount=base,
                    rate=Decimal(line.rate or 0),
                    quantity=cls._quantity_for(data, line.basis),
                    amount=amount,
                    sequence=line.sequence or (index + 1),
                    # Dipaksa mati, bukan disalin. Validasi master sudah
                    # menolak pasangan ini, tapi baris lama yang
                    # terlanjur tersimpan tidak lewat sana lagi — dan
                    # yang lolos di sini mengurangi pajak pegawai
                    # dengan iuran yang tidak pernah dipotong darinya.
                    reduces_taxable=(
                        False if employer_cost else line.reduces_taxable
                    ),
                    is_prorated=line.is_prorated,
                    reference_type=getattr(
                        line,
                        "reference_type",
                        "payroll.deduction_template_line",
                    ),
                    reference_id=str(line.pk),
                    calculation_note=note,
                ),
            )

    @staticmethod
    def _switched_off(basis: str, data: CalculationInput) -> bool:
        """
        Basis ini dimatikan kebijakan perusahaan?

        Dipakai dua tempat — komponen master dan potongan otomatis —
        supaya satu saklar berarti satu hal di seluruh mesin hitung.

        Dasar **harian** mematikan dua-duanya tanpa syarat, dan itu
        bukan pilihan tenant melainkan aritmetika: hari yang tidak
        dibayar sudah tidak membentuk upah, jadi potongan apa pun di
        atasnya memotong hari yang sama dua kali. Komponen master yang
        berbasis hari alpa ikut mati di sini, kalau tidak tenant yang
        sudah menulis potongannya sendiri akan tetap kena.
        """
        if basis == PayrollBasis.PER_ABSENT_DAY:
            return data.pay_basis == PayrollPayBasis.DAILY or not data.deduct_absence

        if basis == PayrollBasis.PER_UNPAID_LEAVE_DAY:
            return (
                data.pay_basis == PayrollPayBasis.DAILY
                or not data.deduct_unpaid_leave
            )

        return False

    @classmethod
    def _absence_reductions(
        cls,
        data: CalculationInput,
        result: CalculationResult,
    ) -> None:
        """
        Alpa dan cuti tidak dibayar — **gaji yang tidak pernah
        terbentuk** (Business Decision #2).

        Barisnya tetap komponen `deduction` bermagnitudo positif, sama
        seperti sebelum keputusan ini: mesin ini menyimpan potongan
        sebagai magnitudo dan membiarkan agregasi yang menentukan
        arahnya. Yang berubah **agregasinya** —
        `_settle_earnings()` mengurangkannya dari gross dan taxable,
        `_settle_totals()` mengeluarkannya dari `total_deduction`.
        Sekali dikurangkan, tidak dua kali, dan `net_pay` tidak
        bergeser satu rupiah pun.

        Tetap **dua komponen, dua sumber, dua angka**. Dijumlahkan jadi
        satu "pengurang ketidakhadiran" akan membuat pegawai yang
        membantah satu hari alpa harus membantah seluruh angkanya, dan
        HR tidak punya cara menunjukkan bagian mana yang datang dari
        absensi dan bagian mana dari dokumen cuti.

        Empat hal yang dijaga di sini:

        1. **Sekali rounding.** Uangnya dihitung dari hari langsung
           (`gaji × hari / pembagi`), bukan dari nilai sehari yang sudah
           dibulatkan ke rupiah. 10.000.000 / 30 = 333.333,33 dikali 3
           menghasilkan 999.999,99 — satu rupiah yang hilang tanpa sebab
           dan yang besarnya berubah mengikuti jumlah harinya.
        2. **Pembagi potongan, bukan pembagi prorata.** Keduanya
           kebijakan yang terpisah; yang dipakai di sini
           `deduction_base_days`.
        3. **Komponen master menang.** Tenant yang sudah mengonfigurasi
           potongan ketidakhadirannya sendiri di Deduction Template
           tidak boleh kena kurang dua kali. Barisnya tetap ditulis di
           layar Deduction Template — yang berubah cuma di sisi mana
           mesin hitung menaruh hasilnya.
        4. **Prorata masa kerja tidak dikenakan lagi.** Nilainya sudah
           mengandung jumlah harinya; mengalikannya dengan faktor
           prorata memotong hari yang sama untuk kedua kalinya.
        5. **Kontrak tanda tidak disentuh.** Angkanya positif, dan
           tidak ada satu pun baris di mesin ini yang berubah tandanya
           karena keputusan #2.

        Yang **tidak** dikerjakan di sini: mengurangi dua kali untuk
        satu tanggal yang berstatus alpa sekaligus cuti tidak dibayar.
        Itu sudah diselesaikan di `PayrollSourceService` — dokumen cuti
        menutup tanggalnya, dan angka `absent_days` yang sampai ke sini
        sudah bersih. Mesin ini tidak mengenal tanggal, cuma jumlah.
        Cuti **dibayar** tidak pernah sampai ke sini sama sekali.
        """
        if data.pay_basis == PayrollPayBasis.DAILY:
            # Dasar harian tidak punya pengurang ketidakhadiran sama
            # sekali. Hari alpa dan hari cuti tidak dibayar sudah tidak
            # membentuk upah di `_daily_wage`; menguranginya lagi di
            # sini berarti satu hari tidak masuk menghapus dua hari
            # upah. Harinya tetap tercatat di barisnya dan tetap
            # disebut di keterangan upahnya.
            cls._settle_attendance_reductions(result)
            return

        handled_bases = cls._master_absence_reductions(data, result)

        base_days = Decimal(data.deduction_base_days or 0) or Decimal(
            data.divisor_days or 0,
        )

        method = data.deduction_method_label or data.deduction_method

        pairs = (
            (
                data.unpaid_leave_days,
                data.deduct_unpaid_leave,
                PayrollBasis.PER_UNPAID_LEAVE_DAY,
                "UNPAID-LEAVE",
                "Unpaid Leave",
                PayrollComponentSource.LEAVE,
                700,
            ),
            (
                data.absent_days,
                data.deduct_absence,
                PayrollBasis.PER_ABSENT_DAY,
                "ABSENT",
                "Absence Deduction",
                PayrollComponentSource.ATTENDANCE,
                710,
            ),
        )

        for days, enabled, basis, code, name, source, sequence in pairs:
            if not days or basis in handled_bases:
                continue

            if not enabled:
                # Kebijakan perusahaan memang mematikannya. Harinya
                # tetap tercatat di barisnya — "tidak dikurangi" dan
                # "tidak pernah terjadi" harus tetap bisa dibedakan.
                # Komponen master dengan basis yang sama sudah disaring
                # lebih dulu, jadi mematikan saklar benar-benar
                # mematikan jalurnya.
                continue

            if base_days <= ZERO:
                result.add_finding(
                    level=PayrollFindingLevel.WARNING,
                    code="deduction_base_missing",
                    message=(
                        f"Ada {days} hari yang seharusnya mengurangi "
                        f"gaji ({name}), tapi pembagi harinya nol. "
                        "Pengurangnya dihitung nol."
                    ),
                )
                continue

            # Satu pembulatan, di akhir.
            amount = money(Decimal(data.basic_salary) * days / base_days)

            # Nilai sehari hanya untuk dibaca orang; yang dipakai
            # menghitung tetap rumus di atas.
            daily_rate = (
                Decimal(data.basic_salary) / base_days
            ).quantize(CENT, rounding=ROUND_HALF_UP)

            result.components.append(
                ComponentResult(
                    # Barisnya **tidak berubah bentuk**: tetap
                    # potongan, tetap besaran positif. Seluruh mesin
                    # ini menyimpan potongan sebagai magnitudo dan
                    # membiarkan agregasi yang memutuskan arahnya;
                    # membalik tandanya di satu jalur saja membuat dua
                    # aturan hidup berdampingan tanpa ada yang
                    # menyebutnya, dan baris lama di database jadi
                    # tidak sebanding dengan baris baru.
                    #
                    # Yang membuatnya "mengurangi penghasilan" bukan
                    # tandanya melainkan `_settle_earnings()` dan
                    # `_settle_totals()`, yang membaca
                    # `EARNINGS_REDUCTION_BASES`.
                    component_type=PayrollComponentType.DEDUCTION,
                    source=source,
                    code=code,
                    name=name,
                    basis=basis,
                    base_amount=money(data.basic_salary),
                    rate=daily_rate,
                    quantity=days,
                    amount=amount,
                    sequence=sequence,
                    # Ditulis sebagai pecahan, bukan "hari x tarif":
                    # 3 x 333.333,33 = 999.999,99, bukan 1.000.000, dan
                    # keterangan yang tidak menghasilkan angkanya
                    # sendiri lebih buruk daripada tidak ada. Tarif
                    # sehari tetap ikut disebut karena itu yang dicari
                    # orang, tapi sebagai keterangan, bukan sebagai
                    # langkah perhitungan.
                    calculation_note=(
                        f"{days} dari {base_days} hari x "
                        f"{money(data.basic_salary)}"
                        f"{f' ({method})' if method else ''}"
                        f"; setara {daily_rate}/hari"
                    ),
                ),
            )

        cls._settle_attendance_reductions(result)

    @classmethod
    def _master_absence_reductions(
        cls,
        data: CalculationInput,
        result: CalculationResult,
    ) -> set:
        """
        Baris Deduction Template yang basisnya alpa / cuti tidak
        dibayar, dikerjakan di sisi penghasilan.

        Dipisah dari `_deductions()` karena urutannya berubah: hasilnya
        harus sudah ada **sebelum** penghasilan ditutup, sementara
        potongan lain justru butuh penghasilan yang sudah tertutup.

        Mengembalikan himpunan basis yang sudah tertangani, supaya
        pengurang otomatis tidak menambahkan yang kedua di atasnya.
        """
        handled: set = set()

        for index, line in enumerate(data.deduction_lines, start=1):
            if line.basis not in EARNINGS_REDUCTION_BASES:
                continue

            if getattr(line, "is_employer_cost", False):
                # Beban perusahaan tidak pernah memotong pegawai, jadi
                # tidak ada penghasilan yang perlu dikurangi. Tetap
                # lewat jalur lama di `_deductions()`.
                continue

            if cls._switched_off(line.basis, data):
                # Saklar kebijakan mematikan **seluruh jalur**, komponen
                # master sekalipun. Kalau tidak, kalimat "perusahaan ini
                # tidak memotong absen" jadi dusta: saklarnya mati tapi
                # baris Deduction Template yang basisnya per hari alpa
                # tetap mengurangi, dan tidak ada satu layar pun yang
                # memperlihatkan pertentangannya.
                continue

            handled.add(line.basis)

            amount, base, note = cls._evaluate(
                data=data,
                result=result,
                basis=line.basis,
                unit_amount=Decimal(line.amount or 0),
                rate=Decimal(line.rate or 0),
                code=line.code,
                minimum_base=getattr(line, "minimum_base", None),
                maximum_base=getattr(line, "maximum_base", None),
            )

            # Basis per hari nilainya sudah mengandung harinya.
            # Potongan 50.000 x hari alpa yang diprorata lagi menagih
            # pegawai setengah dari yang seharusnya. Penjagaannya sama
            # dengan tunjangan, dan alasannya sama.
            if cls._proration_applies(
                basis=line.basis,
                is_prorated=line.is_prorated,
                data=data,
            ):
                raw = amount
                amount = money(cls._prorate(amount, data))
                note = f"{note}; {cls._proration_note(data, raw)}".strip("; ")

            amount = cls._clamp(
                amount,
                minimum=getattr(line, "minimum_amount", None),
                maximum=getattr(line, "maximum_amount", None),
            )

            result.components.append(
                ComponentResult(
                    # Sama seperti jalur otomatis: bentuk barisnya
                    # persis seperti sebelum keputusan #2.
                    component_type=PayrollComponentType.DEDUCTION,
                    source=getattr(
                        line,
                        "source",
                        PayrollComponentSource.DEDUCTION_TEMPLATE,
                    ),
                    code=line.code,
                    name=line.name,
                    basis=line.basis,
                    base_amount=base,
                    rate=Decimal(line.rate or 0),
                    quantity=cls._quantity_for(data, line.basis),
                    amount=amount,
                    sequence=line.sequence or (index + 1),
                    # Dipaksa mati. Pengurangnya **sudah** keluar dari
                    # `taxable_earning` di `_settle_earnings()`;
                    # membiarkan baris ini ikut jadi pengurang pajak di
                    # `_tax()` berarti hari yang sama menurunkan dasar
                    # pajak dua kali. Butir 5 keputusan #2.
                    reduces_taxable=False,
                    is_prorated=line.is_prorated,
                    reference_type=getattr(
                        line,
                        "reference_type",
                        "payroll.deduction_template_line",
                    ),
                    reference_id=str(line.pk),
                    calculation_note=note,
                ),
            )

        return handled

    @staticmethod
    def _settle_attendance_reductions(result: CalculationResult) -> None:
        """
        Total per sumber, dibaca dari basis komponennya.

        Dijumlahkan dari `basis`, bukan dari kode yang dibuat method di
        atas, supaya tenant yang memakai komponen master sendiri tetap
        mendapat angka yang benar di kolom auditnya — pertanyaannya
        "berapa yang hilang karena alpa", bukan "berapa isi komponen
        bernama ABSENT".

        Besaran positif, persis seperti sebelum keputusan #2 — dan
        kolomnya tidak diganti nama. `absence_deduction` /
        `unpaid_leave_deduction` di `PayrollRunEmployee` sudah dipakai
        laporan dan dashboard, dan keputusan #2 butir 6 memintanya
        tetap.
        """
        def total_for(basis: str) -> Decimal:
            return money(
                sum(
                    (
                        component.amount
                        for component in result.components
                        if component.component_type
                        == PayrollComponentType.DEDUCTION
                        and component.basis == basis
                    ),
                    ZERO,
                ),
            )

        result.absence_deduction = total_for(PayrollBasis.PER_ABSENT_DAY)
        result.unpaid_leave_deduction = total_for(
            PayrollBasis.PER_UNPAID_LEAVE_DAY,
        )

    @classmethod
    def _input_deductions(cls, data: CalculationInput, result: CalculationResult) -> None:
        cls._inputs_for_side(
            data=data,
            result=result,
            side=PayrollComponentType.DEDUCTION,
            base_sequence=800,
        )

    # ------------------------------------------------------------------
    # Pajak
    # ------------------------------------------------------------------

    @classmethod
    def _tax(cls, data: CalculationInput, result: CalculationResult) -> None:
        lines = [
            line
            for line in data.deduction_lines
            if line.basis == PayrollBasis.PPH21_PROGRESSIVE
        ]

        if not lines:
            return

        if not data.tax_brackets:
            result.add_finding(
                level=PayrollFindingLevel.WARNING,
                code="tax_bracket_missing",
                message=(
                    "Komponen PPh21 dikonfigurasi tapi tabel Tax "
                    "Bracket masih kosong. Pajak dihitung nol."
                ),
            )
            return

        # Dasar pajak bulanan: penghasilan kena pajak dikurangi iuran
        # yang memang mengurangi pajak (BPJS pegawai, dsb).
        reducers = sum(
            (
                component.amount
                for component in result.components
                if component.component_type == PayrollComponentType.DEDUCTION
                and component.reduces_taxable
            ),
            ZERO,
        )

        monthly_base = result.taxable_earning - reducers

        if monthly_base <= ZERO:
            return

        # Disetahunkan, dipotong PTKP, lalu dibagi dua belas lagi.
        # PTKP adalah angka tahunan; mencampurnya dengan penghasilan
        # bulanan menghasilkan pajak yang salah dua belas kali lipat.
        annual_base = monthly_base * Decimal("12")
        annual_taxable = annual_base - Decimal(data.non_taxable_income or 0)

        if annual_taxable <= ZERO:
            return

        annual_tax = cls._progressive(annual_taxable, data.tax_brackets)

        for index, line in enumerate(lines, start=1):
            amount = money(annual_tax / Decimal("12"))

            amount = cls._clamp(
                amount,
                minimum=getattr(line, "minimum_amount", None),
                maximum=getattr(line, "maximum_amount", None),
            )

            result.components.append(
                ComponentResult(
                    component_type=PayrollComponentType.DEDUCTION,
                    source=PayrollComponentSource.TAX,
                    code=line.code,
                    name=line.name,
                    basis=line.basis,
                    base_amount=money(monthly_base),
                    amount=amount,
                    sequence=line.sequence or (900 + index),
                    reference_type="payroll.deduction_template_line",
                    reference_id=str(line.pk),
                    calculation_note=(
                        f"PKP setahun {money(annual_taxable)} "
                        f"(bruto {money(annual_base)} - PTKP "
                        f"{money(data.non_taxable_income)}), "
                        f"pajak setahun {money(annual_tax)} / 12"
                    ),
                ),
            )

            result.tax_amount += amount

            # Satu baris PPh21 per template sudah cukup; kalau ada lebih
            # dari satu, yang berikutnya akan menghitung pajak yang sama
            # dua kali.
            break

    @staticmethod
    def _progressive(annual_taxable: Decimal, brackets) -> Decimal:
        total = ZERO

        for bracket in brackets:
            low = Decimal(bracket.income_from or 0)

            if annual_taxable <= low:
                break

            high = (
                Decimal(bracket.income_to)
                if bracket.income_to is not None
                else annual_taxable
            )

            slice_amount = min(annual_taxable, high) - low

            if slice_amount <= ZERO:
                continue

            total += slice_amount * Decimal(bracket.rate or 0) / Decimal("100")

        return money(total)

    # ------------------------------------------------------------------
    # Bahan bersama
    # ------------------------------------------------------------------

    @classmethod
    def _inputs_for_side(
        cls,
        *,
        data: CalculationInput,
        result: CalculationResult,
        side: str,
        base_sequence: int,
    ) -> None:
        for index, row in enumerate(data.inputs, start=1):
            if row.effective_side != side:
                continue

            amount = money(row.effective_amount)

            if not amount:
                continue

            result.components.append(
                ComponentResult(
                    component_type=side,
                    source=PayrollComponentSource.INPUT,
                    code=row.effective_code,
                    name=row.effective_name,
                    basis=PayrollBasis.FIXED,
                    rate=Decimal(row.rate or 0),
                    quantity=Decimal(row.quantity or 1),
                    amount=amount,
                    sequence=base_sequence + index,
                    is_taxable=(
                        row.is_taxable
                        if side == PayrollComponentType.EARNING
                        else False
                    ),
                    reference_type="payroll.payroll_input",
                    reference_id=str(row.pk),
                    calculation_note=row.get_input_type_display(),
                ),
            )

    @classmethod
    def _evaluate(
        cls,
        *,
        data: CalculationInput,
        result: CalculationResult,
        basis: str,
        unit_amount: Decimal,
        rate: Decimal,
        code: str,
        minimum_base=None,
        maximum_base=None,
        resolved_base=None,
        resolved_base_note="",
    ) -> tuple[Decimal, Decimal, str]:
        """
        Menerjemahkan satu basis jadi (nilai, dasar, keterangan).
        """
        percent = rate / Decimal("100")

        if basis == PayrollBasis.FIXED:
            return money(unit_amount), ZERO, ""

        if basis == PayrollBasis.PERCENT_OF_RESOLVED_BASE:
            # Dasarnya sudah disusun lapisan kebijakan; yang dikerjakan
            # di sini tetap sama dengan basis persentase lain —
            # menjepit plafon, mengalikan tarif, membulatkan sekali.
            # Komposisinya ikut ditulis di keterangan supaya "kenapa
            # dasarnya 7.500.000" dijawab barisnya sendiri.
            base = cls._bounded(
                money(resolved_base or ZERO), minimum_base, maximum_base,
            )

            note = f"{rate}% x {base}"

            if resolved_base_note:
                note = f"{note} ({resolved_base_note})"

            return money(base * percent), base, note

        if basis == PayrollBasis.PERCENT_OF_BASIC:
            base = cls._bounded(money(data.basic_salary), minimum_base, maximum_base)
            return money(base * percent), base, f"{rate}% x {base}"

        if basis == PayrollBasis.PERCENT_OF_GROSS:
            base = cls._bounded(result.gross_earning, minimum_base, maximum_base)
            return money(base * percent), base, f"{rate}% x {base}"

        if basis == PayrollBasis.PERCENT_OF_TAXABLE:
            base = cls._bounded(result.taxable_earning, minimum_base, maximum_base)
            return money(base * percent), base, f"{rate}% x {base}"

        quantity = cls._quantity_for(data, basis)

        if quantity is None:
            result.add_finding(
                level=PayrollFindingLevel.WARNING,
                code="basis_unsupported",
                message=(
                    f"Komponen {code} memakai basis '{basis}' yang tidak "
                    "dikenali mesin hitung. Nilainya dihitung nol."
                ),
            )
            return ZERO, ZERO, ""

        return (
            money(unit_amount * quantity),
            money(unit_amount),
            f"{quantity} x {money(unit_amount)}",
        )

    @staticmethod
    def _quantity_for(data: CalculationInput, basis: str):
        return {
            PayrollBasis.FIXED: ONE,
            PayrollBasis.PERCENT_OF_BASIC: ONE,
            PayrollBasis.PERCENT_OF_GROSS: ONE,
            PayrollBasis.PERCENT_OF_TAXABLE: ONE,
            PayrollBasis.PERCENT_OF_RESOLVED_BASE: ONE,
            PayrollBasis.PER_WORKING_DAY: data.working_days,
            PayrollBasis.PER_PAID_DAY: data.paid_days,
            PayrollBasis.PER_ATTENDANCE_DAY: data.attendance_days,
            PayrollBasis.PER_ABSENT_DAY: data.absent_days,
            PayrollBasis.PER_UNPAID_LEAVE_DAY: data.unpaid_leave_days,
            PayrollBasis.PER_OVERTIME_HOUR: data.overtime_hours,
        }.get(basis)

    @staticmethod
    def _bounded(value: Decimal, minimum, maximum) -> Decimal:
        if minimum is not None and value < Decimal(minimum):
            value = Decimal(minimum)

        if maximum is not None and value > Decimal(maximum):
            value = Decimal(maximum)

        return money(value)

    @staticmethod
    def _proration_note(data: CalculationInput, raw: Decimal) -> str:
        """
        Keterangan prorata yang **menghasilkan angkanya sendiri**.

        Ditulis sebagai pecahan hari, sama seperti `BASIC` dan potongan
        ketidakhadiran: 1.500.000 x 15/30 = 750.000 bisa dihitung ulang
        tangan. Faktornya ikut disebut karena itu yang dicocokkan orang
        antar-komponen, tapi bukan sebagai langkah perhitungan.
        """
        if data.proration_base_days > ZERO:
            return (
                f"prorata {data.working_days}/{data.proration_base_days} "
                f"hari dari {money(raw)} (faktor {data.proration_factor})"
            )

        return f"prorata faktor {data.proration_factor} dari {money(raw)}"

    @classmethod
    def _clamped(
        cls,
        value: Decimal,
        *,
        minimum,
        maximum,
    ) -> tuple[Decimal, str]:
        """
        `_clamp` yang ikut mengembalikan **alasannya**.

        Nilai yang dijepit adalah satu-satunya keadaan di mana angka
        akhir tidak bisa diturunkan dari kolom lain di baris itu. Tanpa
        keterangannya, tunjangan 10% yang terbit 500.000 sementara gaji
        pokoknya 8 juta terbaca seperti salah hitung.
        """
        clamped = cls._clamp(value, minimum=minimum, maximum=maximum)

        if minimum is not None and clamped > value:
            return clamped, f"dinaikkan ke minimum {money(minimum)}"

        if maximum is not None and clamped < value:
            return clamped, f"dijepit maksimum {money(maximum)}"

        return clamped, ""

    @staticmethod
    def _clamp(value: Decimal, *, minimum, maximum) -> Decimal:
        if minimum is not None and value < Decimal(minimum):
            value = Decimal(minimum)

        if maximum is not None and value > Decimal(maximum):
            value = Decimal(maximum)

        return money(value)

    # ------------------------------------------------------------------

    @staticmethod
    def _settle_allowances(result: CalculationResult) -> None:
        def total(taxable: bool) -> Decimal:
            return money(
                sum(
                    (
                        component.amount
                        for component in result.components
                        if component.source
                        == PayrollComponentSource.ALLOWANCE_TEMPLATE
                        and component.is_taxable is taxable
                    ),
                    ZERO,
                ),
            )

        result.taxable_allowance = total(True)
        result.non_taxable_allowance = total(False)

    @staticmethod
    def _earnings_reduction(result: CalculationResult) -> Decimal:
        """
        Gaji yang tidak pernah terbentuk — Business Decision #2.

        Barisnya tersimpan sebagai potongan bermagnitudo positif, sama
        seperti potongan lain; yang membuatnya berbeda **basisnya**,
        bukan tandanya. Dijumlahkan di satu tempat ini supaya
        `gross_earning`, `taxable_earning`, dan `total_deduction`
        membaca angka yang sama dan tidak bisa berbeda pendapat.
        """
        return money(
            sum(
                (
                    component.amount
                    for component in result.components
                    if component.component_type
                    == PayrollComponentType.DEDUCTION
                    and component.basis in EARNINGS_REDUCTION_BASES
                ),
                ZERO,
            ),
        )

    @classmethod
    def _settle_earnings(cls, result: CalculationResult) -> None:
        """
        Penghasilan yang **benar-benar terbentuk**.

        Hari alpa dan hari cuti tidak dibayar dikurangkan di sini, satu
        kali, dan tidak di tempat lain mana pun: `_settle_totals()`
        mengeluarkannya dari `total_deduction` supaya `net_pay` tidak
        menguranginya untuk kedua kalinya, dan `_tax()` tidak
        menghitungnya lagi karena barisnya `reduces_taxable=False`.

        Hasilnya `net_pay` tidak bergeser satu rupiah pun dibanding
        sebelum keputusan #2 — yang pindah cuma sisi tempat
        pengurangnya dibukukan.
        """
        reduction = cls._earnings_reduction(result)

        result.gross_earning = money(
            sum(
                (
                    component.amount
                    for component in result.components
                    if component.component_type == PayrollComponentType.EARNING
                ),
                ZERO,
            )
            - reduction,
        )

        result.taxable_earning = money(
            sum(
                (
                    component.amount
                    for component in result.components
                    if component.component_type == PayrollComponentType.EARNING
                    and component.is_taxable
                ),
                ZERO,
            )
            - reduction,
        )

    @classmethod
    def _settle_totals(cls, result: CalculationResult) -> None:
        cls._settle_earnings(result)
        cls._settle_allowances(result)

        # Pengurang ketidakhadiran **tidak** ikut: ia sudah keluar
        # dari `gross_earning`. Membiarkannya di sini berarti hari yang
        # sama memotong gaji dua kali — sekali dari penghasilan, sekali
        # dari potongan — dan `net_pay` menyusut tanpa satu baris pun
        # yang menjelaskannya. Butir 5 keputusan #2.
        result.total_deduction = money(
            sum(
                (
                    component.amount
                    for component in result.components
                    if component.component_type == PayrollComponentType.DEDUCTION
                ),
                ZERO,
            )
            - cls._earnings_reduction(result),
        )

        result.employer_contribution = money(
            sum(
                (
                    component.amount
                    for component in result.components
                    if component.component_type
                    == PayrollComponentType.EMPLOYER_CONTRIBUTION
                ),
                ZERO,
            ),
        )

        # Sengaja tidak memuat `employer_contribution`: yang diterima
        # pegawai tidak berubah karena perusahaan menyetor iuran atas
        # namanya.
        result.net_pay = money(result.gross_earning - result.total_deduction)
