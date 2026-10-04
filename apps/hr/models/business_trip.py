"""
Business Trip — perjalanan dinas resmi seorang pegawai.

Kontraknya `docs/claude/hr/business-trip.md` (BT-0B, disetujui). Tiga
batas yang menentukan bentuk berkas ini:

* **Bukan Travel Request.** TR adalah kepulangan pegawai roster/site
  (field break dan cuti). Business Trip adalah tugas resmi perusahaan.
  Siapa yang boleh mengajukan yang mana ditentukan Employee Group
  (`business_trip_applicable` / `field_break_applicable`), bukan kode.
* **Bukan Visitor Request.** Pegawai yang dinas ke site tidak dibuatkan
  Visitor Request; satu transaksi bisnis = satu dokumen sumber.
* **Bukan fakta presensi atau payroll.** Dokumen ini hanya menyatakan
  izin berada di luar lokasi kerjanya. Presensi (BT-3) yang membacanya;
  tidak ada kolom uang, uang muka, penyelesaian, atau akun di sini.

Organisasi pegawai **disalin** ke dokumen (company … cost center).
`OrganizationAssignment` hanya menyimpan penempatan saat ini, jadi
perjalanan yang sudah terjadi harus tetap terbaca milik unit yang
memilikinya waktu itu — bukan ikut pindah saat pegawainya dimutasi.
Salinannya diperbarui selama dokumen masih bisa disunting dan dibekukan
saat diajukan.

Dokumen yang sudah disetujui **tidak pernah disunting**. Perubahan
material = batalkan + dokumen pengganti (`supersedes`, tipe
`replacement`); perpanjangan = dokumen lanjutan (`extension`); pulang
lebih awal = `actual_return_datetime` saat menyelesaikan.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel
from apps.uploads.models.uploaded_file import UploadedFile


class BusinessTripStatus(models.TextChoices):
    """
    Tanpa status "sedang ditinjau".

    Visitor dan Attendance Permission punya UNDER_REVIEW/IN_REVIEW yang
    hanya berpindah lewat tombol di layarnya sendiri — kotak masuk
    generik melewatinya (temuan BT-1). Dokumen ini sengaja tidak punya
    status antara, jadi kedua jalur persetujuan menghasilkan keadaan
    yang persis sama. Kemajuan alurnya dibaca dari blok `approval`.

    `SETTLED` sengaja **belum** ada: nilainya dicadangkan untuk saat
    uang muka/penyelesaian perjalanan benar-benar dibangun (DEFERRED).
    """

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    ON_TRIP = "on_trip", "On Trip"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


# Isinya masih boleh diubah pengajunya.
BUSINESS_TRIP_EDITABLE_STATUSES = [
    BusinessTripStatus.DRAFT,
    BusinessTripStatus.REJECTED,
]


# Dokumen yang sudah **mengklaim** tanggalnya — dipakai penjagaan
# tumpang-tindih (Business Trip lain dan Travel Request timbal balik).
# DRAFT tidak ikut: draf bukan klaim, dan menolaknya berarti pengaju
# tidak bisa menyiapkan dua kemungkinan jadwal.
BUSINESS_TRIP_CLAIMING_STATUSES = [
    BusinessTripStatus.SUBMITTED,
    BusinessTripStatus.APPROVED,
    BusinessTripStatus.ON_TRIP,
    BusinessTripStatus.COMPLETED,
]


# Dokumen yang **berlaku** sebagai izin berada di luar lokasi kerja.
# Belum dibaca siapa pun di BT-2; presensi (BT-3) dan pos jaga (BT-4)
# yang akan membacanya — satu daftar, bukan tiga salinan.
BUSINESS_TRIP_COVERAGE_STATUSES = [
    BusinessTripStatus.APPROVED,
    BusinessTripStatus.ON_TRIP,
    BusinessTripStatus.COMPLETED,
]


class BusinessTripPurpose(models.TextChoices):
    """
    Kosakata tertutup, bukan master (keputusan BT-0B).

    `VisitPurpose` sengaja tidak dipakai: isinya alasan **tamu** datang
    (vendor, pengiriman, wawancara) dan kolom `requires_approval`-nya
    semantik alur Visitor. Nilainya string stabil, jadi kalau kelak
    tenant butuh daftarnya sendiri, promosi ke master cukup pemetaan.
    """

    DUTY = "duty", "Official Duty"
    SITE_VISIT = "site_visit", "Site Visit"
    MEETING = "meeting", "Meeting"
    TRAINING = "training", "Training"
    AUDIT = "audit", "Audit / Inspection"
    OTHER = "other", "Other"


class BusinessTripDestinationType(models.TextChoices):
    INTERNAL_LOCATION = "internal_location", "Company Location"
    EXTERNAL_DOMESTIC = "external_domestic", "External — Domestic"
    EXTERNAL_INTERNATIONAL = (
        "external_international",
        "External — International",
    )


class BusinessTripLinkType(models.TextChoices):
    """
    Kenapa sebuah dokumen menunjuk dokumen lain lewat `supersedes`.

    * `replacement` — perubahan material sebelum berangkat: dokumen
      lamanya dibatalkan, yang ini penggantinya.
    * `extension` — perpanjangan: dokumen lanjutan yang dimulai sesudah
      cakupan dokumen lamanya berakhir.
    """

    REPLACEMENT = "replacement", "Replacement"
    EXTENSION = "extension", "Extension"


class BusinessTrip(BaseModel):
    document_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    request_date = models.DateField()

    # Yang berangkat. Subjek alur persetujuan dan subjek cakupan data.
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="business_trips",
    )

    # Yang mengetik atas namanya — bisa orangnya sendiri, bisa admin.
    requester = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requested_business_trips",
    )

    # ------------------------------------------------------------------
    # Salinan organisasi (lihat docstring modul)
    # ------------------------------------------------------------------

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
        help_text="Lokasi kerja pegawai saat dokumen diajukan.",
    )

    division = models.ForeignKey(
        "administration.Division",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    section = models.ForeignKey(
        "administration.Section",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    position = models.ForeignKey(
        "administration.Position",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    cost_center = models.ForeignKey(
        "administration.CostCenter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    # ------------------------------------------------------------------
    # Rute
    # ------------------------------------------------------------------

    origin_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips_from",
        help_text="Bawaannya lokasi kerja pegawai.",
    )

    destination_type = models.CharField(
        max_length=30,
        choices=BusinessTripDestinationType.choices,
    )

    # Wajib untuk tujuan lokasi perusahaan. Pos jaga (BT-4) membaca
    # kolom ini.
    destination_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips_to",
    )

    destination_city = models.ForeignKey(
        "administration.City",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    destination_country = models.ForeignKey(
        "administration.Country",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trips",
    )

    destination_detail = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Tempat, pelanggan, atau alamat tujuan.",
    )

    purpose_category = models.CharField(
        max_length=20,
        choices=BusinessTripPurpose.choices,
    )

    purpose = models.TextField(
        help_text="Uraian tugas yang dijalankan selama perjalanan.",
    )

    # ------------------------------------------------------------------
    # Tanggal
    # ------------------------------------------------------------------

    departure_datetime = models.DateTimeField()
    return_datetime = models.DateTimeField()

    # Diisi saat berangkat / selesai. Pulang lebih awal dibaca dari
    # `actual_return_datetime` — rencana aslinya tidak ditimpa.
    actual_departure_datetime = models.DateTimeField(null=True, blank=True)
    actual_return_datetime = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Keterlacakan perubahan sesudah disetujui
    # ------------------------------------------------------------------

    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    supersede_type = models.CharField(
        max_length=20,
        choices=BusinessTripLinkType.choices,
        blank=True,
        default="",
    )

    # ------------------------------------------------------------------
    # Status dan jejak waktu
    # ------------------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=BusinessTripStatus.choices,
        default=BusinessTripStatus.DRAFT,
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    departed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    cancelled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    cancellation_reason = models.TextField(blank=True, default="")

    notes = models.TextField(blank=True, default="")

    attachment = models.OneToOneField(
        UploadedFile,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "hr_business_trip"

        verbose_name = "Business Trip"
        verbose_name_plural = "Business Trips"

        ordering = ["-departure_datetime", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_business_trip_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "departure_datetime"],
                name="idx_btrip_employee_departure",
            ),
            models.Index(
                fields=["status", "departure_datetime"],
                name="idx_btrip_status_departure",
            ),
            models.Index(
                fields=["destination_location", "departure_datetime"],
                name="idx_btrip_destination",
            ),
        ]

        # Membatalkan perjalanan orang lain, atau perjalanan yang sudah
        # berangkat. Pegawainya sendiri boleh membatalkan perjalanannya
        # sebelum tanggal berangkat tanpa izin ini.
        permissions = [
            (
                "cancel_businesstrip",
                "Can cancel any business trip, including after departure",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_number or self.pk} - {self.employee_id}"

    @property
    def is_editable(self) -> bool:
        return self.status in BUSINESS_TRIP_EDITABLE_STATUSES

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.departure_datetime
            and self.return_datetime
            and self.return_datetime <= self.departure_datetime
        ):
            errors["return_datetime"] = (
                "Waktu kembali harus sesudah waktu berangkat."
            )

        kind = self.destination_type

        if kind == BusinessTripDestinationType.INTERNAL_LOCATION:
            if not self.destination_location_id:
                errors["destination_location"] = (
                    "Pilih lokasi perusahaan yang dituju."
                )
        elif kind in (
            BusinessTripDestinationType.EXTERNAL_DOMESTIC,
            BusinessTripDestinationType.EXTERNAL_INTERNATIONAL,
        ):
            if self.destination_location_id:
                errors["destination_location"] = (
                    "Tujuan eksternal tidak menunjuk lokasi perusahaan."
                )

            if not self.destination_city_id:
                errors["destination_city"] = "Kota tujuan wajib diisi."

            if (
                kind == BusinessTripDestinationType.EXTERNAL_INTERNATIONAL
                and not self.destination_country_id
            ):
                errors["destination_country"] = (
                    "Negara tujuan wajib diisi untuk perjalanan luar "
                    "negeri."
                )

        if not (self.purpose or "").strip():
            errors["purpose"] = "Uraian tugas wajib diisi."

        if self.supersedes_id:
            if self.pk and self.supersedes_id == self.pk:
                errors["supersedes"] = (
                    "Dokumen tidak bisa menunjuk dirinya sendiri."
                )

            if not self.supersede_type:
                errors["supersede_type"] = (
                    "Sebutkan hubungannya: pengganti atau perpanjangan."
                )
        elif self.supersede_type:
            errors["supersedes"] = (
                "Pilih dokumen yang diganti atau diperpanjang."
            )

        if (
            self.location_id
            and self.company_id
            and self.location.company_id != self.company_id
        ):
            errors["location"] = (
                "Location tidak termasuk dalam Company dokumen ini."
            )

        if errors:
            raise ValidationError(errors)


class BusinessTripLeg(BaseModel):
    """
    Satu ruas perjalanan — bentuknya sama dengan `TravelArrangement`,
    tapi **tidak** menunjuk Travel Request. Isinya logistik saja dan
    tidak pernah dibaca presensi.

    Hanya bisa diubah selama dokumen induknya masih bisa disunting;
    perubahan logistik sesudah disetujui (nomor tiket yang dibeli HRGA)
    DEFERRED — lihat kontrak §29/BT-2.
    """

    class Direction(models.TextChoices):
        OUTBOUND = "outbound", "Outbound"
        RETURN = "return", "Return"
        INTERMEDIATE = "intermediate", "Intermediate"

    trip = models.ForeignKey(
        BusinessTrip,
        on_delete=models.CASCADE,
        related_name="legs",
    )

    direction = models.CharField(
        max_length=20,
        choices=Direction.choices,
        default=Direction.OUTBOUND,
    )

    sequence = models.PositiveSmallIntegerField(default=1)

    travel_start_date = models.DateField()
    travel_end_date = models.DateField(null=True, blank=True)

    origin = models.CharField(max_length=150, blank=True, default="")
    destination = models.CharField(max_length=150, blank=True, default="")

    transport_mode = models.ForeignKey(
        "administration.TransportMode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trip_legs",
    )

    transport_detail = models.CharField(max_length=150, blank=True, default="")
    ticket_number = models.CharField(max_length=100, blank=True, default="")

    accommodation_needed = models.BooleanField(default=False)

    accommodation_type = models.ForeignKey(
        "administration.AccommodationType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_trip_legs",
    )

    accommodation_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    check_in_date = models.DateField(null=True, blank=True)
    check_out_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_business_trip_leg"

        ordering = ["trip", "sequence", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["trip", "direction", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_business_trip_leg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trip_id} {self.direction} #{self.sequence}"

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.travel_start_date
            and self.travel_end_date
            and self.travel_end_date < self.travel_start_date
        ):
            errors["travel_end_date"] = (
                "Tanggal tiba tidak boleh sebelum tanggal berangkat."
            )

        if self.accommodation_needed:
            if not self.check_in_date:
                errors["check_in_date"] = (
                    "Check-in wajib diisi kalau akomodasi dibutuhkan."
                )

            if not self.check_out_date:
                errors["check_out_date"] = (
                    "Check-out wajib diisi kalau akomodasi dibutuhkan."
                )

        if (
            self.check_in_date
            and self.check_out_date
            and self.check_out_date < self.check_in_date
        ):
            errors["check_out_date"] = (
                "Check-out tidak boleh sebelum check-in."
            )

        if errors:
            raise ValidationError(errors)
