"""
Kosakata bersama modul Payroll.

Ditaruh di satu file, bukan di masing-masing model, karena tiga pihak
membacanya dengan arti yang **harus** sama: baris konfigurasi di master
(`AllowanceTemplateLine` / `DeductionTemplateLine`), baris transaksi
(`PayrollInput`), dan mesin hitungnya (`PayrollCalculationService`).
Menyalinnya ke tiga tempat adalah cara membuat satu basis perhitungan
hidup di dua tempat dengan nama berbeda.
"""

from django.db import models


class PayrollPeriodStatus(models.TextChoices):
    """
    Keadaan satu periode payroll.

    Urutannya searah: DRAFT → PROCESSING → REVIEW → APPROVED →
    FINALIZED. Tidak ada jalan balik dari FINALIZED — koreksi sesudah
    itu lewat run bertipe CORRECTION, bukan dengan menyunting angka
    yang slipnya sudah terbit.
    """

    DRAFT = "draft", "Draft"
    PROCESSING = "processing", "Processing"
    REVIEW = "review", "Review"
    APPROVED = "approved", "Approved"
    FINALIZED = "finalized", "Finalized / Locked"


class PayrollRunStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PROCESSING = "processing", "Processing"
    REVIEW = "review", "Review"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"
    FINALIZED = "finalized", "Finalized / Locked"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class PayrollRunType(models.TextChoices):
    REGULAR = "regular", "Regular"
    OFF_CYCLE = "off_cycle", "Off Cycle"
    CORRECTION = "correction", "Correction"


class PayrollRunEmployeeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CALCULATED = "calculated", "Calculated"
    EXCLUDED = "excluded", "Excluded"
    ERROR = "error", "Error"
    FINALIZED = "finalized", "Finalized"


class PayrollComponentType(models.TextChoices):
    """
    Sisi mana satu komponen berdiri.

    `EMPLOYER_CONTRIBUTION` adalah **sumbu ketiga**, bukan varian
    potongan, dan itu disengaja. Seluruh penjumlahan di mesin hitung
    sudah menyaring `component_type` — `gross_earning` menjumlah
    EARNING, `total_deduction` menjumlah DEDUCTION, dasar pajak
    menjumlah DEDUCTION yang `reduces_taxable`. Beban perusahaan yang
    dititipkan sebagai DEDUCTION berpenanda boolean menuntut **setiap**
    penyaring itu ditambah "dan bukan beban perusahaan"; satu yang
    terlewat memotong gaji pegawai dengan iuran yang dibayar
    perusahaan, dan slipnya tetap terlihat masuk akal. Sebagai tipe
    tersendiri ia tidak pernah ikut terjumlah oleh kode yang belum tahu
    ia ada.

    Ia **tidak** mengurangi net dan **tidak** menambah gross:
    `Total Payroll Cost = gross_earning + employer_contribution`.
    """

    EARNING = "earning", "Earning"
    DEDUCTION = "deduction", "Deduction"
    EMPLOYER_CONTRIBUTION = "employer_contribution", "Employer Contribution"


#: Sisi yang boleh dipilih pada `PayrollInput`.
#:
#: Beban perusahaan sengaja **tidak** ada di sini. Input payroll adalah
#: nilai variabel per pegawai, dan mesin hitung hanya menyalurkan input
#: ke sisi earning atau deduction (`_inputs_for_side`). Sisi ketiga yang
#: boleh dipilih tapi tidak pernah dibaca akan hilang tanpa satu pun
#: pesan — dan yang memasukkannya menganggap angkanya sudah tercatat.
#: Iuran perusahaan dikonfigurasi di `DeductionTemplateLine`
#: (`is_employer_cost`), tempat porsi pegawainya juga tinggal.
EMPLOYEE_SIDE_COMPONENT_TYPES = [
    (PayrollComponentType.EARNING.value, PayrollComponentType.EARNING.label),
    (PayrollComponentType.DEDUCTION.value, PayrollComponentType.DEDUCTION.label),
]


