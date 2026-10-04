"""
Aturan roster per site: pola siklus, hari perjalanan, konversi rotation
credit, dan batas pengajuan.

Diturunkan dari dokumen "Substansi Roster" milik klien tambang, yang
menyebutkan tiga hal yang selama ini ditebak kode:

1. **Waktu perjalanan ditentukan jarak, bukan gelombang.** Pegawai
   ber-POH Makassar mendapat 2 hari, Yogyakarta/Bandung/Luwuk Banggai 3
   hari — walau satu crew dan satu pola roster. Karena itu angkanya
   dipetakan dari pasangan (site, Point of Hire), bukan disimpan di
   dokumen roster.

2. **Rasio kerja:off dipakai untuk mengonversi hari.** 6:2 → 42:14 = 3,
   7:2 → 49:14 = 3,5, 8:2 → 56:14 = 4. Mundur cuti atas persetujuan KTT
   memberi tambahan off sebesar `hari ÷ rasio`; terlambat kembali
   karena kesalahan pegawai menambah on-site sebesar `hari × rasio`.

3. **Pengajuan punya tenggat.** Travel Request diajukan sekian hari
   sebelum berangkat, dan sistem mengingatkan sekian hari sebelumnya.

Semuanya per site, karena Gebe dan Bacan tidak harus sama.

Policy juga **pembawa pola siklus**
-----------------------------------
Sejak roster dikerjakan penuh, policy inilah yang memegang 4:2 / 5:2 /
6:2 / 8:2 dan seterusnya, dan pegawai menunjuknya lewat
`EmploymentAssignment.roster_policy`. Tidak ada satu pun rumus yang
membaca **nama** atau **kode** policy — semuanya angka yang bisa diubah
dari layar.

Konsekuensinya satu site boleh punya banyak policy (`GBE-6-2` dan
`GBE-8-2` berdampingan), jadi constraint lama "satu policy per site"
dicabut. Yang menggantikan penjagaannya `is_default`: banyak policy
boleh, tapi hanya satu yang jadi bawaan site — kalau tidak, hari
perjalanan seseorang kembali bergantung pada nomor id di database.

**Pola boleh kosong, dan itu disengaja.** Baris yang sudah terlanjur
diseed sebagai aturan site murni tidak dikarang polanya oleh migrasi;
angka karangan di master lebih berbahaya daripada tidak ada angka,
karena orang menganggapnya sudah divalidasi. Policy tanpa pola tetap
sah dan tetap memberi hari perjalanan — ia hanya tidak bisa ditugaskan
ke pegawai, dan `EmploymentAssignment.clean()` yang menolaknya.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class RosterStartBasis(models.TextChoices):
    """
    Arti tanggal yang diketik sebagai Current Cycle Start.

    Ketiganya menghasilkan tanggal blok kerja yang berbeda dari input
    yang sama, jadi tidak boleh diasumsikan — itu sebabnya ia jadi
    kolom, bukan konvensi.
    """

    WORK_START_DATE = "work_start", "Work Start Date"
    SITE_ARRIVAL_DATE = "site_arrival", "Site Arrival Date"
    TRAVEL_DEPARTURE_DATE = "travel_departure", "Travel Departure Date"


class TravelDayMode(models.TextChoices):
    FIXED = "fixed", "Fixed (from policy)"
    ACTUAL_ITINERARY = "actual", "Actual Itinerary"


class CreditRounding(models.TextChoices):
    FLOOR = "floor", "Round Down"
    ROUND_HALF_UP = "half_up", "Round Half Up"
    CEIL = "ceil", "Round Up"
    EXACT = "exact", "Exact (no rounding)"


# Pagar untuk `min_rest_hours`, bukan kebijakan. Dua minggu adalah
# angka yang sudah pasti salah ketik: jeda sepanjang itu antar
# pergantian shift memakan seluruh blok kerja dan mengubahnya jadi
# hari pemulihan. Yang dijaga cuma itu — berapa jam yang wajar untuk
# satu site tetap keputusan site tersebut.
MAX_MIN_REST_HOURS = 336


class RosterPolicy(BaseModel):
    """
    Satu aturan roster, berlaku untuk satu site atau seluruh company.

    Pencocokan **bawaan site** berjenjang lewat `specificity`, pola yang
    sama dengan `LeavePolicy` dan `WorkflowDefinition`: yang menyebut
    location menang atas yang hanya menyebut company, dan itu menang atas
    yang global. Kosong berarti "berlaku untuk semua", bukan "tidak
    berlaku".

    Pencocokan itu **tidak** dipakai untuk menentukan pola roster
    pegawai. Pola selalu dari `EmploymentAssignment.roster_policy` yang
    ditunjuk eksplisit — kalau kosong, pegawainya memang bukan pegawai
    roster dan generator tidak menyentuhnya sama sekali.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="roster_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak "
            "punya aturannya sendiri."
        ),
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="roster_policies",
        help_text=(
            "Site yang diatur. Dikosongkan = berlaku untuk semua site "
            "di company itu."
        ),
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    # Satu site boleh punya beberapa policy (6:2 dan 8:2 berdampingan),
    # tapi hanya satu yang jadi bawaan. Ini yang dipakai untuk mengisi
    # awal form dan untuk menjawab hari perjalanan pegawai yang belum
    # punya policy — dua hal yang tidak boleh bergantung pada nomor id.
    is_default = models.BooleanField(
        default=False,
        help_text=(
            "Aturan bawaan untuk site ini. Hanya boleh satu per site."
        ),
    )

    # ------------------------------------------------------------------
    # Pola siklus
    # ------------------------------------------------------------------

    cycle_work_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Jumlah hari blok kerja — 42 untuk pola 6:2, 56 untuk 8:2. "
            "Dikosongkan = aturan site saja, tidak bisa ditugaskan ke "
            "pegawai."
        ),
    )

    cycle_off_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Jumlah hari blok field break — 14 untuk 2 minggu.",
    )

    roster_start_basis = models.CharField(
        max_length=20,
        choices=RosterStartBasis.choices,
        default=RosterStartBasis.WORK_START_DATE,
        help_text=(
            "Arti tanggal Current Cycle Start pegawai. Work Start = hari "
            "pertama masuk kerja. Site Arrival = hari tiba di site "
            "(perjalanan menuju site sudah dihitung On Site). Travel "
            "Departure = hari berangkat dari Point of Hire."
        ),
    )

    rolling_horizon_months = models.PositiveSmallIntegerField(
        default=12,
        help_text=(
            "Jadwal digenerate sampai sekian bulan ke depan, lalu "
            "diperpanjang berkala. 0 = ikut bawaan sistem."
        ),
    )

    # ------------------------------------------------------------------
    # Jeda antar shift
    # ------------------------------------------------------------------

    # Satu angka, dan sengaja satu: yang diperiksa **selisih waktu
    # sungguhan** antara jam selesai shift terakhir dan jam mulai shift
    # berikutnya, bukan pasangan kode shift tertentu. Karena itu aturan
    # yang sama menutup Night → Day, Night → Afternoon, dan pergantian
    # apa pun yang belum ada di site mana pun hari ini — tanpa satu
    # baris tambahan di master maupun di kode.
    #
    # Bawaannya **0 = tidak diperiksa**. Site yang selama ini berjalan
    # tanpa aturan ini tidak boleh tiba-tiba kehilangan hari kerja
    # karena sebuah kolom baru lahir dengan angka di dalamnya.
    min_rest_hours = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Jeda istirahat minimum saat shift berganti, dalam jam — "
            "dihitung dari jam selesai shift terakhir sampai jam mulai "
            "shift berikutnya. Generator menyisipkan hari Recovery "
            "sampai jeda ini terpenuhi. 0 = tidak diperiksa."
        ),
    )

    # ------------------------------------------------------------------
    # Hari perjalanan
    # ------------------------------------------------------------------

    default_travel_out_days = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Hari perjalanan site → Point of Hire (pulang), untuk POH "
            "yang belum didaftarkan di tabel di bawah."
        ),
    )

    default_travel_in_days = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Hari perjalanan Point of Hire → site (berangkat), untuk POH "
            "yang belum didaftarkan di tabel di bawah."
        ),
    )

    travel_day_mode = models.CharField(
        max_length=20,
        choices=TravelDayMode.choices,
        default=TravelDayMode.FIXED,
        help_text=(
            "Fixed = jendela travel dari angka di atas. Actual Itinerary "
            "= setelah Travel Request disetujui, selisihnya dilaporkan "
            "sebagai usulan penyesuaian."
        ),
    )

    travel_creates_segment = models.BooleanField(
        default=True,
        help_text=(
            "Membuat baris Travel Out/Travel In di jadwal. Dimatikan = "
            "hari perjalanan cuma jadi celah kalender."
        ),
    )

    # Dua flag, bukan satu, karena aturan dokumen klien memang berbeda
    # per arah: site → POH bukan On Site (#1), sedangkan Sorong/Ternate →
    # site sudah dihitung On Site (#4).
    #
    # Keduanya **tidak** memendekkan blok kerja. Pegawai 45/14 yang dua
    # hari di kapal tetap menjalani 45 hari di site; memotongnya dari
    # Work Days membuat angka di kontrak tidak cocok dengan angka mana
    # pun di sistem. Yang dipengaruhi flag ini cuma rekap hari on-site.
    travel_out_counts_as_roster_day = models.BooleanField(
        default=False,
        help_text=(
            "Hari perjalanan pulang dihitung sebagai hari on-site di "
            "rekap. Tidak memendekkan blok kerja."
        ),
    )

    travel_in_counts_as_roster_day = models.BooleanField(
        default=False,
        help_text=(
            "Hari perjalanan berangkat dihitung sebagai hari on-site di "
            "rekap. Tidak memendekkan blok kerja."
        ),
    )

    count_transit_overnight = models.BooleanField(
        default=True,
        help_text=(
            "Malam menginap di kota transit ikut dihitung sebagai hari "
            "perjalanan saat membandingkan rencana dengan itinerary."
        ),
    )

    # Delay pesawat/kapal **tidak** otomatis jadi rotation credit —
    # aturan #17 dokumen menyebutnya di luar kendali pegawai, dan yang
    # di luar kendali tidak menghasilkan hak tambahan maupun kewajiban
    # tambahan. Perusahaan yang memutuskan sebaliknya menyalakannya di
    # sini, dan tetap dipagari batas hari.
    travel_variance_credit_eligible = models.BooleanField(
        default=False,
        help_text=(
            "Selisih hari perjalanan aktual terhadap rencana boleh jadi "
            "rotation credit. Bawaannya mati."
        ),
    )

    travel_variance_credit_max_days = models.PositiveSmallIntegerField(
        default=0,
        help_text="Batas hari selisih yang boleh dikonversi. 0 = tanpa batas.",
    )

    # ------------------------------------------------------------------
    # Rotation credit
    # ------------------------------------------------------------------

    credit_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Site ini memakai rotation credit. Dimatikan = kelebihan "
            "hari kerja tidak menghasilkan saldo apa pun."
        ),
    )

    conversion_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Perbandingan hari kerja : hari off. Dikosongkan = dihitung "
            "sendiri dari pola roster (56:14 = 4). Diisi hanya kalau "
            "perusahaan memakai angka yang berbeda dari polanya."
        ),
    )

    credit_rounding = models.CharField(
        max_length=20,
        choices=CreditRounding.choices,
        default=CreditRounding.FLOOR,
        help_text=(
            "Cara membulatkan hasil konversi. Round Down + Carry "
            "Remainder adalah pilihan yang paling bisa dijelaskan ke "
            "pegawai."
        ),
    )

    credit_carry_remainder = models.BooleanField(
        default=True,
        help_text=(
            "Sisa hari yang belum genap jadi satu kredit disimpan dan "
            "ikut dihitung pada konversi berikutnya, bukan hangus. "
            "Hanya berlaku untuk Round Down."
        ),
    )

    credit_max_balance_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Plafon saldo. Dikosongkan = tanpa plafon.",
    )

    credit_expiry_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Kredit kedaluwarsa setelah sekian bulan. Dikosongkan = "
            "tidak kedaluwarsa. Eksekusinya belum ada."
        ),
    )

    credit_allow_negative = models.BooleanField(
        default=False,
        help_text="Saldo boleh menembus nol.",
    )

    # ------------------------------------------------------------------
    # Tenggat pengajuan
    # ------------------------------------------------------------------

    request_lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text=(
            "Travel Request diajukan minimal sekian hari sebelum "
            "tanggal berangkat. 0 = tanpa tenggat."
        ),
    )

    notify_lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text=(
            "Sistem mengingatkan sekian hari sebelum tanggal berangkat "
            "kalau Travel Request-nya belum dibuat."
        ),
    )

    # Alasan yang boleh menembus tenggat. Menunjuk `RotationPurpose`
    # supaya daftarnya bisa diatur per tenant — duka, sakit, dinas, dan
    # penyesuaian roster karena ada pengganti di site tidak bisa
    # direncanakan seminggu sebelumnya.
    urgent_purposes = models.ManyToManyField(
        "administration.RotationPurpose",
        blank=True,
        related_name="roster_policies",
        help_text=(
            "Travel Purpose yang boleh diajukan mendadak, menembus "
            "tenggat di atas."
        ),
    )

    class Meta:
        db_table = "master_roster_policy"

        ordering = ["company", "location", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_rosterpolicy_code",
            ),
            # Menggantikan `uniq_active_rosterpolicy_target` yang dulu
            # membatasi satu policy per site. Banyak policy per site
            # sekarang sah — yang tetap tidak boleh dua adalah policy
            # **bawaan**, karena itulah yang dipilih tanpa disebut
            # siapa pun.
            models.UniqueConstraint(
                fields=["company", "location"],
                condition=Q(is_deleted=False) & Q(is_default=True),
                name="uniq_active_rosterpolicy_default",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "location", "is_default"],
                name="idx_roster_policy_scope",
            ),
        ]

    # ------------------------------------------------------------------
    # Turunan
    # ------------------------------------------------------------------

    @property
    def specificity(self) -> int:
        return (
            (2 if self.company_id else 0)
            + (1 if self.location_id else 0)
        )

    @property
    def has_cycle_pattern(self) -> bool:
        """
        Policy ini bisa ditugaskan ke pegawai atau tidak.

        Yang tanpa pola tetap berguna sebagai aturan site (hari
        perjalanan, tenggat pengajuan) — ia cuma tidak bisa
        menghasilkan jadwal.
        """
        return bool(self.cycle_work_days and self.cycle_off_days)

    @property
    def total_travel_days(self) -> int:
        return (
            (self.default_travel_out_days or 0)
            + (self.default_travel_in_days or 0)
        )

    @property
    def cycle_length(self) -> int | None:
        """
        Panjang satu putaran penuh dalam hari kalender.

        Hari perjalanan dihitung **sekali** per putaran: satu jendela
        keluar di ujung blok kerja, satu jendela kembali di ujung blok
        off.
        """
        if not self.has_cycle_pattern:
            return None

        return (
            self.cycle_work_days
            + self.cycle_off_days
            + self.total_travel_days
        )

    @property
    def derived_ratio(self) -> Decimal | None:
        """
        Rasio kerja:off dari polanya sendiri.

        Dihitung, bukan didaftar per pola: perusahaan yang besok memakai
        9:3 tidak perlu menunggu ada yang menambahkan barisnya di master.
        """
        if not self.has_cycle_pattern:
            return None

        return (
            Decimal(self.cycle_work_days) / Decimal(self.cycle_off_days)
        ).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.conversion_ratio is not None
            and self.conversion_ratio <= 0
        ):
            errors["conversion_ratio"] = (
                "Rasio konversi harus lebih besar dari nol."
            )

        # Site tanpa company tidak bisa dicocokkan: pencarian selalu
        # berangkat dari company pegawai.
        if self.location_id and not self.company_id:
            errors["company"] = (
                "Company wajib diisi kalau aturannya menyebut Site."
            )

        # Setengah pola lebih berbahaya daripada tanpa pola: yang
        # setengah akan lolos ke form pegawai lalu gagal saat generate,
        # jauh dari layar tempat angkanya diisi.
        if bool(self.cycle_work_days) != bool(self.cycle_off_days):
            missing = (
                "cycle_off_days"
                if self.cycle_work_days
                else "cycle_work_days"
            )

            errors[missing] = (
                "Work Days dan Off Days harus diisi dua-duanya, atau "
                "dikosongkan dua-duanya. Pola yang cuma separuh tidak "
                "bisa dipakai menghitung jadwal."
            )

        if (self.min_rest_hours or 0) > MAX_MIN_REST_HOURS:
            errors["min_rest_hours"] = (
                f"Maksimal {MAX_MIN_REST_HOURS} jam "
                f"({MAX_MIN_REST_HOURS // 24} hari). Jeda yang lebih "
                "panjang dari itu memakan seluruh blok kerja."
            )

        if (
            self.credit_max_balance_days is not None
            and self.credit_max_balance_days < 0
        ):
            errors["credit_max_balance_days"] = (
                "Plafon saldo tidak boleh negatif."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.code} — {self.name}"


