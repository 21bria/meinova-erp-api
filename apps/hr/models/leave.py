from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel
from apps.uploads.models import UploadedFile

from .employee import Employee


class LeaveStatus(models.TextChoices):
    """
    Dua jalur hidup berdampingan di satu tabel, dan itu disengaja.

    **Pencatatan** — cuti yang sudah disetujui di luar sistem, atau yang
    diterbitkan Travel Request, masuk langsung sebagai RECORDED. Tidak
    lewat approval sama sekali; HR yang mengetiknya sudah tahu cuti itu
    terjadi.

    **Pengajuan** — pegawai membuat sendiri (DRAFT), menekan Submit
    (SUBMITTED), lalu alurnya menentukan APPROVED atau REJECTED.

    Memisahkannya jadi dua tabel akan membuat kartu cuti seseorang harus
    dijumlahkan dari dua sumber, dan pegawai yang pindah dari HO ke site
    jadi kasus khusus permanen.
    """

    RECORDED = "recorded", "Recorded"
    CANCELLED = "cancelled", "Cancelled"

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


# Status yang benar-benar memotong saldo. RECORDED = tercatat terjadi,
# APPROVED = disetujui lewat alur. Yang masih SUBMITTED **belum** boleh
# memotong apa pun: cuti yang belum disetujui tidak boleh sudah
# mengurangi jatah orang, dan kalau ditolak tidak ada yang perlu
# dikembalikan.
LEAVE_DEDUCTING_STATUSES = [
    LeaveStatus.RECORDED,
    LeaveStatus.APPROVED,
]


# Status yang benar-benar "memesan" tanggal, dipakai pengecekan
# tumpang tindih. SUBMITTED ikut walau belum memotong saldo: dua
# pengajuan di tanggal yang sama tetap salah, dan yang kedua akan
# memotong ganda begitu dua-duanya disetujui. DRAFT belum jadi apa-apa;
# REJECTED/CANCELLED sudah selesai — keduanya tidak boleh menghalangi
# pengajuan ulang di tanggal yang sama.
LEAVE_BLOCKING_STATUSES = [
    LeaveStatus.RECORDED,
    LeaveStatus.APPROVED,
    LeaveStatus.SUBMITTED,
]


# Status yang isinya masih boleh disunting pengaju.
LEAVE_EDITABLE_STATUSES = [
    LeaveStatus.DRAFT,
    LeaveStatus.RECORDED,
    LeaveStatus.REJECTED,
    LeaveStatus.CANCELLED,
]


class EmployeeLeave(BaseModel):
    # Nomor dari deret `hr/leave` (prefix LV) — diisi
    # `EmployeeLeaveService.apply_document_number` saat record dibuat,
    # untuk **semua** jalur: diajukan pegawai, dicatat HR, maupun
    # terbitan Travel Request. Satu deret untuk semua supaya tiap
    # catatan cuti bisa dirujuk di layar monitoring.
    #
    # Boleh kosong: data lama tidak dinomori ulang (dokumen tercetak
    # yang sudah beredar tidak boleh berubah nomornya), dan tenant yang
    # deretnya belum diseed tetap harus bisa mencatat cuti.
    document_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leaves",
    )

    # Organisasi didenormalisasi dari OrganizationAssignment aktif saat
    # record dibuat — pola yang sama dengan EmployeeAttendance. Tanpa ini
    # rekap cuti per unit kerja harus menembus dua join setiap kali.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_leaves",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_leaves",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_leaves",
    )

    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.PROTECT,
        related_name="employee_leaves",
    )

    leave_reason = models.ForeignKey(
        "administration.LeaveReason",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_leaves",
    )

    start_date = models.DateField()
    end_date = models.DateField()

    is_half_day = models.BooleanField(default=False)

    # Diisi otomatis oleh service kalau kosong. Pecahan 0,5 dipakai
    # untuk setengah hari, jadi tidak bisa integer.
    total_days = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=LeaveStatus.choices,
        default=LeaveStatus.RECORDED,
    )

    # Surat dokter / dokumen pendukung.
    uploaded_file = models.OneToOneField(
        UploadedFile,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_leave"

        ordering = [
            "-start_date",
            "employee",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_leave_employee",
            ),
            models.Index(
                fields=["leave_type"],
                name="idx_emp_leave_type",
            ),
            models.Index(
                fields=["start_date", "end_date"],
                name="idx_emp_leave_period",
            ),
            models.Index(
                fields=["status"],
                name="idx_emp_leave_status",
            ),
        ]

        # Pencatatan administratif: menerbitkan cuti yang **tidak**
        # lewat alur persetujuan (RECORDED), dan membatalkannya.
        #
        # Izin tersendiri karena ia bukan bagian dari CRUD: yang boleh
        # membuat cuti (`add_employeeleave` — setiap pegawai, untuk
        # dirinya sendiri) tidak dengan sendirinya boleh menerbitkan
        # cuti yang sudah sah tanpa satu tanda tangan pun. Sampai izin
        # ini ada, keduanya satu kotak yang sama, dan mengirim
        # `status=recorded` lewat POST biasa sudah cukup untuk memotong
        # saldo tanpa persetujuan.
        #
        # Izin Django biasa, jadi ia muncul di layar Roles dan bisa
        # dicentang per tenant — bukan daftar kode role di dalam kode.
        permissions = [
            (
                "record_employeeleave",
                "Can record leave without approval",
            ),
        ]

    # `total_days` dihitung `LeaveDayCalculator`
    # (`apps/hr/api/leave/calculator.py`), bukan di model: angkanya
    # bergantung pada WorkCalendar dan Holiday milik pegawai, jadi
    # butuh query — dan itu urusan service, bukan model.

    @property
    def is_editable(self) -> bool:
        """
        Dokumen yang sedang menunggu atau sudah disetujui tidak boleh
        disunting.

        Bukan kerewelan: yang sudah ditandatangani harus tetap menunjuk
        isi yang ditandatangani. Kalau memang perlu diubah, tarik dulu
        pengajuannya — dan itu tindakan yang terlihat.
        """
        return self.status in LEAVE_EDITABLE_STATUSES

    @property
    def deducts_balance(self) -> bool:
        return self.status in LEAVE_DEDUCTING_STATUSES

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

        if (
            self.is_half_day
            and self.start_date
            and self.end_date
            and self.start_date != self.end_date
        ):
            errors["is_half_day"] = (
                "Setengah hari hanya berlaku untuk cuti satu hari."
            )

        # Nol itu sah, bukan kesalahan: pegawai roster yang mengambil
        # cuti saat blok off-nya tidak memotong saldo sama sekali.
        # Menolaknya akan memaksa mereka mengarang tanggal.
        if (
            self.total_days is not None
            and self.total_days < 0
        ):
            errors["total_days"] = (
                "Total Days tidak boleh negatif."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.leave_type_id} "
            f"({self.start_date} s/d {self.end_date})"
        )