class PayrollComponentSource(models.TextChoices):
    """
    Dari mana satu baris perhitungan berasal.

    Ini yang membuat hasil bisa diaudit tanpa menjalankan ulang
    mesinnya: satu baris slip selalu bisa menjawab "angka ini datang
    dari master yang mana, atau dari input siapa".
    """

    BASIC = "basic", "Basic Salary"
    ALLOWANCE_TEMPLATE = "allowance_template", "Allowance Template"
    DEDUCTION_TEMPLATE = "deduction_template", "Deduction Template"
    OVERTIME = "overtime", "Overtime"
    INPUT = "input", "Payroll Input"
    ATTENDANCE = "attendance", "Attendance"
    LEAVE = "leave", "Leave"
    TAX = "tax", "Tax"

    # Identitas BPJS yang authoritative. Sebelum ini BPJS hanya bisa
    # dipisahkan dengan mencocokkan kode komponen — cara yang bekerja
    # sampai ada tenant yang menamainya "Jamsostek", dan gagalnya diam:
    # angkanya tetap keluar, cuma masuk kotak yang salah.
    BPJS = "bpjs", "BPJS"


class PayrollBasis(models.TextChoices):
    """
    Cara satu komponen dihitung.

    **Basis, bukan rumus bebas.** Payroll dikonfigurasi orang HR lewat
    layar, dan ekspresi bebas berarti kesalahan ketik baru ketahuan saat
    slip terbit. Daftar tertutup ini bisa divalidasi di form.
    """

    FIXED = "fixed", "Fixed Amount"
    PERCENT_OF_BASIC = "percent_of_basic", "% of Basic Salary"
    PERCENT_OF_GROSS = "percent_of_gross", "% of Gross Earning"
    PERCENT_OF_TAXABLE = "percent_of_taxable", "% of Taxable Earning"
    PER_WORKING_DAY = "per_working_day", "Amount x Working Day"
    PER_PAID_DAY = "per_paid_day", "Amount x Paid Day"
    PER_ATTENDANCE_DAY = "per_attendance_day", "Amount x Attendance Day"
    PER_ABSENT_DAY = "per_absent_day", "Amount x Absent Day"
    PER_UNPAID_LEAVE_DAY = "per_unpaid_leave_day", "Amount x Unpaid Leave Day"
    PER_OVERTIME_HOUR = "per_overtime_hour", "Amount x Overtime Hour"
    PPH21_PROGRESSIVE = "pph21_progressive", "PPh21 Progressive"

    # Persentase atas dasar yang **dihitung lapisan kebijakan**, bukan
    # atas kolom yang ada di baris itu sendiri. Dipakai iuran yang
    # dasarnya komposisi beberapa komponen — BPJS yang pertama — dan
    # sengaja dinamai umum: yang membedakannya dari basis lain cuma
    # dari mana dasarnya datang, bukan program apa yang memakainya.
    #
    # Hanya boleh dipakai baris hasil resolusi. Baris master yang
    # memakainya tidak punya dasar yang dititipkan siapa pun, jadi
    # hasilnya nol — kegagalan diam yang ditolak `clean()` kedua model
    # baris.
    PERCENT_OF_RESOLVED_BASE = (
        "percent_of_resolved_base",
        "% of Resolved Base",
    )


# Basis yang **hanya** masuk akal untuk potongan. Dipakai `clean()`
# kedua model baris supaya konfigurasi yang mustahil ditolak di layar
# tempat ia ditulis, bukan saat payroll dihitung sebulan kemudian.
DEDUCTION_ONLY_BASES = frozenset(
    {
        PayrollBasis.PER_ABSENT_DAY,
        PayrollBasis.PER_UNPAID_LEAVE_DAY,
        PayrollBasis.PPH21_PROGRESSIVE,
        PayrollBasis.PERCENT_OF_RESOLVED_BASE,
        # Persentase atas gross/taxable **hanya** untuk potongan.
        # Sebagai tunjangan ia melingkar: gross belum terbentuk waktu
        # tunjangan dihitung, jadi hasilnya selalu nol — kegagalan yang
        # diam. Ditolak di layar tempat komponennya ditulis.
        PayrollBasis.PERCENT_OF_GROSS,
        PayrollBasis.PERCENT_OF_TAXABLE,
    },
)

EARNING_ONLY_BASES = frozenset(
    {
        PayrollBasis.PER_OVERTIME_HOUR,
    },
)


