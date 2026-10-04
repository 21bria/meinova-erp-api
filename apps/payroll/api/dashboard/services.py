"""
Angka Payroll Dashboard.

**Dashboard tidak menghitung payroll.** Tidak ada satu baris pun di file
ini yang menurunkan gaji, tarif, prorata, potongan, lembur, atau pajak;
seluruhnya menjumlahkan apa yang sudah tertulis di `PayrollRunEmployee`
dan `PayrollRunComponent` — hasil `PayrollCalculationService`, dibekukan
per run. Mesin hitung kedua di layar ringkasan adalah cara paling pasti
membuat dashboard dan slip gaji menyebut dua angka berbeda untuk orang
yang sama, dan yang salah tidak akan ketahuan sampai ada yang
membandingkannya.

Konsekuensi yang disengaja: **run yang sudah Finalized tidak bergerak**.
Barisnya tidak dihitung ulang dari master terbaru, karena tidak ada yang
dihitung ulang sama sekali. Kebijakan yang diganti bulan depan, gaji
yang naik, tarif harian yang dikoreksi — tidak satu pun menyentuh angka
run lama.

Dua lapis cakupan, dan keduanya wajib
-------------------------------------
`DataScopeService` menjawab "baris milik organisasi mana", persis dengan
peta yang dipakai `PayrollRunViewSet` dan `PayrollRunEmployeeViewSet`.
`EmployeeDataVisibility` menjawab "gaji siapa yang boleh dibaca akun
ini" lewat `EmployeeDataPolicy` kelompok `FIELD_PAYROLL` — lapis yang
sama yang menutup tab Payroll di kartu pegawai.

Keduanya dipasang di **satu** tempat (`lines()`), dan seluruh KPI,
chart, tabel, serta rincian dibangun dari sana. Itu sebabnya total di
kartu selalu cocok dengan isi tabel di bawahnya: keduanya menjumlahkan
queryset yang sama.

Kenapa KPI tidak membaca `PayrollRun.total_*`
---------------------------------------------
Kolom itu ada dan sudah benar — tapi ia dibekukan atas **seluruh**
pegawai run, tanpa mengenal siapa yang membacanya. Memakainya berarti
supervisor yang cuma boleh melihat satu departemen tetap membaca total
se-perusahaan di kartu KPI, sementara tabel di bawahnya menampilkan
tujuh orang. Selisih itu tidak berbunyi; ia cuma terbaca seperti
kesalahan hitung.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.accounts.scoping import DataScopeService
from apps.payroll.models import (
    EARNINGS_REDUCTION_BASES,
    PayrollComponentSource,
    PayrollComponentType,
    PayrollFindingLevel,
    PayrollPayBasis,
    PayrollPeriod,
    PayrollRun,
    PayrollRunComponent,
    PayrollRunEmployee,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
)
from apps.accounts.permissions import view_permission_for
from apps.payroll.scoping import scope_run_employees


ZERO = Decimal("0.00")

# Jumlah periode pada chart tren. Enam, bukan dua belas: yang dibaca
# orang payroll adalah "apakah bulan ini wajar dibanding beberapa bulan
# terakhir", dan dua belas titik di kartu selebar setengah layar
# membuat labelnya bertumpuk.
TREND_PERIODS = 6

# Baris tanpa unit organisasi tetap dihitung dan tetap punya nama.
# Membuangnya membuat jumlah baris rincian tidak pernah sama dengan KPI
# di atasnya, dan selisih tanpa sebab lebih buruk daripada satu baris
# bernama "(belum ditentukan)".
UNASSIGNED_LABEL = "(belum ditentukan)"

# Pegawai yang tidak membawa kebijakan **mengikuti** `PayrollSetting`
# perusahaannya — itu keadaan yang sah, bukan konfigurasi yang hilang.
# Ditulis berbeda dari `UNASSIGNED_LABEL` supaya keduanya tidak
# tertukar saat dibaca di kolom Kebijakan.
COMPANY_DEFAULT_LABEL = "Default Perusahaan"


# ----------------------------------------------------------------------
# Cakupan data per baris
# ----------------------------------------------------------------------
#
# Cakupan baris pegawai **tidak** ditulis di sini: `lines()` memanggil
# `apps.payroll.scoping.scope_run_employees`, peta yang sama persis yang
# dipakai `PayrollRunEmployeeViewSet` dan rekap
# `payroll-runs/<id>/summary/`. Sebelumnya salinannya ada di file ini,
# dan dua salinan yang harus tetap sepakat adalah cara paling pasti
# membuat satu layar menyaring lebih longgar dari yang lain tanpa ada
# yang menyadarinya.
#
# Dua peta di bawah menyaring **dokumen**, bukan baris gaji, dan masih
# disalin persis dari `data_scope` viewset masing-masing. Kalau salah
# satu diubah, yang di sini harus ikut — kalau tidak, daftar run dan
# periode di filter berhenti cocok dengan layarnya.

RUN_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "department": "department",
    "section": "section",
}

PERIOD_SCOPE = {"company": "company"}


# ----------------------------------------------------------------------
# Komposisi payroll
# ----------------------------------------------------------------------
#
# Kategori ditentukan pasangan (`component_type`, `source`) yang memang
# ditulis mesin hitung di tiap baris komponen — **bukan** dari kode atau
# nama komponennya. `if "BPJS" in code` bekerja sampai ada tenant yang
# menamainya "Jamsostek", dan kegagalannya diam: angkanya tetap keluar,
# cuma masuk kotak yang salah.
#
# Kategori baru karena itu tidak boleh ditambahkan tanpa
# mengeluarkannya dari kategori lain, kalau tidak jumlahnya berhenti
# cocok.
#
# Sejak Business Decision #2 ada **tiga** kelompok di grafik ini, bukan
# dua, dan ketiganya rekonsiliasi begini:
#
#     Gaji Pokok + Tunjangan + Lembur + Input Variabel
#       = gross sebelum pengurang
#
#     ... dikurangi "Ketidakhadiran"
#       = gross_earning (kartu Gross Payroll)
#
#     Potongan + PPh21
#       = total_deduction (kartu Total Deduction)
#
#     net_pay = gross_earning - total_deduction
#
# "Ketidakhadiran" **bukan** potongan biasa: hari yang tidak dijalani
# adalah gaji yang tidak pernah terbentuk, bukan uang yang ditahan.
# Karena itu ia tidak boleh ikut di kotak `Potongan` — kalau ikut,
# `Potongan` berhenti sama dengan `total_deduction` dan grafiknya
# menagih pegawai dua kali di mata orang yang membacanya.
#
# Juringnya tetap **positif**. Menggambarnya negatif menghasilkan
# juring yang tidak terbaca sebagai apa pun.
#
# Yang belum ada: **BPJS**. Hari ini ia cuma `DeductionTemplateLine`
# ber-kode "BPJS-*", dan tidak ada `PayrollComponentSource` untuknya —
# memisahkannya berarti mencocokkan nama. Begitu #5 memberinya sumber
# sendiri, satu baris di bawah ini cukup.
COMPOSITION = [
    (
        "Gaji Pokok",
        PayrollComponentType.EARNING,
        (PayrollComponentSource.BASIC,),
    ),
    (
        "Tunjangan",
        PayrollComponentType.EARNING,
        (PayrollComponentSource.ALLOWANCE_TEMPLATE,),
    ),
    (
        "Lembur",
        PayrollComponentType.EARNING,
        (PayrollComponentSource.OVERTIME,),
    ),
    (
        "Input Variabel",
        PayrollComponentType.EARNING,
        (PayrollComponentSource.INPUT,),
    ),
    (
        "Potongan",
        PayrollComponentType.DEDUCTION,
        (
            PayrollComponentSource.DEDUCTION_TEMPLATE,
            PayrollComponentSource.INPUT,
            PayrollComponentSource.ATTENDANCE,
            PayrollComponentSource.LEAVE,
            PayrollComponentSource.BASIC,
            PayrollComponentSource.OVERTIME,
        ),
    ),
    # PPh21 berdiri sendiri karena sumbernya memang berdiri sendiri
    # (`PayrollComponentSource.TAX`), bukan karena namanya mengandung
    # "pajak". Perhitungannya sendiri masih PROVISIONAL (#6) dan tidak
    # disentuh dari sini.
    (
        "PPh21",
        PayrollComponentType.DEDUCTION,
        (PayrollComponentSource.TAX,),
    ),
]

# Kelompok ketiga, di luar `COMPOSITION` karena ia tidak dipilih lewat
# pasangan (`component_type`, `source`) melainkan lewat **basis**
# (`EARNINGS_REDUCTION_BASES`) — sumbernya bisa `attendance`, `leave`,
# maupun `deduction_template` kalau tenant menulis pengurangnya sendiri.
EARNINGS_REDUCTION_LABEL = "Ketidakhadiran"


# ----------------------------------------------------------------------
# Tahapan run
# ----------------------------------------------------------------------
#
# Dibaca dari **stempel waktu dokumennya sendiri**, bukan dari mesin
# status kedua yang ditulis khusus untuk dashboard. Satu tahap selesai
# kalau jejaknya ada; yang belum punya jejak berarti belum terjadi.
# Karena itu run yang melompat (ditolak lalu diajukan ulang) tetap
# tergambar benar tanpa aturan tambahan.
#
# `PayrollRunStatus` punya REJECTED dan CANCELLED yang bukan tahap
# melainkan simpangan; keduanya ditambahkan sebagai baris terakhir saat
# terjadi, bukan disisipkan ke dalam urutan.
STAGES = [
    ("draft", "Draft", None, None),
    ("generated", "Pegawai Dibentuk", None, "generated"),
    ("calculated", "Dihitung", "calculated_at", "calculated"),
    ("submitted", "Diajukan", "submitted_at", None),
    ("approved", "Disetujui", "approved_at", None),
    ("finalized", "Final / Terkunci", "finalized_at", "finalized"),
]


# Judul temuan per kode validasi.
#
# Yang dipakai membuat "2 pegawai belum punya Payroll Assignment" dari
# dua pesan yang masing-masing menyebut nama orangnya. Pesan aslinya
# tidak dibuang — ia jadi keterangan di bawah judulnya.
#
# Kode yang tidak terdaftar **tidak hilang**: judulnya jatuh ke pesan
# temuan pertama apa adanya. Itu yang membuat temuan baru di
# `PayrollValidationService` langsung muncul di sini tanpa perlu
# didaftarkan lebih dulu — daftar yang harus diurus dua tempat adalah
# daftar yang cepat atau lambat kehilangan satu baris.
FINDING_TITLES = {
    # --- tingkat run --------------------------------------------------
    "no_employee": "Run belum punya pegawai",
    "proration_policy_missing": "Kebijakan prorata belum dipilih",
    "attendance_deduction_policy_missing": (
        "Kebijakan potongan ketidakhadiran belum dipilih"
    ),
    "duplicate_finalized": "Sudah dibayar di run lain",

    # --- kebijakan ----------------------------------------------------
    "policy_inactive": "Payroll Policy tidak aktif",
    "policy_company_mismatch": "Payroll Policy milik perusahaan lain",
    "daily_rate_method_missing": "Cara upah harian belum dipilih",
    "daily_rate_divisor_missing": "Pembagi upah harian belum diisi",
    "daily_paid_leave_undecided": (
        "Aturan cuti dibayar (harian) belum dipilih"
    ),

    # --- konfigurasi pegawai ------------------------------------------
    "assignment_missing": "Payroll Assignment belum ada",
    "basic_salary_missing": "Gaji pokok belum ada",
    "daily_rate_missing": "Upah harian belum ada",
    "currency_missing": "Mata uang belum ada",
    "join_date_missing": "Tanggal masuk belum ada",

    # --- lembur -------------------------------------------------------
    "overtime_group_missing": "Overtime Group belum ada",
    "overtime_not_eligible": "Lembur tercatat pada yang tidak eligible",
    "overtime_divisor_missing": "Pembagi lembur belum diisi",
    "overtime_divisor_invalid": "Pembagi lembur tidak sah",
    "overtime_multiplier_invalid": "Pengali lembur tidak sah",
    "overtime_tier_basis_missing": "Basis tingkat lembur belum dipilih",
    "overtime_tier_gap": "Tingkat lembur berlubang",
    "overtime_tier_overlap": "Tingkat lembur bertumpang tindih",
    "overtime_tier_range_invalid": "Rentang tingkat lembur tidak sah",
    "overtime_tier_multiplier_invalid": "Pengali tingkat lembur tidak sah",
    "overtime_daily_hours_missing": "Rincian jam lembur per hari tidak ada",
    "overtime_hours_negative": "Jam lembur negatif",

    # --- hasil perhitungan --------------------------------------------
    "not_calculated": "Belum dihitung",
    "calculation_error": "Gagal dihitung",
    "calculation_failed": "Gagal dihitung",
    "basis_unsupported": "Basis komponen tidak dikenal",
    "deduction_base_missing": "Dasar potongan tidak ada",
    "attendance_missing": "Belum ada absensi pada periode ini",
    "tax_bracket_missing": "Bracket PPh21 belum diisi",
    "negative_net_pay": "Net Pay negatif",
    "zero_net_pay": "Net Pay nol",
}


def _amount(value) -> float:
    """
    Uang untuk **ditampilkan**, bukan untuk dihitung lagi.

    Dikembalikan sebagai float karena itu yang dibaca
    `formatDashboardValue` di frontend, dan seluruh angkanya sudah
    dibulatkan dua desimal jauh sebelum sampai ke sini — pembulatan
    kedua tidak terjadi di layar. Yang tidak boleh dilakukan adalah
    kebalikannya: menjumlahkan float lalu menyimpannya kembali sebagai
    angka payroll. Tidak ada jalan dari sini ke sana.
    """
    return float(value or ZERO)


def _ids(value) -> list[int]:
    """Nilai filter (satu atau bercentang banyak) jadi daftar id."""
    if value in (None, ""):
        return []

    if not isinstance(value, (list, tuple, set)):
        value = [value]

    result = []

    for item in value:
        text = str(item).strip()

        if text.isdigit():
            result.append(int(text))

    return result


def _single(value) -> int | None:
    found = _ids(value)

    return found[0] if found else None


class PayrollDashboardService:
    # ------------------------------------------------------------------
    # Queryset dasar
    # ------------------------------------------------------------------

    @staticmethod
    def _companies(context: dict) -> list[int]:
        return _ids(context.get("company"))

    @classmethod
    def periods(cls, context: dict):
        queryset = PayrollPeriod.objects.filter(is_deleted=False)

        companies = cls._companies(context)

        if companies:
            queryset = queryset.filter(company_id__in=companies)

        return DataScopeService.filter(
            queryset,
            PERIOD_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(PayrollPeriod),
        )

    @classmethod
    def runs(cls, context: dict):
        """
        Run yang boleh dibaca akun ini, sudah menyempit ke company yang
        dipilih di toolbar.

        Run yang dibatalkan ikut terbawa — "kenapa periode ini tidak
        ada angkanya" harus bisa dijawab dokumen yang membatalkannya,
        bukan oleh run yang menghilang dari daftar.
        """
        queryset = PayrollRun.objects.filter(is_deleted=False)

        companies = cls._companies(context)

        if companies:
            queryset = queryset.filter(company_id__in=companies)

        return DataScopeService.filter(
            queryset,
            RUN_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(PayrollRun),
        )

    @classmethod
    def lines(cls, context: dict):
        """
        Satu-satunya pintu ke angka payroll per pegawai.

        Dua lapis cakupan dipasang di sini dan **hanya** di sini; tiap
        widget membangun dirinya dari fungsi ini. Yang dikecualikan dari
        run (`is_excluded`) tidak ikut: barisnya sengaja tetap ada di
        dokumen supaya "kenapa si A tidak dibayar" punya jawaban, tapi
        ia bukan bagian dari angka yang dibayarkan.
        """
        queryset = PayrollRunEmployee.objects.filter(
            is_deleted=False,
            is_excluded=False,
        )

        companies = cls._companies(context)

        if companies:
            queryset = queryset.filter(company_id__in=companies)

        # Kedua lapis — `DataScopeService` dan `EmployeeDataPolicy`
        # kelompok Payroll — dipasang sekaligus oleh helper bersama,
        # bukan diulang di sini. Lapis kedua itu yang menutup tab
        # Payroll di kartu pegawai; tanpanya, angka yang tidak boleh
        # dibaca lewat `/api/payroll/payroll-run-employees/` tetap
        # terbaca sebagai bagian dari total di kartu KPI.
        return scope_run_employees(queryset, context.get("user"))

    # ------------------------------------------------------------------
    # Pemilihan periode & run
    # ------------------------------------------------------------------

    @classmethod
    def selection(cls, context: dict) -> dict:
        """
        Run dan periode yang sedang dibaca layar ini.

        Tidak ada yang di-hardcode: tanpa filter, yang dipilih adalah
        **periode terbaru yang punya run** dalam cakupan pemegang akun,
        lalu run terbaru di periode itu. Perusahaan, tahun, dan bulannya
        datang dari data, jadi tenant yang periodenya berjalan di 2031
        tetap membuka layar yang benar.

        Hasilnya disimpan di `context` — satu request menghitungnya
        sekali untuk sebelas widget.
        """
        cached = context.get("_selection")

        if cached is not None:
            return cached

        runs = cls.runs(context)
        periods = cls.periods(context)

        run = None
        period = None

        chosen_run = _single(context.get("payroll_run"))

        if chosen_run:
            run = runs.filter(pk=chosen_run).select_related(
                "period", "company",
            ).first()

            # Run yang disebut tapi **tidak ada dalam cakupan**:
            # kosong, bukan mundur ke run bawaan.
            #
            # Aturan umum dashboard adalah sebaliknya — satu query
            # param salah ketik jatuh ke bawaan, tidak mematikan
            # halaman (lihat `BaseDashboardAPIView.get_period`). Di
            # sini kebalikannya yang benar, dan bedanya soal uang:
            # periode tanggal yang salah ketik cuma menghasilkan
            # rentang bawaan yang tidak berbahaya, sementara run yang
            # salah ketik menampilkan **angka payroll run lain** di
            # bawah pemilih yang menyebut run yang diminta. Yang
            # membacanya tidak punya cara tahu ia sedang melihat
            # dokumen yang berbeda.
            #
            # Bukan penjagaan — cakupannya sudah ditutup `runs()` di
            # atas; ini soal tidak berdusta tentang dokumen mana yang
            # sedang dibaca.
            selection = {"run": run, "period": run.period if run else None}

            context["_selection"] = selection

            return selection

        chosen_period = _single(context.get("payroll_period"))

        if chosen_period:
            # Alasan yang sama: periode yang disebut tapi di luar
            # cakupan tidak mundur ke periode terbaru.
            period = periods.filter(pk=chosen_period).first()
        else:
            # Periode terbaru yang **benar-benar punya run** yang boleh
            # dibaca. Periode kosong yang baru dibuka bulan depan akan
            # selalu jadi yang terbaru, dan membukanya sebagai bawaan
            # berarti layar ini kosong tiap kali ada yang menyiapkan
            # periode berikutnya lebih awal.
            period = (
                periods
                .filter(runs__in=runs)
                .order_by("-start_date", "-id")
                .distinct()
                .first()
                or periods.order_by("-start_date", "-id").first()
            )

        if period is not None:
            run = (
                runs
                .filter(period=period)
                .select_related("period", "company")
                .order_by("-created_at", "-id")
                .first()
            )

        selection = {"run": run, "period": period}

        context["_selection"] = selection

        return selection

    @classmethod
    def run_of(cls, context: dict):
        return cls.selection(context)["run"]

    @classmethod
    def run_lines(cls, context: dict):
        """Baris pegawai pada run terpilih; kosong kalau tidak ada run."""
        run = cls.run_of(context)

        if run is None:
            return cls.lines(context).none()

        return cls.lines(context).filter(run=run)

    # ------------------------------------------------------------------
    # Agregat bersama
    # ------------------------------------------------------------------

    @classmethod
    def totals(cls, context: dict) -> dict:
        """
        Satu agregat untuk enam kartu KPI, dihitung sekali per request.

        Enam query terpisah untuk enam kartu yang menjumlahkan queryset
        yang sama persis adalah lima query yang tidak perlu — dan
        kelimanya melewati tabel yang sama.
        """
        cached = context.get("_totals")

        if cached is not None:
            return cached

        totals = cls.run_lines(context).aggregate(
            employees=Count("id"),
            gross=Sum("gross_earning"),
            deduction=Sum("total_deduction"),
            net=Sum("net_pay"),
            absence=Sum("absence_deduction"),
            unpaid=Sum("unpaid_leave_deduction"),
            employer=Sum("employer_contribution"),
        )

        context["_totals"] = totals

        return totals

    @classmethod
    def component_totals(cls, context: dict) -> dict:
        """
        Total komponen run terpilih, di-key `(component_type, source)`.

        Satu query untuk kartu Lembur **dan** chart komposisi. Keduanya
        bertanya hal yang sama ke tabel yang sama; menanyakannya dua
        kali cuma menggandakan biayanya.
        """
        cached = context.get("_component_totals")

        if cached is not None:
            return cached

        # `basis` ikut ditarik supaya pengurang ketidakhadiran bisa
        # dipisahkan dari potongan biasa — keduanya sama-sama baris
        # `deduction` bermagnitudo positif, dan yang membedakannya cuma
        # basisnya (Business Decision #2). Tetap satu query; yang
        # bertambah cuma jumlah baris yang dijumlahkan ulang di Python.
        rows = (
            PayrollRunComponent.objects
            .filter(
                is_deleted=False,
                run_employee__in=cls.run_lines(context),
            )
            .values("component_type", "source", "basis")
            .annotate(total=Sum("amount"))
        )

        totals: dict = {}
        reduction = ZERO

        for row in rows:
            amount = row["total"] or ZERO

            if (
                row["component_type"] == PayrollComponentType.DEDUCTION
                and row["basis"] in EARNINGS_REDUCTION_BASES
            ):
                # Dikeluarkan dari kotak potongan mana pun, persis
                # seperti `_settle_totals()` mengeluarkannya dari
                # `total_deduction`. Kalau ikut, grafik dan kartu
                # berhenti sepakat.
                reduction += amount
                continue

            key = (row["component_type"], row["source"])

            totals[key] = totals.get(key, ZERO) + amount

        context["_component_totals"] = totals
        context["_earnings_reduction"] = reduction

        return totals

    @classmethod
    def earnings_reduction(cls, context: dict) -> Decimal:
        """
        Gaji yang tidak pernah terbentuk pada run terpilih.

        Alpa dan cuti tidak dibayar — Business Decision #2. Dibaca dari
        **basis** komponennya, bukan dari kode maupun sumbernya, jadi
        tenant yang menulis pengurangnya sendiri di Deduction Template
        tetap terhitung di sini dan tetap keluar dari kotak `Potongan`.

        Nilainya positif: ia besaran yang dikurangkan, bukan angka
        bertanda.
        """
        cls.component_totals(context)

        return context.get("_earnings_reduction") or ZERO

    @classmethod
    def _source_total(cls, context: dict, component_type, sources) -> Decimal:
        totals = cls.component_totals(context)

        return sum(
            (totals.get((component_type, source), ZERO) for source in sources),
            ZERO,
        )

    # ------------------------------------------------------------------
    # Kartu KPI
    # ------------------------------------------------------------------

    @classmethod
    def employees(cls, context: dict) -> dict:
        return {"value": cls.totals(context)["employees"] or 0}

    @classmethod
    def gross_payroll(cls, context: dict) -> dict:
        return {"value": _amount(cls.totals(context)["gross"])}

    @classmethod
    def total_deduction(cls, context: dict) -> dict:
        return {"value": _amount(cls.totals(context)["deduction"])}

    @classmethod
    def net_payroll(cls, context: dict) -> dict:
        return {"value": _amount(cls.totals(context)["net"])}

    @classmethod
    def employer_contribution(cls, context: dict) -> dict:
        """
        Beban perusahaan — iuran yang dibayar perusahaan, bukan yang
        dipotong dari pegawai.

        Dibaca dari kolom `employer_contribution`, bukan dari komponen
        ber-kode "BPJS-*". Angka yang lahir dari tebakan nama terbaca
        sebagai angka resmi justru ketika ia salah.
        """
        return {"value": _amount(cls.totals(context)["employer"])}

    @classmethod
    def total_payroll_cost(cls, context: dict) -> dict:
        """
        `Gross + Employer Contribution`, **bukan** Net.

        Yang dikeluarkan perusahaan bukan yang diterima pegawai: net
        sudah dikurangi pajak dan iuran yang tetap dibayarkan
        perusahaan ke pihak ketiga, dan biaya sesungguhnya justru di
        atas gross.
        """
        totals = cls.totals(context)

        return {
            "value": _amount(
                (totals["gross"] or ZERO) + (totals["employer"] or ZERO),
            ),
        }

    @classmethod
    def overtime(cls, context: dict) -> dict:
        """
        Upah lembur, bukan jam lembur.

        Diambil dari komponen ber-sumber `OVERTIME` — angka yang
        benar-benar masuk gross, sudah lewat tingkat dan pengalinya.
        Mengalikan `overtime_hours` dengan tarif di sini berarti
        menghitung ulang lembur di dashboard, dan hasilnya akan
        berbeda dari slip begitu kelompoknya bertingkat.
        """
        return {
            "value": _amount(
                cls._source_total(
                    context,
                    PayrollComponentType.EARNING,
                    (PayrollComponentSource.OVERTIME,),
                ),
            ),
        }

    @classmethod
    def absence_unpaid(cls, context: dict) -> dict:
        """
        Potongan alpa + cuti tidak dibayar, dari kolom hasil #2.

        Pegawai **harian** menyumbang nol di sini dan itu benar: upahnya
        tidak pernah terbentuk pada hari yang tidak dibayar, jadi tidak
        ada yang dipotong. Harinya tetap tercatat di barisnya.
        """
        totals = cls.totals(context)

        return {
            "value": _amount(
                (totals["absence"] or ZERO) + (totals["unpaid"] or ZERO),
            ),
        }

    # ------------------------------------------------------------------
    # Progress run
    # ------------------------------------------------------------------

    @classmethod
    def run_progress(cls, context: dict) -> dict:
        run = cls.run_of(context)

        if run is None:
            return {"items": []}

        counts = cls.run_lines(context).aggregate(
            generated=Count("id"),
            calculated=Count(
                "id",
                filter=Q(
                    status__in=[
                        PayrollRunEmployeeStatus.CALCULATED,
                        PayrollRunEmployeeStatus.FINALIZED,
                    ],
                ),
            ),
            finalized=Count(
                "id",
                filter=Q(status=PayrollRunEmployeeStatus.FINALIZED),
            ),
            failed=Count(
                "id",
                filter=Q(status=PayrollRunEmployeeStatus.ERROR),
            ),
        )

        link = cls.run_link(run)

        items = [
            {
                "id": "run",
                "label": run.document_number or f"Run #{run.pk}",
                "hint": cls._run_caption(run),
                "count": counts["generated"] or 0,
                "status": PayrollRunStatus(run.status).label,
                "state": cls._run_state(run),
                "link": link,
            },
        ]

        done_so_far = True

        for key, label, stamp_field, count_key in STAGES:
            stamp = getattr(run, stamp_field) if stamp_field else None

            if key == "draft":
                done = True
            elif key == "generated":
                done = bool(counts["generated"])
            else:
                done = stamp is not None

            # Tahap pertama yang belum selesai adalah yang sedang
            # berjalan; sesudahnya semua "belum". Tanpa penanda ini,
            # run yang sudah Final tapi tanggal approval-nya kosong
            # (data lama) akan menampilkan dua tahap "berjalan".
            if done:
                state = "success"
                status = "Selesai"
            elif done_so_far:
                state = "warning"
                status = "Berjalan"
                done_so_far = False
            else:
                state = ""
                status = "Belum"

            hint = cls._stamp_caption(run, key, stamp, counts)

            # Barisnya sengaja **tidak** bertautan. Kartu ini sudah
            # punya satu tautan ke run-nya — di baris kepala dan di
            # tombol "Lihat Semua" — dan enam baris yang semuanya
            # menuju tempat yang sama membuat tautan berhenti berarti
            # apa-apa. Yang bertautan hanya baris yang menawarkan
            # tindakan.
            items.append(
                {
                    "id": key,
                    "label": label,
                    "hint": hint,
                    "count": counts.get(count_key) if count_key else None,
                    "status": status,
                    "state": state,
                },
            )

        # Ditolak dan dibatalkan bukan tahap — keduanya simpangan, dan
        # menyisipkannya ke dalam urutan membuat seolah setiap run
        # melewatinya.
        if run.status == PayrollRunStatus.REJECTED:
            items.append(
                {
                    "id": "rejected",
                    "label": "Ditolak",
                    "hint": run.notes or "Pengajuan dikembalikan approver.",
                    "count": None,
                    "status": "Ditolak",
                    "state": "danger",
                    "link": link,
                },
            )

        if run.status == PayrollRunStatus.CANCELLED:
            items.append(
                {
                    "id": "cancelled",
                    "label": "Dibatalkan",
                    "hint": run.notes or "Run tidak dilanjutkan.",
                    "count": None,
                    "status": "Dibatalkan",
                    "state": "danger",
                    "link": link,
                },
            )

        return {"items": items, "link": link}

    @staticmethod
    def _run_caption(run) -> str:
        parts = [getattr(run.period, "name", "") or ""]

        company = getattr(run, "company", None)

        if company is not None:
            parts.append(company.name)

        return " · ".join(part for part in parts if part)

    @staticmethod
    def _run_state(run) -> str:
        off_track = (
            PayrollRunStatus.REJECTED,
            PayrollRunStatus.CANCELLED,
        )

        if run.status in off_track:
            return "danger"

        if run.status == PayrollRunStatus.FINALIZED:
            return "success"

        return "warning"

    @classmethod
    def _stamp_caption(cls, run, key: str, stamp, counts: dict) -> str:
        """
        Keterangan satu tahap: kapan, oleh siapa, dan apa yang tersisa.

        Yang gagal dihitung disebut di tahap Dihitung, bukan disimpan
        untuk kartu Perlu Ditindaklanjuti saja — yang membaca progress
        harus tahu bahwa "sudah dihitung" tidak berarti "semuanya
        berhasil".
        """
        actor_field = {
            "calculated": "calculated_by",
            "submitted": "submitted_by",
            "approved": "approved_by",
            "finalized": "finalized_by",
        }.get(key)

        pieces = []

        if stamp is not None:
            pieces.append(stamp.strftime("%d %b %Y %H:%M"))

        actor = getattr(run, actor_field, None) if actor_field else None

        if actor is not None:
            pieces.append(
                getattr(actor, "get_full_name", lambda: "")()
                or getattr(actor, "username", "")
                or "",
            )

        if key == "calculated" and counts.get("failed"):
            pieces.append(f"{counts['failed']} gagal")

        return " · ".join(piece for piece in pieces if piece)

    # ------------------------------------------------------------------
    # Perlu ditindaklanjuti
    # ------------------------------------------------------------------

    @classmethod
    def attention(cls, context: dict, *, limit: int = 12) -> dict:
        """
        Temuan yang sudah dihasilkan `PayrollValidationService`,
        dikelompokkan per kode.

        **Tidak ada validasi yang dijalankan ulang di sini.** Yang
        dibaca `PayrollRun.validation_summary` — ringkasan yang sama
        persis yang dipakai layar Review dan yang mengunci Finalize.
        Memeriksa ulang berarti dashboard bisa menampilkan temuan yang
        berbeda dari yang menghalangi tombolnya, dan yang membacanya
        tidak punya cara tahu mana yang berlaku.
        """
        run = cls.run_of(context)

        if run is None:
            return {"items": []}

        link = cls.run_link(run)

        findings = cls._visible_findings(context, run)

        grouped: dict[str, dict] = {}

        for item in findings:
            code = item.get("code") or "unknown"

            bucket = grouped.setdefault(
                code,
                {
                    "id": code,
                    "label": FINDING_TITLES.get(code)
                    or item.get("message")
                    or code,
                    "names": [],
                    "count": 0,
                    "level": item.get("level"),
                    "message": item.get("message") or "",
                },
            )

            bucket["count"] += 1

            name = item.get("employee_name")

            if name:
                bucket["names"].append(name)

            # Satu kode bisa membawa dua tingkat (mis. temuan mesin
            # hitung yang naik ke ringkasan). Yang paling berat yang
            # menang — kelompok yang berisi satu error tidak boleh
            # tampil sebagai peringatan.
            if item.get("level") == PayrollFindingLevel.ERROR:
                bucket["level"] = PayrollFindingLevel.ERROR

        items = [
            {
                "id": bucket["id"],
                "label": bucket["label"],
                "hint": cls._finding_hint(bucket),
                "count": bucket["count"],
                "level": (
                    "Error"
                    if bucket["level"] == PayrollFindingLevel.ERROR
                    else "Peringatan"
                ),
                "state": (
                    "danger"
                    if bucket["level"] == PayrollFindingLevel.ERROR
                    else "warning"
                ),
                "link": link,
            }
            for bucket in grouped.values()
        ]

        items.extend(cls._operational_attention(context, run, link))

        # Error dulu, lalu yang paling banyak. Daftar yang diurutkan
        # menurut kode akan menaruh satu peringatan di atas sepuluh
        # error hanya karena huruf awalnya.
        items.sort(
            key=lambda item: (item["state"] != "danger", -item["count"]),
        )

        return {"items": items[:limit], "total": len(items), "link": link}

    @classmethod
    def _visible_findings(cls, context: dict, run) -> list[dict]:
        """
        Temuan yang menyebut pegawai di luar cakupan pembacanya dibuang.

        `validation_summary` dibekukan atas **seluruh** run — ia tidak
        tahu siapa yang membacanya. Temuan membawa nama dan nomor
        pegawai di pesannya, jadi menampilkannya apa adanya membocorkan
        daftar orang yang barisnya sendiri sudah disembunyikan
        `EmployeeDataPolicy`. Temuan tingkat run (yang tidak menyebut
        pegawai) tetap tampil untuk semua.
        """
        summary = run.validation_summary or {}

        findings = [
            *(summary.get("errors") or []),
            *(summary.get("warnings") or []),
        ]

        if not findings:
            return []

        # Dihitung dari `lines()` untuk run yang **diberikan**, bukan
        # dari run yang kebetulan terpilih. Keduanya sama di jalur
        # normal; menyandarkannya pada pilihan berarti pemanggil
        # berikutnya yang memeriksa run lain mendapat daftar pegawai
        # milik run yang salah — dan yang lolos justru nama yang
        # seharusnya disembunyikan.
        visible = set(
            cls.lines(context)
            .filter(run=run)
            .values_list("employee_id", flat=True),
        )

        return [
            item
            for item in findings
            if not item.get("employee") or item.get("employee") in visible
        ]

    @staticmethod
    def _finding_hint(bucket: dict) -> str:
        names = bucket["names"]

        if not names:
            return bucket["message"]

        shown = ", ".join(names[:3])

        if len(names) > 3:
            shown = f"{shown}, +{len(names) - 3} lainnya"

        return shown

    @classmethod
    def _operational_attention(
        cls,
        context: dict,
        run,
        link: str,
    ) -> list[dict]:
        """
        Keadaan run yang **bukan** temuan validasi tapi tetap menahan
        payroll: menunggu approver, dan run yang belum pernah dihitung.

        Keduanya dibaca dari kolom dokumennya sendiri. Yang kedua cuma
        ditambahkan kalau `validation_summary` memang masih kosong —
        run yang sudah divalidasi sudah punya temuan `not_calculated`
        sendiri, dan menampilkan keduanya berarti satu keadaan dihitung
        dua kali.
        """
        items = []

        if run.status == PayrollRunStatus.SUBMITTED:
            items.append(
                {
                    "id": "approval_pending",
                    "label": "Menunggu persetujuan",
                    "hint": cls._approval_hint(run),
                    "count": 1,
                    "level": "Peringatan",
                    "state": "warning",
                    "link": link,
                },
            )

        if not (run.validation_summary or {}):
            pending = cls.run_lines(context).filter(
                status=PayrollRunEmployeeStatus.PENDING,
            ).count()

            if pending:
                items.append(
                    {
                        "id": "not_calculated",
                        "label": FINDING_TITLES["not_calculated"],
                        "hint": "Jalankan Calculate pada run ini.",
                        "count": pending,
                        "level": "Error",
                        "state": "danger",
                        "link": link,
                    },
                )

        return items

    @staticmethod
    def _approval_hint(run) -> str:
        """
        Siapa yang sedang ditunggu, dibaca dari alur yang sudah ada.

        `WorkflowInstance.pending_approvals` sudah menjawab pertanyaan
        ini untuk seluruh dokumen di sistem — termasuk step bertipe
        Role Holder yang menunggu beberapa orang sekaligus. Menyusun
        ulang aturannya di sini berarti dashboard bisa menyebut nama
        yang berbeda dari kotak masuk approval-nya sendiri.

        Alur yang tidak ketemu (run lama, definisi yang dihapus)
        jatuh ke stempel waktu pengajuannya, bukan ke pesan galat:
        yang dijawab baris ini "run ini tertahan", dan itu tetap benar
        walau namanya tidak bisa disebut.
        """
        from apps.workflow.models import WorkflowInstance

        submitted = (
            run.submitted_at.strftime("%d %b %Y %H:%M")
            if run.submitted_at
            else ""
        )

        instance = (
            WorkflowInstance.objects
            .filter(
                module="payroll",
                document_type="payroll_run",
                object_id=str(run.pk),
            )
            .order_by("-id")
            .first()
        )

        if instance is None or not instance.is_open:
            return submitted

        names = [
            (
                approval.approver
                and (
                    approval.approver.get_full_name()
                    or approval.approver.username
                )
            )
            or approval.name
            for approval in instance.pending_approvals.select_related(
                "approver",
            )
        ]

        names = [name for name in names if name]

        if not names:
            return submitted

        waiting = ", ".join(names[:3])

        if len(names) > 3:
            waiting = f"{waiting}, +{len(names) - 3} lainnya"

        return f"Menunggu {waiting}" + (f" · {submitted}" if submitted else "")

    # ------------------------------------------------------------------
    # Tabel run berjalan
    # ------------------------------------------------------------------

    @classmethod
    def run_employees(cls, context: dict, *, page) -> dict:
        """
        Baris pegawai run terpilih, dipaginasi di sisi server.

        Tiga query berapa pun jumlah pegawainya: satu menghitung
        seluruh baris (untuk penghitung dan baris Total), satu mengambil
        halaman yang diminta, satu menjumlahkan komponen **halaman itu**
        per sumber. Mengambil komponen lewat relasi per baris akan
        menghasilkan satu query per pegawai — dua puluh lima query untuk
        satu layar, lima ratus untuk satu run.
        """
        queryset = (
            cls.run_lines(context)
            .select_related("employee", "payroll_policy")
            .order_by("employee__employee_number", "id")
        )

        total = queryset.count()

        if page.search:
            needle = page.search

            queryset = queryset.filter(
                Q(employee__employee_number__icontains=needle)
                | Q(employee__first_name__icontains=needle)
                | Q(employee__last_name__icontains=needle),
            )

        matched = queryset.count() if page.search else total

        rows = list(queryset[page.offset:page.offset + page.page_size])

        components = cls._components_by_line(rows)

        items = [
            cls._employee_row(line, components.get(line.pk, {}))
            for line in rows
        ]

        totals = cls.totals(context)

        return page.envelope(
            items=items,
            matched=matched,
            total=total,
            # Kaki tabel dihilangkan kalau memang tidak ada barisnya.
            # Baris Total berisi nol di bawah tabel kosong terbaca
            # sebagai "payroll periode ini nol rupiah", bukan sebagai
            # "belum ada run" — dan yang kedua yang benar.
            # Baris Total menjumlahkan **seluruh** run, bukan halaman
            # yang kebetulan terbuka — aturan `TablePage`. Pindah
            # halaman karena itu tidak menggeser satu angka pun di
            # kakinya.
            totals=None if not total else {
                "base_earning": _amount(
                    cls._source_total(
                        context,
                        PayrollComponentType.EARNING,
                        (PayrollComponentSource.BASIC,),
                    ),
                ),
                "allowance": _amount(
                    cls._source_total(
                        context,
                        PayrollComponentType.EARNING,
                        (
                            PayrollComponentSource.ALLOWANCE_TEMPLATE,
                            PayrollComponentSource.INPUT,
                        ),
                    ),
                ),
                "overtime": _amount(
                    cls._source_total(
                        context,
                        PayrollComponentType.EARNING,
                        (PayrollComponentSource.OVERTIME,),
                    ),
                ),
                "deduction": _amount(totals["deduction"]),
                "net_pay": _amount(totals["net"]),
            },
        )

    @staticmethod
    def _components_by_line(rows) -> dict[int, dict]:
        if not rows:
            return {}

        aggregated = (
            PayrollRunComponent.objects
            .filter(
                is_deleted=False,
                run_employee_id__in=[line.pk for line in rows],
            )
            .values("run_employee_id", "component_type", "source")
            .annotate(total=Sum("amount"))
        )

        result: dict[int, dict] = {}

        for row in aggregated:
            bucket = result.setdefault(row["run_employee_id"], {})
            key = (row["component_type"], row["source"])
            bucket[key] = row["total"] or ZERO

        return result

    @classmethod
    def _employee_row(cls, line, components: dict) -> dict:
        def total(component_type, *sources) -> Decimal:
            return sum(
                (components.get((component_type, source), ZERO)
                 for source in sources),
                ZERO,
            )

        return {
            "id": line.pk,
            "employee": cls._employee_name(line),
            "employee_number": getattr(
                line.employee, "employee_number", "",
            ) or "",
            "policy": cls.policy_label(line),
            "pay_basis": cls.basis_label(line),
            # Dasar upah = komponen ber-sumber BASIC, **bukan**
            # `basic_salary`. Untuk pegawai harian kolom itu berisi gaji
            # sebulan yang tidak pernah dipakai menghitung apa pun (dan
            # lazimnya nol); yang benar-benar ia terima adalah tarif
            # sehari x hari yang dibayar, dan itu yang tertulis di
            # komponennya.
            "base_earning": _amount(
                total(
                    PayrollComponentType.EARNING,
                    PayrollComponentSource.BASIC,
                ),
            ),
            "allowance": _amount(
                total(
                    PayrollComponentType.EARNING,
                    PayrollComponentSource.ALLOWANCE_TEMPLATE,
                    PayrollComponentSource.INPUT,
                ),
            ),
            "overtime": _amount(
                total(
                    PayrollComponentType.EARNING,
                    PayrollComponentSource.OVERTIME,
                ),
            ),
            "deduction": _amount(line.total_deduction),
            "net_pay": _amount(line.net_pay),
            "status": PayrollRunEmployeeStatus(line.status).label,
            "state": {
                PayrollRunEmployeeStatus.ERROR: "danger",
                PayrollRunEmployeeStatus.PENDING: "warning",
                PayrollRunEmployeeStatus.CALCULATED: "success",
                PayrollRunEmployeeStatus.FINALIZED: "success",
            }.get(line.status, ""),
        }

    @staticmethod
    def _employee_name(line) -> str:
        employee = line.employee

        name = getattr(employee, "full_name", None)

        if callable(name):
            name = name()

        return name or str(employee)

    @staticmethod
    def policy_label(line) -> str:
        """
        Nama kebijakan yang **dibekukan di baris ini**, bukan yang
        berlaku di assignment hari ini.

        Kosong berarti pegawainya mengikuti `PayrollSetting`
        perusahaan — keadaan yang sah, dan bedanya dengan "punya
        kebijakan yang kebetulan sama" harus tetap terbaca. Tidak ada
        nama kebijakan yang ditulis di kode: yang keluar di sini
        apa pun yang diketik tenant di master.
        """
        policy = getattr(line, "payroll_policy", None)

        if policy is None:
            return COMPANY_DEFAULT_LABEL

        return policy.name or policy.code

    @staticmethod
    def basis_label(line) -> str:
        """
        Label manusiawi `pay_basis`, bukan "MONTHLY"/"DAILY" mentah.

        Dibaca dari snapshot di barisnya sendiri — bukan dari nama
        kelompok pegawai, lokasi, atau perusahaan. Payroll memang tidak
        mengenal kategori-kategori itu, dan mencabangkan tampilan
        berdasarkan salah satunya akan salah di tenant pertama yang
        menamai kantornya berbeda.
        """
        basis = getattr(line, "pay_basis", "") or ""

        if not basis:
            return ""

        try:
            return PayrollPayBasis(basis).label
        except ValueError:
            return basis

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @classmethod
    def cost_trend(cls, context: dict) -> dict:
        """
        Enam periode payroll terakhir dalam cakupan yang sama.

        Sumbu-x-nya **periode payroll**, bukan bulan kalender, dan itu
        bukan detail: periode bisa berjalan 26–25, bisa dua kali sebulan,
        dan bisa berjudul "THR 2027". Memaksanya ke bulan kalender
        membuat dua periode jatuh di satu titik dan angkanya berlipat
        tanpa ada yang menyadarinya.
        """
        lines = cls.lines(context)

        # Periode yang punya **baris yang boleh dibaca akun ini**,
        # bukan periode yang punya run.
        #
        # Bedanya bukan kehalusan. Cakupan `EmployeeDataPolicy` bisa
        # menutup seluruh baris gaji sementara dokumen run-nya sendiri
        # tetap boleh dibuka — dan chart yang tetap menggambar enam
        # periode bernilai nol untuk orang itu berkata "payroll bulan
        # itu nol rupiah", bukan "kamu tidak boleh melihatnya". Yang
        # kedua yang benar, dan bentuk yang menyampaikannya adalah
        # chart kosong beserta kalimat keadaan kosongnya.
        period_ids = list(
            cls.periods(context)
            .filter(pk__in=lines.values("run__period_id"))
            .order_by("-start_date", "-id")
            .values_list("pk", flat=True)[:TREND_PERIODS]
        )

        if not period_ids:
            return {"categories": [], "datasets": []}

        period_ids.reverse()

        periods = sorted(
            PayrollPeriod.objects.filter(pk__in=period_ids),
            key=lambda item: period_ids.index(item.pk),
        )

        lines = lines.filter(run__period_id__in=period_ids)

        by_period = {
            row["run__period_id"]: row
            for row in (
                lines
                .values("run__period_id")
                .annotate(gross=Sum("gross_earning"), net=Sum("net_pay"))
            )
        }

        overtime = {
            row["run_employee__run__period_id"]: row["total"] or ZERO
            for row in (
                PayrollRunComponent.objects
                .filter(
                    is_deleted=False,
                    source=PayrollComponentSource.OVERTIME,
                    component_type=PayrollComponentType.EARNING,
                    run_employee__in=lines,
                )
                .values("run_employee__run__period_id")
                .annotate(total=Sum("amount"))
            )
        }

        return {
            "categories": [period.code or period.name for period in periods],
            "datasets": [
                {
                    "label": "Gross Payroll",
                    "data": [
                        _amount(by_period.get(pk, {}).get("gross"))
                        for pk in period_ids
                    ],
                },
                {
                    "label": "Net Payroll",
                    "data": [
                        _amount(by_period.get(pk, {}).get("net"))
                        for pk in period_ids
                    ],
                },
                {
                    "label": "Lembur",
                    "data": [
                        _amount(overtime.get(pk, ZERO)) for pk in period_ids
                    ],
                },
            ],
        }

    @classmethod
    def composition(cls, context: dict) -> dict:
        series = []

        for label, component_type, sources in COMPOSITION:
            value = cls._source_total(context, component_type, sources)

            # Kategori bernilai nol dibuang, bukan digambar sebagai
            # batang setinggi nol. Tenant yang tidak memakai PPh21 tidak
            # perlu melihat kotak kosong bernama PPh21 tiap bulan.
            if not value:
                continue

            series.append({"label": label, "value": _amount(value)})

        # Kelompok ketiga, dan sengaja **sesudah** seluruh kategori
        # komponen: ia bukan penghasilan dan bukan potongan, melainkan
        # penghasilan yang tidak pernah terbentuk. Yang membacanya
        # merekonsiliasi begini —
        #
        #     (Gaji Pokok + Tunjangan + Lembur + Input Variabel)
        #       - Ketidakhadiran  = Gross Payroll
        #
        # Nol tetap dibuang, sama seperti kategori lain: tenant tanpa
        # alpa tidak perlu melihat juring kosong tiap bulan.
        reduction = cls.earnings_reduction(context)

        if reduction:
            series.append(
                {
                    "label": EARNINGS_REDUCTION_LABEL,
                    "value": _amount(reduction),
                },
            )

        return {"series": series}

    # ------------------------------------------------------------------
    # Rincian
    # ------------------------------------------------------------------

    @classmethod
    def breakdown(cls, context: dict, *, field: str, key: str) -> dict:
        """
        Agregasi run terpilih menurut satu sumbu organisasi/kebijakan.

        Satu query per sumbu, dijumlahkan database. Mengambil seluruh
        baris lalu mengelompokkannya di Python berarti run 500 pegawai
        memindahkan 500 baris ke memori tiga kali untuk menghasilkan
        selusin angka.
        """
        rows = (
            cls.run_lines(context)
            .values(field)
            .annotate(
                employees=Count("id"),
                gross=Sum("gross_earning"),
                deduction=Sum("total_deduction"),
                net=Sum("net_pay"),
            )
            .order_by("-gross")
        )

        default = (
            COMPANY_DEFAULT_LABEL
            if field == "payroll_policy__name"
            else UNASSIGNED_LABEL
        )

        items = [
            {
                "id": index,
                key: row[field] or default,
                "employees": row["employees"] or 0,
                "gross": _amount(row["gross"]),
                "deduction": _amount(row["deduction"]),
                "net": _amount(row["net"]),
            }
            for index, row in enumerate(rows)
        ]

        totals = cls.totals(context)

        return {
            "items": items,
            "total": len(items),
            "totals": {
                "employees": totals["employees"] or 0,
                "gross": _amount(totals["gross"]),
                "deduction": _amount(totals["deduction"]),
                "net": _amount(totals["net"]),
            } if items else None,
        }

    # ------------------------------------------------------------------
    # Navigasi
    # ------------------------------------------------------------------

    @staticmethod
    def run_link(run) -> str:
        """
        Tujuan tombol dan baris yang bisa ditekan.

        Sengaja ke **detail run**, bukan ke daftar Payroll Review
        ber-query `?run=<id>&status=error`: halaman daftar di frontend
        tidak membaca query string jadi filter, jadi tautan seperti itu
        membuka daftar seluruh tenant sambil terlihat seperti daftar
        yang tersaring — dead link yang paling sulit ketahuan, karena
        halamannya terbuka dan berisi.

        Dan detail run **memang** tempat yang dicari: tab anaknya
        adalah daftar `payroll-run-employees` yang sudah tersaring ke
        run itu lewat `foreignKey` (`payrollRunsWorkspace`), jadi yang
        menekan temuan mendarat tepat di baris-baris yang dimaksud —
        bukan di layar yang harus disaring ulang dengan tangan.
        """
        return f"/payroll/payroll-runs/{run.pk}"