class RosterTravelDay(BaseModel):
    """
    Hari perjalanan dari satu site ke satu Point of Hire.

    Baris inilah yang membuat Rahmawaty (Makassar, 2 hari) dan Budi
    (Yogyakarta, 3 hari) bisa satu crew tapi beda jadwal travel —
    sesuatu yang mustahil selama angkanya disimpan di dokumen roster.

    Dipecah out/in sejak jendela travel jadi baris jadwal tersendiri.
    Sebelumnya satu angka total pulang-pergi yang dipecah generator
    dengan pembulatan condong ke sisi keluar; sekarang pemecahannya jadi
    dua angka yang bisa dilihat dan diubah di layar, bukan rumus
    tersembunyi.
    """

    policy = models.ForeignKey(
        RosterPolicy,
        on_delete=models.CASCADE,
        related_name="travel_days",
    )

    point_of_hire = models.ForeignKey(
        "administration.City",
        on_delete=models.CASCADE,
        related_name="roster_travel_days",
    )

    travel_out_days = models.PositiveSmallIntegerField(
        default=1,
        help_text="Hari perjalanan site → Point of Hire (pulang).",
    )

    travel_in_days = models.PositiveSmallIntegerField(
        default=1,
        help_text="Hari perjalanan Point of Hire → site (berangkat).",
    )

    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "master_roster_travel_day"

        ordering = ["policy", "point_of_hire"]

        constraints = [
            models.UniqueConstraint(
                fields=["policy", "point_of_hire"],
                condition=Q(is_deleted=False),
                name="uniq_active_rostertravelday_poh",
            ),
        ]

    @property
    def total_days(self) -> int:
        return (self.travel_out_days or 0) + (self.travel_in_days or 0)

    def __str__(self):
        return (
            f"{self.point_of_hire} — {self.travel_out_days} keluar / "
            f"{self.travel_in_days} kembali"
        )