# Basis yang **mengurangi penghasilan**, bukan memotong sesudahnya
# (Business Decision #2).
#
# Hari alpa dan hari cuti tidak dibayar adalah gaji yang **tidak
# pernah menjadi hak** — bukan uang yang sudah menjadi hak pegawai lalu
# ditahan perusahaan. Bedanya terlihat begitu ada pertanyaan berikutnya:
# gross yang dilaporkan, dasar pajak, dan angka yang dibaca orang di
# baris "penghasilan" semuanya salah kalau hari yang tidak dijalani
# tetap dihitung sebagai penghasilan lalu dikurangi di kolom sebelah.
#
# **Bentuk barisnya tidak berubah.** Tetap dikonfigurasi di Deduction
# Template, tetap tersimpan sebagai komponen `deduction` bermagnitudo
# positif — kontrak tanda yang sama dengan seluruh potongan lain di
# mesin ini, dan baris lama di database tetap sebanding dengan baris
# baru. Membalik tandanya di satu jalur saja berarti dua aturan hidup
# berdampingan tanpa ada yang menyebutnya.
#
# Yang membacanya hanya dua tempat, dan keduanya agregasi:
# `_settle_earnings()` mengurangkannya dari gross dan taxable, lalu
# `_settle_totals()` mengeluarkannya dari `total_deduction` supaya
# tidak dikurangkan untuk kedua kalinya.
#
# `net_pay` karena itu tidak bergeser satu rupiah pun.
EARNINGS_REDUCTION_BASES = frozenset(
    {
        PayrollBasis.PER_ABSENT_DAY,
        PayrollBasis.PER_UNPAID_LEAVE_DAY,
    },
)

# Basis yang nilainya **sudah** hasil kali dengan jumlah hari atau jam
# yang benar-benar terjadi. Dibedakan karena satu aturan bergantung
# padanya: prorata masa kerja **tidak** boleh dikenakan lagi di atasnya.
#
# Tunjangan makan 25.000 x hari hadir pada pegawai yang masuk tanggal 16
# sudah menghitung sebelas hari yang ia benar-benar masuk. Mengalikannya
# lagi dengan faktor prorata 0,5 membuatnya dibayar 5,5 hari untuk
# sebelas hari kerja — potongan kedua yang tidak pernah diminta siapa
# pun dan tidak terbaca di satu layar pun.
#
# Yang diprorata hanya basis yang nilainya **bulanan**: FIXED dan
# PERCENT_*. Di situ faktornya memang satu-satunya yang tahu bahwa
# bulannya tidak dijalani penuh.
QUANTITY_BASES = frozenset(
    {
        PayrollBasis.PER_WORKING_DAY,
        PayrollBasis.PER_PAID_DAY,
        PayrollBasis.PER_ATTENDANCE_DAY,
        PayrollBasis.PER_ABSENT_DAY,
        PayrollBasis.PER_UNPAID_LEAVE_DAY,
        PayrollBasis.PER_OVERTIME_HOUR,
    },
)


# Basis yang angkanya diambil dari kolom `rate` (persen), bukan
# `amount`. Yang lain memakai `amount` sebagai nilai satuan.
PERCENT_BASES = frozenset(
    {
        PayrollBasis.PERCENT_OF_BASIC,
        PayrollBasis.PERCENT_OF_GROSS,
        PayrollBasis.PERCENT_OF_TAXABLE,
        PayrollBasis.PERCENT_OF_RESOLVED_BASE,
    },
)

#: Basis yang **hanya** boleh lahir dari lapisan kebijakan, tidak
#: pernah ditulis orang di layar master.
RESOLVER_ONLY_BASES = frozenset(
    {
        PayrollBasis.PERCENT_OF_RESOLVED_BASE,
    },
)


class BpjsDailyBasicMethod(models.TextChoices):
    """
    Cara membentuk dasar iuran pegawai **harian**.

    Pegawai harian tidak punya gaji pokok sebulan menurut kontrak —
    kolomnya memang kosong — jadi komposisi dasar yang hanya tahu
    "gaji pokok kontraktual" menghasilkan dasar nol untuk mereka.

    **Sistem tidak memilihkan.** Kedua cara di bawah lazim dan hasilnya
    berbeda jauh, persis seperti `PayrollDailyRateMethod` yang juga
    menolak memilihkan. Angka pengalinya **tidak** punya bawaan: 21, 25,
    dan 30 semuanya dipakai orang, dan yang benar ditentukan regulasi
    atau kebijakan yang harus diverifikasi — bukan oleh nilai bawaan
    yang kebetulan tertulis di kode.
    """

    #: Perilaku hari ini. Pegawai harian menghasilkan dasar nol, dan
    #: peringatan `bpjs_base_zero` yang membuatnya tidak diam.
    NONE = "none", "Tidak diatur"

    #: Upah sehari x pengali yang dikonfigurasi.
    DAILY_RATE_X_FACTOR = "daily_rate_x_factor", "Upah Harian x Pengali"

    #: Upah sehari x hari yang benar-benar dibayar pada periode itu.
    PAID_DAYS_X_DAILY_RATE = (
        "paid_days_x_daily_rate",
        "Hari Dibayar x Upah Harian",
    )


