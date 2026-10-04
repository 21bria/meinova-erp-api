"""
Travel Request — pengajuan satu kepulangan pegawai site.

Bedanya dengan `SiteRotation` di sebelah, dan ini yang sempat tertukar:
`SiteRotation` adalah **jadwal kerja setahun**, alat perencanaan yang
menyebutkan kapan seseorang on dan off sepanjang tahun. Yang di sini
adalah **dokumen pengajuan** untuk satu kepulangan: Ahmad off 22
September sampai 5 Oktober, isinya tujuh hari Field Break lalu tujuh
hari Cuti Tahunan, berangkat dengan penerbangan tanggal 20. Itu yang
diajukan, disetujui, dan dibelikan tiket — dan satu orang punya banyak
TR dalam setahun.

Roster bukan syarat. Pegawai site yang belum punya dokumen jadwal tetap
bisa mengajukan; kalau jadwalnya ada, blok off-nya bisa ditunjuk lewat
`rotation_period` dan tanggalnya terisi dari sana.

Tiga model, sejajar dengan tiga tabel di formulir kertasnya:

* ``TravelRequest``        — kepala dokumen
* ``TravelRequestPurpose`` — tabel "Travel Purpose"
* ``TravelArrangement``    — tabel "Travel Arrangement" + "Accommodation"
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class TravelRequestStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


# Status yang membuat satu blok jadwal dianggap **sudah punya** Travel
# Request, dipakai menolak pembuatan TR kedua dari blok yang sama.
#
# Tiga-tiganya masih hidup: DRAFT sedang diisi, SUBMITTED sedang
# dinilai, APPROVED sudah menerbitkan cuti dan mungkin tiket. Menerbitkan
# TR kedua untuk kepulangan yang sama membuat dua dokumen memperebutkan
# satu blok off — dan kalau dua-duanya disetujui, `issue_leave_records`
# memotong saldo cutinya dua kali.
#
# REJECTED dan CANCELLED tidak ikut: dokumennya sudah selesai, dan
# pengajuan yang ditolak harus bisa diajukan ulang untuk blok yang sama.
TRAVEL_REQUEST_ACTIVE_STATUSES = [
    TravelRequestStatus.DRAFT,
    TravelRequestStatus.SUBMITTED,
    TravelRequestStatus.APPROVED,
]


class TravelDirection(models.TextChoices):
    OUTBOUND = "out", "Outbound"
    INBOUND = "in", "Inbound"


class TravelRequest(BaseModel):
    document_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="travel_requests",
    )

    # Didenormalisasi dari OrganizationAssignment aktif, pola yang sama
    # dengan EmployeeLeave/SiteRotation.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="travel_requests",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="travel_requests",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="travel_requests",
    )

    # Blok off pada jadwal roster yang direalisasikan pengajuan ini.
    # Boleh kosong: TR berdiri sendiri, dan pegawai yang jadwalnya belum
    # disusun tetap harus bisa mengajukan. Kalau diisi, tanggalnya
    # disalin dari periode itu saat dokumen dibuat.
    #
    # SET_NULL: menghapus dokumen jadwal tidak boleh ikut menghapus
    # pengajuan yang sudah disetujui dan tiketnya sudah dibeli.
    rotation_period = models.ForeignKey(
        "hr.RotationPeriod",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="travel_requests",
    )

    # Rentang off yang diajukan. Baris tujuan di bawah memecahnya jadi
    # beberapa bagian; kolom ini yang dipakai untuk menyaring dan
    # mengurutkan daftar tanpa menembus tabel anak.
    start_date = models.DateField()
    end_date = models.DateField()

    # Dijumlahkan service dari baris tujuan. Disimpan, bukan properti:
    # kolom ini dipakai sebagai kolom tabel yang bisa disortir.
    total_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=TravelRequestStatus.choices,
        default=TravelRequestStatus.DRAFT,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_travel_request"

        ordering = [
            "-start_date",
            "employee",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_travel_request_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "start_date"],
                name="idx_travel_request_emp_date",
            ),
            models.Index(
                fields=["status"],
                name="idx_travel_request_status",
            ),
        ]

    @property
    def departure_date(self):
        """
        Tanggal berangkat **sebenarnya**: etape pertama arah keluar.

        Bukan `start_date`. Kolom itu awal blok off — hari pertama orang
        itu libur di kampungnya — sedangkan berangkatnya satu sampai
        tiga hari sebelumnya, karena etape site → POH memakan hari
        kalender sendiri. Pengingat "berangkat 7 hari lagi" yang
        dihitung dari `start_date` karena itu terkirim saat orangnya
        sudah di kapal.

        Jatuh ke `start_date` selama etapenya belum diketik: TR sah
        disetujui sebelum tiketnya dibeli, dan awal blok off adalah
        perkiraan terbaik yang dimiliki dokumen saat itu.

        Disaring di Python, bukan lewat `.filter()`, supaya pemanggil
        yang sudah mem-prefetch `travels` tidak menembak satu query
        tambahan per dokumen.
        """
        legs = [
            leg
            for leg in self.travels.all()
            if not leg.is_deleted
            and leg.direction == TravelDirection.OUTBOUND
            and leg.travel_start_date
        ]

        if not legs:
            return self.start_date

        return min(leg.travel_start_date for leg in legs)

    @property
    def journey_dates(self):
        """
        Rentang **perjalanan fisik**: `(awal, akhir)`, inklusif.

        `start_date..end_date` adalah blok off — hari orangnya libur di
        kampungnya. Perjalanannya lebih panjang: etape keluar berangkat
        satu sampai tiga hari sebelum `start_date`, dan etape pulang bisa
        tiba sesudah `end_date`. Penjagaan "satu perjalanan fisik = satu
        dokumen" terhadap Business Trip (TR/BT POLICY-1) membaca rentang
        ini, bukan blok off-nya — kalau tidak, Business Trip di hari
        keberangkatan lolos.

        Seluruh etape yang punya tanggal ikut, arah mana pun. Tanpa etape
        (itinerary belum diketik) jatuh ke `start_date..end_date`, jadi
        dokumen lama berperilaku persis seperti sebelumnya. Disaring di
        Python supaya prefetch `travels` kepakai.
        """
        legs = [
            leg
            for leg in self.travels.all()
            if not leg.is_deleted and leg.travel_start_date
        ]

        starts = [self.start_date, *(leg.travel_start_date for leg in legs)]
        ends = [self.end_date, *(leg.arrival_date for leg in legs)]

        return (
            min(day for day in starts if day is not None),
            max(day for day in ends if day is not None),
        )

    @property
    def is_editable(self) -> bool:
        """
        Dokumen yang sedang menunggu persetujuan atau sudah disetujui
        tidak boleh disunting bebas — yang sudah ditandatangani harus
        tetap menunjuk isi yang ditandatangani.
        """
        return self.status in {
            TravelRequestStatus.DRAFT,
            TravelRequestStatus.REJECTED,
        }

    def clean(self):
        super().clean()

        errors = {}

        # Serializer sengaja membolehkan kolom ini kosong supaya service
        # bisa menyalinnya dari blok jadwal. Kalau sampai di sini masih
        # kosong berarti tidak ada blok yang bisa jadi acuan, dan pesan
        # bawaan Django ("This field cannot be null") tidak memberi tahu
        # apa yang harus dilakukan.
        for field_name, label in (
            ("start_date", "Off Start"),
            ("end_date", "Off End"),
        ):
            if getattr(self, field_name) is None:
                errors[field_name] = (
                    f"{label} wajib diisi. Pilih Blok Jadwal supaya "
                    "terisi otomatis dari periode off-nya, atau isi "
                    "manual."
                )

        if (
            self.start_date
            and self.end_date
            and self.end_date < self.start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if (
            self.location_id
            and self.company_id
            and self.location.company_id != self.company_id
        ):
            errors["location"] = (
                "Location tidak termasuk dalam Company yang dipilih."
            )

        # Periode roster milik orang lain akan menampilkan jadwal yang
        # bukan miliknya di kepala dokumen.
        if (
            self.rotation_period_id
            and self.employee_id
            and self.rotation_period.employee_id != self.employee_id
        ):
            errors["rotation_period"] = (
                "Blok jadwal itu milik pegawai lain."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.document_number or 'TR'} — "
            f"{self.employee.employee_number} "
            f"({self.start_date} s/d {self.end_date})"
        )


class TravelRequestPurpose(BaseModel):
    """
    Satu baris di tabel "Travel Purpose".

    Inilah yang membuat satu formulir bisa memuat beberapa alasan
    sekaligus: tujuh hari Field Break lalu tujuh hari Cuti Tahunan
    dalam satu kepulangan. Yang membedakan keduanya
    `RotationPurpose.deducts_leave` — Field Break adalah jatah off
    rosternya sendiri dan tidak memotong saldo apa pun, Cuti Tahunan
    memotong.
    """

    request = models.ForeignKey(
        TravelRequest,
        on_delete=models.CASCADE,
        related_name="purposes",
    )

    sequence = models.PositiveSmallIntegerField()

    purpose = models.ForeignKey(
        "administration.RotationPurpose",
        on_delete=models.PROTECT,
        related_name="travel_request_purposes",
    )

    start_date = models.DateField()
    end_date = models.DateField()

    total_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    # Catatan cuti yang benar-benar memotong saldo. Dibuat service saat
    # pengajuan disetujui, bukan saat diketik — cuti yang belum
    # disetujui tidak boleh sudah mengurangi saldo orang.
    #
    # Sengaja tautan, bukan perhitungan sendiri: `EmployeeLeave` sudah
    # punya kalkulator hari kerja dan penjumlah ulang saldo, dan
    # menyalin logikanya ke sini berarti dua sumber angka untuk cuti
    # yang sama.
    employee_leave = models.ForeignKey(
        "hr.EmployeeLeave",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="travel_request_purposes",
    )

    # Apakah catatan cuti di atas **lahir dari** dokumen ini, atau cuma
    # ditaut ke catatan yang sudah lebih dulu ada.
    #
    # Tautannya sendiri tidak bisa membedakan keduanya:
    # `issue_leave_records` mengisi `employee_leave` untuk dua jalur —
    # cuti yang diterbitkannya sendiri, dan cuti yang sudah dicatat HR
    # di tanggal yang sama lalu diadopsi supaya saldonya tidak
    # terpotong dua kali.
    #
    # Bedanya baru penting saat pembatalan: yang terbit dari dokumen
    # ini ikut dibatalkan, yang cuma diadopsi **tidak** — itu catatan
    # milik HR, cutinya tetap terjadi, dan membatalkannya berarti
    # mengembalikan saldo untuk cuti yang benar-benar diambil.
    leave_issued = models.BooleanField(default=False)

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_travel_request_purpose"

        ordering = [
            "request",
            "start_date",
            "sequence",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["request", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_travel_request_purpose",
            ),
        ]

    @property
    def day_count(self) -> int | None:
        if not self.start_date or not self.end_date:
            return None

        return (self.end_date - self.start_date).days + 1

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.start_date
            and self.end_date
            and self.end_date < self.start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if self.total_days is not None and self.total_days < 0:
            errors["total_days"] = "Total Days tidak boleh negatif."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"#{self.sequence} {self.purpose.name} "
            f"({self.start_date} s/d {self.end_date})"
        )


class TravelArrangement(BaseModel):
    """
    Satu **etape** perjalanan beserta penginapan transitnya.

    Satu arah lazim terdiri dari beberapa etape, dan etapenya berbeda
    per orang karena Point of Hire-nya berbeda:

        Karyawan A (POH Jakarta, 3 hari PP)
          out #1  Jakarta → Sorong   13 Sep
          out #2  Sorong  → Gebe     14 Sep

        Karyawan B (POH Makassar, 2 hari PP)
          out #1  Makassar → Sorong  14 Sep
          out #2  Sorong   → Gebe    14 Sep

    Keduanya tiba di Gebe pada hari yang sama; yang membedakan kapan
    mereka berangkat dari kotanya. Karena itu barisnya per etape, bukan
    per arah: moda, nomor tiket, dan penginapan transitnya masing-masing
    berbeda, dan satu baris per arah memaksa semuanya dipadatkan jadi
    satu kolom teks yang tidak bisa dilaporkan.

    Menggantikan `RotationTravel` yang dulu menempel ke blok jadwal.
    Tanggal penerbangan adalah hal yang **diajukan dan disetujui**,
    bukan hasil rumus jadwal — menyimpannya di dua tempat berarti dua
    tanggal keberangkatan untuk penerbangan yang sama, dan cepat atau
    lambat keduanya berbeda. Jadwal roster kini hanya menghitung
    perkiraan jendela travel untuk ditampilkan, tidak menyimpannya.

    Dua tabel di formulir — "Travel Arrangement" dan "Accommodation" —
    membaca baris yang sama dengan kolom yang berbeda. Akomodasi
    dipisah karena satu tabel berisi delapan belas kolom memaksa orang
    menggulir ke samping hanya untuk melihat kolom yang sedang diisinya.
    """

    request = models.ForeignKey(
        TravelRequest,
        on_delete=models.CASCADE,
        related_name="travels",
    )

    direction = models.CharField(
        max_length=10,
        choices=TravelDirection.choices,
    )

    # Nomor etape di dalam arahnya. Diisi service dengan nomor bebas
    # berikutnya kalau form tidak menyebutkannya — yang mengetik jadwal
    # penerbangan memikirkan rutenya, bukan nomor urut barisnya.
    sequence = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Urutan etape dalam satu arah. 1 = Jakarta → Sorong, "
            "2 = Sorong → Gebe."
        ),
    )

    # Rentang, bukan satu tanggal: perjalanan dari site lazim menginap
    # di kota transit, jadi berangkat dan tiba beda hari.
    travel_start_date = models.DateField()

    travel_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Dikosongkan = tiba di hari yang sama.",
    )

    origin = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Titik berangkat, mis. Gebe.",
    )

    destination = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Titik tujuan, mis. Jakarta.",
    )

    transport_mode = models.ForeignKey(
        "administration.TransportMode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="travel_arrangements",
    )

    transport_detail = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "Nomor penerbangan, nama kapal, atau rute etape. "
            "Mis. GA-642 / KM Sabuk Nusantara."
        ),
    )

    ticket_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    justification = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Alasan perjalanan ini menyimpang dari rotasi normal. "
            "Kosong = perjalanan rutin."
        ),
    )

    is_special_arrangement = models.BooleanField(
        default=False,
    )

    special_arrangement_notes = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    accommodation_needed = models.BooleanField(
        default=False,
    )

    accommodation_type = models.ForeignKey(
        "administration.AccommodationType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="travel_arrangements",
    )

    accommodation_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Nama hotel/mess, mis. Hotel Bukit Pelangi.",
    )

    accommodation_checkin = models.DateField(null=True, blank=True)
    accommodation_checkout = models.DateField(null=True, blank=True)

    accommodation_nights = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    # Hari perjalanan kembali ke site dihitung hari kerja: orang yang
    # tertahan semalam karena kapalnya digeser tetap sedang menjalankan
    # tugas. Bawaannya diturunkan dari arah oleh service, tapi boleh
    # ditimpa — kapal pulang yang delay dua hari juga tanggungan
    # perusahaan, dan itu tidak bisa disimpulkan dari arahnya saja.
    counts_as_work = models.BooleanField(default=False)

    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_travel_arrangement"

        # Kronologis, dengan nomor etape sebagai pemecah seri: dua
        # etape yang berangkat di hari yang sama (Makassar → Sorong →
        # Gebe) harus tetap terbaca berurutan.
        ordering = [
            "request",
            "travel_start_date",
            "direction",
            "sequence",
        ]

        constraints = [
            # Nomor etape unik di dalam arahnya, bukan satu baris per
            # arah. Pembatasan yang lama memaksa rute bersambung
            # (Jakarta → Sorong → Gebe) dipadatkan jadi satu baris,
            # padahal tiap etape punya moda, nomor tiket, dan
            # penginapan transitnya sendiri.
            models.UniqueConstraint(
                fields=["request", "direction", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_travel_arrangement_leg",
            ),
        ]

        indexes = [
            models.Index(
                fields=["travel_start_date"],
                name="idx_travel_arrangement_start",
            ),
        ]

    @property
    def arrival_date(self):
        return self.travel_end_date or self.travel_start_date

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.travel_start_date
            and self.travel_end_date
            and self.travel_end_date < self.travel_start_date
        ):
            errors["travel_end_date"] = (
                "Arrival Date tidak boleh lebih awal dari "
                "Departure Date."
            )

        if self.accommodation_needed:
            if not self.accommodation_checkin:
                errors["accommodation_checkin"] = (
                    "Check-in wajib diisi jika akomodasi dibutuhkan."
                )

            if not self.accommodation_checkout:
                errors["accommodation_checkout"] = (
                    "Check-out wajib diisi jika akomodasi dibutuhkan."
                )

        if (
            self.accommodation_checkin
            and self.accommodation_checkout
            and self.accommodation_checkout < self.accommodation_checkin
        ):
            errors["accommodation_checkout"] = (
                "Check-out tidak boleh lebih awal dari Check-in."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        route = " → ".join(
            part
            for part in (self.origin, self.destination)
            if part
        )

        return (
            f"{self.get_direction_display()} #{self.sequence or '-'} "
            f"{route or self.travel_start_date}"
        )