class RosterShiftRotation(BaseModel):
    """
    Urutan perputaran shift sebuah roster policy — **konfigurasi**, bukan
    kode.

    Kenapa barisnya ada di sini
    ---------------------------
    Sebelum ini urutan shift hanya hidup di dalam dialog: pengguna
    memilih shift satu per satu tiap kali menyusun rencana, dan sistem
    tidak menyimpan apa pun tentang polanya. Akibatnya jadwal shift tidak
    pernah bisa **diterbitkan otomatis** dari roster — padahal roster
    sendiri sudah lahir dari policy ini.

    Satu baris = satu langkah perputaran: "blok berikutnya pakai shift
    ini, selama sekian hari". `sequence` yang menentukan urutannya, dan
    perputaran kembali ke langkah pertama setelah langkah terakhir.

    Kenapa tabel tersendiri, bukan kolom di `RosterPolicy`
    ------------------------------------------------------
    Urutan berulang tidak muat di satu kolom. Menyimpannya sebagai teks
    (`"SHIFT-1,SHIFT-3,SHIFT-2"`) berarti kode shift jadi string yang
    tidak dijaga foreign key — shift yang dihapus dari master
    meninggalkan pola yang menunjuk sesuatu yang tidak ada, dan gagalnya
    baru terlihat saat jadwal diterbitkan. Bentuknya sama persis dengan
    `RosterTravelDay` di atas: daftar berurut milik satu policy, disunting
    lewat tabel inline di layar policy-nya.

    Yang **tidak** disimpan di sini: jam kerja. Itu milik master `Shift`,
    dan mengubah jam di sana mengubah seluruh jadwal tanpa satu baris pun
    di tabel ini disentuh.
    """

    policy = models.ForeignKey(
        RosterPolicy,
        on_delete=models.CASCADE,
        related_name="shift_rotations",
    )

    sequence = models.PositiveSmallIntegerField(
        help_text=(
            "Urutan langkah perputaran. Sesudah langkah terakhir, "
            "perputaran kembali ke langkah pertama."
        ),
    )

    shift = models.ForeignKey(
        "administration.Shift",
        on_delete=models.PROTECT,
        related_name="roster_shift_rotations",
        help_text=(
            "Jam kerjanya milik master Shift — mengubah jam di sana "
            "mengubah jadwal semua yang memakai pola ini."
        ),
    )

    block_days = models.PositiveSmallIntegerField(
        default=7,
        help_text=(
            "Berapa hari shift ini dipakai sebelum berganti ke langkah "
            "berikutnya. 7 = mingguan."
        ),
    )

    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "master_roster_shift_rotation"

        ordering = ["policy", "sequence"]

        constraints = [
            models.UniqueConstraint(
                fields=["policy", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_rostershiftrotation_sequence",
            ),
        ]

    def clean(self):
        super().clean()

        if self.block_days is not None and self.block_days < 1:
            raise ValidationError(
                {"block_days": "Minimal 1 hari."},
            )

    def __str__(self):
        return f"{self.sequence}. {self.shift_id} — {self.block_days} hari"