class PayrollInputType(models.TextChoices):
    """
    Jenis nilai transaksi yang dimasukkan per periode/pegawai.

    **Bukan definisi komponen.** Definisinya tetap di master
    (`AllowanceTemplateLine` / `DeductionTemplateLine`); yang disimpan di
    sini nilainya untuk satu periode. Jenis di bawah ini cuma
    mengelompokkan input supaya layar dan laporan bisa memisahkannya.
    """

    OVERTIME = "overtime", "Overtime"
    ALLOWANCE = "allowance", "Variable Allowance"
    INCENTIVE = "incentive", "Incentive / Bonus"
    DEDUCTION = "deduction", "Deduction"
    REIMBURSEMENT = "reimbursement", "Reimbursement"
    ADJUSTMENT = "adjustment", "Correction / Adjustment"
    UNPAID_LEAVE = "unpaid_leave", "Unpaid Leave"
    ATTENDANCE = "attendance", "Attendance Adjustment"


# Jenis input → sisi mana ia jatuh secara bawaan. Tetap bisa ditimpa
# per baris: koreksi (`ADJUSTMENT`) sah berada di kedua sisi.
INPUT_TYPE_DEFAULT_SIDE: dict[str, str] = {
    PayrollInputType.OVERTIME: PayrollComponentType.EARNING,
    PayrollInputType.ALLOWANCE: PayrollComponentType.EARNING,
    PayrollInputType.INCENTIVE: PayrollComponentType.EARNING,
    PayrollInputType.REIMBURSEMENT: PayrollComponentType.EARNING,
    PayrollInputType.ADJUSTMENT: PayrollComponentType.EARNING,
    PayrollInputType.DEDUCTION: PayrollComponentType.DEDUCTION,
    PayrollInputType.UNPAID_LEAVE: PayrollComponentType.DEDUCTION,
    PayrollInputType.ATTENDANCE: PayrollComponentType.DEDUCTION,
}


class PayrollInputStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"


class PayrollProrationMethod(models.TextChoices):
    """
    Cara gaji pokok sebulan dipecah jadi hak harian.

    Dipilih **per perusahaan**, bukan per pegawai: dua orang di satu
    perusahaan yang gaji sebulannya sama tidak boleh dibayar berbeda
    hanya karena masuk di bulan yang berbeda panjangnya.

    - `FIXED_30` — pembagi selalu 30. Nilai sehari sama sepanjang tahun,
      dan itu memang yang dicari sebagian perusahaan; konsekuensinya
      bulan 31 hari yang dijalani penuh tetap dibayar penuh karena
      faktor prorata dibatasi 1
    - `CALENDAR_DAYS` — pembagi jumlah hari kalender periode itu (30,
      31, 28, 29). Nilai sehari berubah tiap bulan, tapi sebulan penuh
      selalu tepat gaji sebulan
    - `WORKING_DAYS` — pembagi jumlah hari kerja pegawai pada periode
      itu, dibaca dari kalender kerja dan hari libur yang sudah ada
      (`WorkCalendar`, `Holiday`, atau roster). Bukan Senin–Jumat yang
      ditanam di kode
    """

    FIXED_30 = "fixed_30", "Fixed 30 Days"
    CALENDAR_DAYS = "calendar_days", "Calendar Days"
    WORKING_DAYS = "working_days", "Working Days"