class LeaveBalance(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_balances",
    )

    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.PROTECT,
        related_name="leave_balances",
    )

    year = models.PositiveSmallIntegerField()

    entitlement = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    carried_over = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    # Saldo awal migrasi — kantong ketiga, di samping jatah tahun
    # berjalan dan sisa bawaan tahun lalu.
    #
    # **Dijumlah ulang dari `LeaveOpeningBalance`, jangan diketik.**
    # Sumber kebenarannya dokumen migrasi, sama seperti `used` yang
    # sumbernya catatan cuti. Kolom ini cuma cermin supaya kartu saldo
    # bisa disortir dan difilter tanpa menembus join.
    #
    # Sengaja terpisah dari `entitlement`: kolom itu ditulis ulang
    # `LeaveBalanceGenerator` tiap kali dijalankan, dan saldo dari
    # sistem lama tidak boleh ikut hilang saat jatahnya dihitung ulang.
    # Terpisah juga dari `adjustment`, yang tempatnya koreksi manual
    # sehari-hari — mencampur keduanya membuat "7 hari ini dari mana"
    # tidak punya jawaban.
    opening_balance = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text=(
            "Saldo awal saat ERP mulai dipakai. Terisi otomatis dari "
            "dokumen Leave Opening Balance."
        ),
    )

    # Cermin `LeaveOpeningBalance.expires_at`, dibekukan di sana.
    # Kosong = tidak hangus.
    opening_expires_at = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Tanggal saldo awal hangus. Dikosongkan = tidak hangus."
        ),
    )

    # Kapan sisa bawaan hangus.
    #
    # Menempel pada baris saldo, bukan dihitung ulang dari policy saat
    # dibaca: `carry_over_expiry_months` boleh diubah orang besok, dan
    # tanggal hangus yang sudah dikabarkan ke pegawai lewat email tidak
    # boleh ikut bergeser. Yang sudah diterbitkan adalah janji.
    #
    # Kosong = tidak hangus. Itu keadaan yang sah dan justru yang paling
    # lazim: `carry_over_expiry_months` bawaannya kosong.
    carried_over_expires_at = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Tanggal sisa bawaan hangus. Dikosongkan = tidak hangus."
        ),
    )

    # Berapa hari yang sudah benar-benar hangus.
    #
    # Disimpan terpisah, bukan sekadar dikurangkan dari `carried_over` —
    # tanpa kolom ini, saldo yang hangus tidak bisa dibedakan dari saldo
    # yang tidak pernah ada, dan pertanyaan "empat hari saya ke mana"
    # tidak punya jawaban di layar mana pun.
    carried_over_forfeited = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="Sisa bawaan yang sudah hangus karena lewat tanggalnya.",
    )

    # Berapa hari saldo awal yang sudah hangus. Terpisah dari
    # `carried_over_forfeited` karena kantongnya memang berbeda, dan
    # "saldo migrasi saya hangus" adalah pertanyaan yang berbeda dari
    # "sisa tahun lalu saya hangus".
    #
    # `opening_balance` sendiri **tidak** dikurangi saat hangus — ia
    # dijumlah ulang dari dokumen `LeaveOpeningBalance`, jadi angka yang
    # dikurangi di sini akan dikembalikan pada sinkronisasi berikutnya.
    # Yang mengurangi `remaining` adalah kolom ini.
    opening_forfeited = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="Saldo awal yang sudah hangus karena lewat tanggalnya.",
    )

    # Koreksi manual (bonus/potongan) yang tidak berasal dari record cuti.
    adjustment = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    # ------------------------------------------------------------------
    # Hasil alokasi FIFO
    # ------------------------------------------------------------------
    #
    # Ketiganya **dihitung ulang** `LeaveBalanceService.recalculate_used`
    # bersama `used`, dari catatan cuti — bukan diketik, bukan
    # inkremental. Yang disimpan cuma jawabannya, supaya bisa disortir
    # dan difilter di tabel tanpa menghitung ulang per baris.
    #
    # Tanpa ketiganya, penghangusan tidak bisa dieksekusi: bawaan yang
    # belum terpakai (memang hangus) tidak bisa dibedakan dari bawaan
    # yang sudah dipakai bulan Maret (tidak ada yang perlu dihanguskan).

    opening_used = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="Bagian pemakaian yang menggerus saldo awal.",
    )

    carried_over_used = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="Bagian pemakaian yang menggerus sisa tahun lalu.",
    )

    # Pemakaian yang tidak punya kantong sama sekali — cuti dibayar di
    # muka. Disimpan supaya saldo minus punya penjelasan: tanpa ini,
    # kartu bersaldo −3 tidak bisa dibedakan dari kartu yang jatahnya
    # salah hitung.
    advance_used = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="Pemakaian yang melebihi seluruh kantong.",
    )

    # Disimpan, bukan dihitung on-the-fly, supaya bisa disortir dan
    # difilter langsung di tabel. Diperbarui oleh EmployeeLeaveService
    # setiap kali record cuti berubah.
    used = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_leave_balance"

        ordering = [
            "-year",
            "employee",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["employee", "leave_type", "year"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_leave_balance",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "year"],
                name="idx_leave_balance_emp_year",
            ),
        ]

    @property
    def remaining(self) -> Decimal:
        """
        Sisa yang benar-benar masih bisa dipakai.

        Tiga pemberian (jatah, bawaan, saldo awal) plus koreksi manual,
        dikurangi pemakaian **dan** yang sudah hangus.

        Yang hangus dikurangi di sini, bukan dengan mengecilkan kolom
        pemberiannya: `opening_balance` dijumlah ulang dari dokumen
        migrasi dan `carried_over` ditimpa ulang tiap kali carry over
        dijalankan, jadi angka yang dikurangi di sana akan kembali
        sendiri pada sinkronisasi berikutnya — dan hari yang sudah
        dihanguskan hidup lagi tanpa ada yang menyadarinya.
        """
        return (
            (self.entitlement or Decimal("0.0"))
            + (self.carried_over or Decimal("0.0"))
            + (self.opening_balance or Decimal("0.0"))
            + (self.adjustment or Decimal("0.0"))
            - (self.used or Decimal("0.0"))
            - (self.carried_over_forfeited or Decimal("0.0"))
            - (self.opening_forfeited or Decimal("0.0"))
        )

    @property
    def entitlement_used(self) -> Decimal:
        """
        Bagian pemakaian yang menggerus jatah tahun berjalan.

        Diturunkan, tidak disimpan: ia sisa dari tiga angka yang sudah
        ada, dan kolom keempat yang harus dijaga tetap sejumlah dengan
        ketiganya cepat atau lambat berbeda.
        """
        rest = (
            (self.used or Decimal("0.0"))
            - (self.opening_used or Decimal("0.0"))
            - (self.carried_over_used or Decimal("0.0"))
            - (self.advance_used or Decimal("0.0"))
        )

        return rest if rest > Decimal("0.0") else Decimal("0.0")

    @property
    def opening_remaining(self) -> Decimal:
        """Sisa saldo awal yang belum terpakai dan belum hangus."""
        left = (
            (self.opening_balance or Decimal("0.0"))
            - (self.opening_used or Decimal("0.0"))
            - (self.opening_forfeited or Decimal("0.0"))
        )

        return left if left > Decimal("0.0") else Decimal("0.0")

    @property
    def carried_over_remaining(self) -> Decimal:
        """Sisa bawaan tahun lalu yang belum terpakai dan belum hangus."""
        left = (
            (self.carried_over or Decimal("0.0"))
            - (self.carried_over_used or Decimal("0.0"))
            - (self.carried_over_forfeited or Decimal("0.0"))
        )

        return left if left > Decimal("0.0") else Decimal("0.0")

    def clean(self):
        super().clean()

        errors = {}

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "Tahun harus di antara 2000 dan 2100."

        if self.entitlement is not None and self.entitlement < 0:
            errors["entitlement"] = "Entitlement tidak boleh negatif."

        if self.used is not None and self.used < 0:
            errors["used"] = "Used tidak boleh negatif."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.leave_type_id} ({self.year})"
        )
