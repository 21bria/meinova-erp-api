"""
Visitor Management — tamu yang datang ke kantor atau site.

Tiga model, dan pembagiannya menjawab tiga pertanyaan yang berbeda:

* ``ExternalVisitor`` — **siapa** tamunya. Master, bukan teks bebas di
  dokumen: tamu yang pernah datang harus bisa dipanggil lagi tanpa
  mengetik ulang nomor KTP dan nama perusahaannya. Vendor yang datang
  dua belas kali setahun mengetik identitasnya sekali.
* ``VisitorRequest`` — **satu kunjungan**: kapan, ke mana, ditemui
  siapa, perlu tiket dan penginapan atau tidak, dan bagaimana
  persetujuannya berjalan.
* ``VisitorPass`` — **kartu yang dipegang tamunya** selama di lokasi.
  Model tersendiri, bukan kolom di request, karena satu kunjungan
  panjang bisa menerbitkan lebih dari satu kartu (hilang, rusak,
  diperpanjang) dan nomor kartu yang tercetak harus tetap menunjuk
  kartu yang itu.

**Sejak BT-2A Visitor Request hanya untuk orang luar.** Pegawai yang
berkunjung ke HO atau site lain sedang dinas, dan dokumennya Business
Trip — satu perjalanan, satu dokumen sumber. `VisitorType.INTERNAL` dan
kolom `employee` tetap ada **hanya** supaya dokumen lama tetap terbaca
dan bisa dituntaskan (check-in/out, no-show); dokumen baru, suntingan,
dan pengajuan internal ditolak `VisitorRequestService.assert_external_only`
dan `submit`. Pegawai tetap sah sebagai `host_employee` dan `requester`.

Dokumen internal lama menunjuk `Employee` apa adanya, bukan salinan di
master tamu, dan `clean()` tetap menegakkan bahwa satu dokumen menunjuk
**salah satu** dari dua kolom.

Batas yang perlu disadari soal status ``UNDER_REVIEW``: engine approval
di codebase ini sengaja tidak punya hook per-step (`WorkflowStep` tidak
punya efek samping sendiri; satu-satunya callback adalah `on_complete`
yang jalan saat **seluruh** alur berhenti). Jadi perpindahan
SUBMITTED → UNDER_REVIEW hanya terjadi lewat tombol Approve di layar
Visitor Request, tempat service ini memang dilewati. Keputusan yang
diambil dari **kotak masuk generik** membiarkan statusnya SUBMITTED
sampai meja terakhir. Keduanya berarti "sedang berjalan" dan tidak ada
aturan bisnis yang membedakannya — yang membedakan cuma seberapa
terbaca kemajuannya di layar daftar.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class VisitorType(models.TextChoices):
    INTERNAL = "internal", "Internal"
    EXTERNAL = "external", "External"


class IdentityType(models.TextChoices):
    """
    Jenis kartu identitas.

    `TextChoices`, bukan master referensi — daftarnya ditentukan negara,
    bukan klien, dan tidak ada tenant yang perlu menambah jenis kartu
    identitas baru tanpa menunggu rilis. Bedanya dengan `VisitPurpose`
    yang memang berbeda per klien.
    """

    KTP = "ktp", "KTP"
    PASSPORT = "passport", "Passport"
    SIM = "sim", "SIM"
    KITAS = "kitas", "KITAS / KITAP"
    OTHER = "other", "Other"


class VisitorRequestStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    COMPLETED = "completed", "Completed"


# Status yang berarti dokumennya sedang berjalan di alur persetujuan.
# Dipakai penjagaan sunting dan penjagaan pengajuan ganda — dua tempat
# yang harus memakai daftar yang sama, kalau tidak dokumen yang sedang
# menunggu tetap bisa disunting lewat salah satunya.
VISITOR_OPEN_STATUSES = {
    VisitorRequestStatus.SUBMITTED,
    VisitorRequestStatus.UNDER_REVIEW,
}


# Status yang isinya masih boleh diubah pengajunya.
VISITOR_EDITABLE_STATUSES = {
    VisitorRequestStatus.DRAFT,
    VisitorRequestStatus.REJECTED,
}


class VisitorArrivalStatus(models.TextChoices):
    EXPECTED = "expected", "Expected"
    ARRIVED = "arrived", "Arrived"
    CHECKED_IN = "checked_in", "Checked In"
    CHECKED_OUT = "checked_out", "Checked Out"
    NO_SHOW = "no_show", "No Show"


class VisitorPassStatus(models.TextChoices):
    ISSUED = "issued", "Issued"
    RETURNED = "returned", "Returned"
    EXPIRED = "expired", "Expired"
    LOST = "lost", "Lost"


class ExternalVisitor(BaseModel):
    """
    Tamu dari luar perusahaan.

    Ini yang membuat "tamu yang pernah datang bisa dicari lagi" mungkin.
    Tanpa master ini, satu-satunya tempat menyimpan nama dan nomor KTP
    tamu adalah kolom teks di dokumen kunjungan — dan sesudah itu tidak
    ada satu pun cara menjawab "vendor ini sudah berapa kali ke site",
    karena dua puluh dokumen memuat dua puluh ejaan nama yang berbeda.
    """

    # Auto dari deret hr/external_visitor (VIS-000001). Boleh kosong:
    # deret yang belum diseed tidak boleh membuat tamu gagal disimpan —
    # pelajaran yang sama dengan nomor Travel Request.
    visitor_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    full_name = models.CharField(max_length=150)

    identity_type = models.CharField(
        max_length=20,
        choices=IdentityType.choices,
        default=IdentityType.KTP,
    )

    identity_number = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text=(
            "Nomor KTP/paspor. Dipakai memeriksa tamu ganda — dua baris "
            "dengan nomor yang sama ditolak."
        ),
    )

    gender = models.ForeignKey(
        "administration.Gender",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_visitors",
    )

    date_of_birth = models.DateField(null=True, blank=True)

    nationality = models.ForeignKey(
        "administration.Nationality",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_visitors",
    )

    # ------------------------------------------------------------------
    # Kontak
    # ------------------------------------------------------------------

    email = models.EmailField(blank=True, default="")

    phone = models.CharField(max_length=50, blank=True, default="")

    mobile = models.CharField(max_length=50, blank=True, default="")

    # ------------------------------------------------------------------
    # Asal
    # ------------------------------------------------------------------

    # Nama perusahaan tamu sengaja teks bebas, bukan FK ke master
    # vendor: modul procurement masih kerangka kosong, dan memaksa tiap
    # perusahaan tamu didaftarkan lebih dulu akan menghentikan satpam
    # yang cuma mau mencatat kedatangan.
    organization_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Perusahaan atau instansi asal tamu.",
    )

    position = models.CharField(max_length=100, blank=True, default="")

    city = models.ForeignKey(
        "administration.City",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_visitors",
    )

    country = models.ForeignKey(
        "administration.Country",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_visitors",
    )

    address = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Tambahan
    # ------------------------------------------------------------------

    emergency_contact_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    emergency_contact_phone = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    notes = models.TextField(blank=True, default="")

    # Daftar hitam. Bukan `is_active` — yang itu berarti "baris ini
    # tidak dipakai lagi", sementara ini berarti "orangnya tidak boleh
    # masuk", dan keduanya butuh jawaban berbeda saat satpam mencari
    # namanya di gerbang.
    is_blacklisted = models.BooleanField(default=False)

    blacklist_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_external_visitor"

        ordering = ["full_name"]

        constraints = [
            models.UniqueConstraint(
                fields=["visitor_number"],
                condition=Q(is_deleted=False) & ~Q(visitor_number=""),
                name="uniq_active_hr_external_visitor_number",
            ),
            # Dikondisikan ke is_deleted **dan** ke nilai tidak kosong:
            # tamu yang identitasnya belum lengkap (dicatat satpam
            # tengah malam) tetap harus bisa disimpan, dan baris kosong
            # tidak boleh saling mengunci.
            models.UniqueConstraint(
                fields=["identity_number"],
                condition=Q(is_deleted=False) & ~Q(identity_number=""),
                name="uniq_active_hr_external_visitor_identity",
            ),
        ]

        indexes = [
            models.Index(
                fields=["full_name"],
                name="idx_external_visitor_name",
            ),
        ]

    @property
    def visit_count(self) -> int:
        """
        Berapa kali tamu ini pernah diundang.

        Membaca anotasi `visit_total` kalau viewset menyediakannya, dan
        menghitung sendiri kalau tidak. Dua alasan properti ini ada di
        model alih-alih cuma di serializer: respons POST/PATCH datang
        dari service dan **tidak** beranotasi, dan export CSV membaca
        instance — bukan serializer — jadi kolomnya akan kosong di
        seluruh baris tanpa ada satu pun pesan.

        Namanya sengaja berbeda dari anotasinya. Anotasi bernama sama
        dengan properti ditempelkan Django lewat `setattr` dan
        menjatuhkan endpoint-nya dengan "has no setter" — jebakan yang
        sudah kena dua kali di codebase ini (`participant_count`,
        `candidate_count`).
        """
        annotated = getattr(self, "visit_total", None)

        if annotated is not None:
            return annotated

        return self.visitor_requests.filter(is_deleted=False).count()

    def clean(self):
        super().clean()

        errors = {}

        if self.is_blacklisted and not self.blacklist_reason.strip():
            errors["blacklist_reason"] = (
                "Alasan wajib diisi kalau tamu ditandai blacklist. "
                "Satpam di gerbang harus tahu kenapa seseorang ditolak."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        label = self.visitor_number or "VIS"

        if self.organization_name:
            return f"{label} — {self.full_name} ({self.organization_name})"

        return f"{label} — {self.full_name}"


class VisitorRequest(BaseModel):
    """
    Satu kunjungan yang diajukan, disetujui, lalu dijalani.

    Kolom perjalanan dan akomodasi ada **di dokumen ini**, bukan
    menumpang `TravelRequest` milik pegawai. Keduanya terlihat mirip di
    layar dan sangat berbeda isinya: TR pegawai bersandar pada Point of
    Hire, blok roster, dan saldo cuti — tiga hal yang tidak dipunyai
    tamu sama sekali. Menumpangkannya berarti separuh kolom TR selalu
    kosong untuk tamu, dan separuh aturannya harus dimatikan dengan
    `if`.
    """

    document_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    request_date = models.DateField()

    # Pegawai yang mengajukan. Bukan `created_by` (yang mengetik):
    # sekretaris lazim mengetikkan kunjungan untuk direkturnya, dan yang
    # tercetak di dokumen harus pemohonnya.
    requester = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="visitor_requests",
    )

    # Denormalisasi dari OrganizationAssignment pemohon, pola yang sama
    # dengan EmployeeLeave/TravelRequest — ini yang dibaca
    # cakupan data, dan tanpa kolomnya penyaringan per site
    # harus menembus dua relasi di setiap query.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
    )

    # Lokasi yang dikunjungi. Sengaja **satu** kolom, bukan "Location"
    # di kepala dokumen plus "Visit Location" di bagian kunjungan:
    # keduanya selalu tempat yang sama, dan dua kolom untuk satu fakta
    # cepat atau lambat berbeda isinya.
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
        help_text="Lokasi/site yang dikunjungi.",
    )

    # ------------------------------------------------------------------
    # Siapa tamunya
    # ------------------------------------------------------------------

    visitor_type = models.CharField(
        max_length=20,
        choices=VisitorType.choices,
        default=VisitorType.EXTERNAL,
    )

    # Diisi kalau internal. Menunjuk Employee apa adanya — tidak ada
    # salinan pegawai di master tamu.
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visits_as_visitor",
    )

    # Diisi kalau external.
    external_visitor = models.ForeignKey(
        ExternalVisitor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
    )

    # ------------------------------------------------------------------
    # Kunjungannya
    # ------------------------------------------------------------------

    visit_purpose = models.ForeignKey(
        "administration.VisitPurpose",
        on_delete=models.PROTECT,
        related_name="visitor_requests",
    )

    visit_type = models.ForeignKey(
        "administration.VisitType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
    )

    host_employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="hosted_visits",
        help_text="Pegawai yang bertanggung jawab menerima tamu.",
    )

    visit_start_date = models.DateField()

    visit_start_time = models.TimeField(null=True, blank=True)

    visit_end_date = models.DateField()

    visit_end_time = models.TimeField(null=True, blank=True)

    number_of_visitors = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Jumlah orang dalam rombongan, termasuk tamu utama di atas."
        ),
    )

    remarks = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=VisitorRequestStatus.choices,
        default=VisitorRequestStatus.DRAFT,
    )

    # ------------------------------------------------------------------
    # Perjalanan
    # ------------------------------------------------------------------

    travel_required = models.BooleanField(default=False)

    travel_from = models.CharField(max_length=150, blank=True, default="")

    travel_to = models.CharField(max_length=150, blank=True, default="")

    departure_date = models.DateField(null=True, blank=True)
    departure_time = models.TimeField(null=True, blank=True)

    return_date = models.DateField(null=True, blank=True)
    return_time = models.TimeField(null=True, blank=True)

    transport_mode = models.ForeignKey(
        "administration.TransportMode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
    )

    ticket_required = models.BooleanField(default=False)

    ticket_number = models.CharField(max_length=100, blank=True, default="")

    # ------------------------------------------------------------------
    # Akomodasi
    # ------------------------------------------------------------------

    accommodation_required = models.BooleanField(default=False)

    accommodation_type = models.ForeignKey(
        "administration.AccommodationType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visitor_requests",
    )

    accommodation_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Nama hotel/mess, mis. Hotel Bukit Pelangi.",
    )

    accommodation_checkin = models.DateField(null=True, blank=True)
    accommodation_checkout = models.DateField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Penjemputan
    # ------------------------------------------------------------------

    pickup_required = models.BooleanField(default=False)

    pickup_point = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Bandara/pelabuhan tempat tamu dijemput.",
    )

    dropoff_point = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    vehicle_required = models.BooleanField(default=False)

    driver_required = models.BooleanField(default=False)

    travel_remarks = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Kedatangan
    # ------------------------------------------------------------------

    arrival_status = models.CharField(
        max_length=20,
        choices=VisitorArrivalStatus.choices,
        default=VisitorArrivalStatus.EXPECTED,
    )

    expected_arrival = models.DateTimeField(null=True, blank=True)

    checked_in_at = models.DateTimeField(null=True, blank=True)

    checked_in_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visitor_checkins",
    )

    check_in_gate = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Pos jaga tempat tamu masuk.",
    )

    check_in_remarks = models.TextField(blank=True, default="")

    checked_out_at = models.DateTimeField(null=True, blank=True)

    checked_out_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visitor_checkouts",
    )

    check_out_remarks = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_visitor_request"

        ordering = ["-visit_start_date", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_hr_visitor_request_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["visit_start_date"],
                name="idx_visitor_request_start",
            ),
            models.Index(
                fields=["status"],
                name="idx_visitor_request_status",
            ),
            models.Index(
                fields=["arrival_status"],
                name="idx_visitor_request_arrival",
            ),
        ]

    # ------------------------------------------------------------------
    # Turunan
    # ------------------------------------------------------------------

    @property
    def visitor_name(self) -> str:
        if self.visitor_type == VisitorType.INTERNAL:
            return self.employee.full_name if self.employee_id else ""

        return (
            self.external_visitor.full_name
            if self.external_visitor_id
            else ""
        )

    @property
    def visitor_organization(self) -> str:
        """
        Perusahaan asal tamu — untuk internal, perusahaan tempatnya
        bekerja; untuk eksternal, perusahaan yang ditulis di masternya.
        """
        if self.visitor_type == VisitorType.INTERNAL:
            if not self.employee_id:
                return ""

            organization = getattr(self.employee, "organization", None)
            company = getattr(organization, "company", None)

            return company.name if company else ""

        if not self.external_visitor_id:
            return ""

        return self.external_visitor.organization_name

    @property
    def expected_duration_days(self) -> int | None:
        if not self.visit_start_date or not self.visit_end_date:
            return None

        return (self.visit_end_date - self.visit_start_date).days + 1

    @property
    def is_editable(self) -> bool:
        return self.status in VISITOR_EDITABLE_STATUSES

    def clean(self):
        super().clean()

        errors = {}

        # BR-02 / BR-03. Diperiksa di model, bukan cuma di serializer:
        # importer, seed, dan shell tidak lewat serializer, dan dokumen
        # tanpa tamu tidak bisa dijalankan siapa pun.
        if self.visitor_type == VisitorType.INTERNAL:
            if not self.employee_id:
                errors["employee"] = (
                    "Employee wajib dipilih untuk Visitor Type Internal."
                )

            if self.external_visitor_id:
                errors["external_visitor"] = (
                    "Kunjungan internal tidak boleh menunjuk External "
                    "Visitor. Kosongkan salah satunya."
                )

        elif self.visitor_type == VisitorType.EXTERNAL:
            if not self.external_visitor_id:
                errors["external_visitor"] = (
                    "External Visitor wajib dipilih. Buat dulu datanya "
                    "di Visitor Master kalau tamunya belum terdaftar."
                )

            if self.employee_id:
                errors["employee"] = (
                    "Kunjungan eksternal tidak boleh menunjuk Employee. "
                    "Kosongkan salah satunya."
                )

        # BR-05
        if (
            self.visit_start_date
            and self.visit_end_date
            and self.visit_end_date < self.visit_start_date
        ):
            errors["visit_end_date"] = (
                "Visit End tidak boleh lebih awal dari Visit Start."
            )

        # Jam hanya bisa dibandingkan kalau harinya sama — kunjungan
        # dua hari yang mulai jam 4 sore dan selesai jam 9 pagi itu sah.
        if (
            self.visit_start_date
            and self.visit_end_date
            and self.visit_start_date == self.visit_end_date
            and self.visit_start_time
            and self.visit_end_time
            and self.visit_end_time < self.visit_start_time
        ):
            errors["visit_end_time"] = (
                "Visit End Time tidak boleh lebih awal dari Visit Start "
                "Time pada hari yang sama."
            )

        if self.number_of_visitors is not None and self.number_of_visitors < 1:
            errors["number_of_visitors"] = (
                "Number of Visitors minimal 1."
            )

        # BR-07. Kebalikannya (BR-06) sengaja tidak dijaga: kolom travel
        # yang kebetulan terisi lalu Travel Required dimatikan bukan
        # kesalahan yang perlu menghentikan penyimpanan — form sudah
        # menyembunyikannya, dan menghapus isinya diam-diam justru
        # membuang data yang mungkin masih dibutuhkan kalau saklarnya
        # dinyalakan lagi.
        if self.accommodation_required:
            if not self.accommodation_checkin:
                errors["accommodation_checkin"] = (
                    "Check-in wajib diisi kalau akomodasi dibutuhkan."
                )

            if not self.accommodation_checkout:
                errors["accommodation_checkout"] = (
                    "Check-out wajib diisi kalau akomodasi dibutuhkan."
                )

        if (
            self.accommodation_checkin
            and self.accommodation_checkout
            and self.accommodation_checkout < self.accommodation_checkin
        ):
            errors["accommodation_checkout"] = (
                "Check-out tidak boleh lebih awal dari Check-in."
            )

        if self.travel_required:
            if not self.departure_date:
                errors["departure_date"] = (
                    "Departure Date wajib diisi kalau perjalanan "
                    "dibutuhkan."
                )

        if (
            self.departure_date
            and self.return_date
            and self.return_date < self.departure_date
        ):
            errors["return_date"] = (
                "Return Date tidak boleh lebih awal dari Departure Date."
            )

        if (
            self.location_id
            and self.company_id
            and self.location.company_id != self.company_id
        ):
            errors["location"] = (
                "Location tidak termasuk dalam Company yang dipilih."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.document_number or 'VR'} — "
            f"{self.visitor_name or 'Visitor'} "
            f"({self.visit_start_date})"
        )


class VisitorPass(BaseModel):
    """
    Kartu tamu.

    Model tersendiri, bukan satu kolom nomor di `VisitorRequest`: kartu
    bisa terbit lebih dari sekali untuk kunjungan yang sama (hilang,
    rusak, kunjungan multi-hari yang kartunya dikembalikan tiap sore),
    dan riwayat "kartu nomor berapa dipegang siapa kapan" adalah hal
    pertama yang ditanyakan saat ada kartu tidak kembali.
    """

    request = models.ForeignKey(
        VisitorRequest,
        on_delete=models.CASCADE,
        related_name="passes",
    )

    pass_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    valid_from = models.DateField()
    valid_until = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=VisitorPassStatus.choices,
        default=VisitorPassStatus.ISSUED,
    )

    issued_at = models.DateTimeField(null=True, blank=True)

    issued_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_visitor_passes",
    )

    returned_at = models.DateTimeField(null=True, blank=True)

    returned_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returned_visitor_passes",
    )

    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_visitor_pass"

        ordering = ["-issued_at", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["pass_number"],
                condition=Q(is_deleted=False) & ~Q(pass_number=""),
                name="uniq_active_hr_visitor_pass_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["status"],
                name="idx_visitor_pass_status",
            ),
        ]

    @property
    def is_open(self) -> bool:
        """Kartu yang masih dipegang tamunya."""
        return self.status == VisitorPassStatus.ISSUED

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.valid_from
            and self.valid_until
            and self.valid_until < self.valid_from
        ):
            errors["valid_until"] = (
                "Valid Until tidak boleh lebih awal dari Valid From."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.pass_number or f"VP #{self.pk}"