# Perusahaan yang belum memilih apa pun. **Bukan kebijakan** — ini
# perilaku engine sebelum kebijakannya ada, dipertahankan supaya
# menambah layar konfigurasi tidak mengubah satu angka pun pada payroll
# yang sudah berjalan. Runnya membawa temuan WARNING yang menyebutnya,
# jadi "belum dipilih" kelihatan dan tidak menyamar jadi keputusan.
DEFAULT_PRORATION_METHOD = PayrollProrationMethod.CALENDAR_DAYS


class PayrollPayBasis(models.TextChoices):
    """
    Gaji orang ini dihitung **dari apa**.

    Bukan jenis kepegawaian, bukan golongan, bukan tempat kerja —
    Payroll sengaja tidak mengenal kategori-kategori itu. Yang
    dibutuhkan mesin hitung cuma satu pertanyaan: angka bulanan dipecah
    jadi hak harian (MONTHLY), atau upah dibentuk dari hari yang
    benar-benar dibayar (DAILY).

    `MONTHLY` adalah bawaan, dan itu **bukan** keputusan bisnis baru:
    seluruh perhitungan sebelum kebijakan ini ada memang bulanan, dan
    bawaan lain berarti payroll yang sudah berjalan berubah angkanya
    hanya karena sebuah tabel lahir.
    """

    MONTHLY = "monthly", "Bulanan"
    DAILY = "daily", "Harian"


class PayrollPolicyToggle(models.TextChoices):
    """
    Saklar yang punya keadaan ketiga: **belum diputuskan di sini**.

    Dipakai kebijakan kelompok untuk menimpa saklar perusahaan. Boolean
    biasa tidak cukup dan `null` pada `BooleanField` cuma memindahkan
    masalahnya ke layar: tidak ada widget yang bisa menampilkan tiga
    keadaan sebagai kotak centang, dan kotak centang kosong terbaca
    sebagai "tidak", bukan sebagai "ikut perusahaan".

    Bedanya menentukan uang: kebijakan yang **sengaja** mematikan
    prorata dan kebijakan yang **belum mengatur** prorata harus
    menghasilkan angka yang berbeda pada perusahaan yang menyalakannya.
    """

    INHERIT = "inherit", "Ikut kebijakan perusahaan"
    ON = "on", "Ya"
    OFF = "off", "Tidak"


class PayrollDailyRateMethod(models.TextChoices):
    """
    Upah sehari pegawai harian diambil dari mana.

    Dua-duanya dipakai di lapangan dan menghasilkan angka yang berbeda,
    jadi **tidak ada bawaan**: kebijakan harian yang belum memilih
    ditolak validasi, bukan diam-diam dihitung dengan salah satunya.

    - `ASSIGNMENT_RATE` — angka yang ditulis di `PayrollAssignment.
      daily_rate`, tempat kompensasi payroll yang sudah effective-dated
    - `FROM_MONTHLY` — gaji sebulan di assignment yang sama dibagi
      pembagi yang tertulis di kebijakan (25, 26, 30 — angkanya milik
      perusahaan)
    """

    ASSIGNMENT_RATE = "assignment_rate", "Tarif harian di Payroll Assignment"
    FROM_MONTHLY = "from_monthly", "Gaji sebulan dibagi pembagi"


class OvertimeTierBasis(models.TextChoices):
    """
    Jam lembur dihitung bertingkat **per apa**.

    Pertanyaan ini punya dua jawaban yang sama-sama dipakai di
    lapangan, dan keduanya menghasilkan angka yang jauh berbeda untuk
    pegawai yang sama: lembur 1 jam setiap hari selama empat hari
    seluruhnya masuk tarif jam pertama kalau tingkatnya dihitung per
    hari, tapi tiga dari empat jamnya masuk tarif jam berikutnya kalau
    dihitung dari total sebulan.

    Karena itu **tidak ada bawaan**. Perusahaan yang memakai tingkat
    harus menyatakan pilihannya; yang tidak menyatakannya ditolak
    validasi, bukan diam-diam dihitung dengan salah satunya.
    """

    DAILY = "daily", "Per hari lembur"
    MONTHLY = "monthly", "Total jam sebulan"


class PayrollFindingLevel(models.TextChoices):
    """
    ERROR mengunci Finalize; WARNING boleh dilanjutkan dengan
    acknowledgement. Pemisahan ini disengaja: daftar temuan yang
    semuanya menghalangi membuat orang berhenti membacanya.
    """

    ERROR = "error", "Error"
    WARNING = "warning", "Warning"


class PayslipStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
