"""
Aturan jatah cuti — berapa hari, sejak kapan, dan untuk siapa.

Sebelum ini tidak ada sama sekali: `LeaveType` isinya cuma kode dan
nama, dan `LeaveBalance` harus diketik tangan satu per satu per pegawai
per tahun. Konsekuensinya jatah cuti tidak pernah bisa dijelaskan —
angka 12 di kartu seseorang tidak menunjuk aturan mana pun, dan pegawai
baru yang belum genap setahun tetap bisa punya saldo penuh karena tidak
ada yang memeriksanya.

Yang disimpan di sini **aturannya**, bukan angkanya. Angka per pegawai
tetap di `LeaveBalance`; kebijakan ini yang menerbitkannya, dan kolom
`adjustment` di sana tetap milik manusia sehingga koreksi manual tidak
pernah tertimpa perhitungan ulang.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class LeaveAccrual(models.TextChoices):
    # Jatah setahun diberikan sekaligus di awal periode. Paling lazim,
    # dan paling mudah dijelaskan ke pegawai.
    UPFRONT = "upfront", "Upfront"

    # Terkumpul sebulan sekali. Dipakai perusahaan yang tidak mau
    # pegawai baru langsung memakai jatah setahun penuh lalu keluar.
    MONTHLY = "monthly", "Monthly Accrual"


class LeavePeriodBasis(models.TextChoices):
    # Periode mengikuti tahun kalender: 1 Januari – 31 Desember.
    CALENDAR_YEAR = "calendar", "Calendar Year"

    # Periode mengikuti tanggal masuk pegawai: 9 Agustus – 8 Agustus.
    # Lebih adil untuk pegawai yang masuk pertengahan tahun, tapi
    # membuat rekap per tahun tidak lagi sebaris untuk semua orang.
    JOIN_DATE = "join_date", "Employment Anniversary"


class LeaveHistoryAction(models.TextChoices):
    """
    Apa yang dilakukan terhadap temuan riwayat, dan tiga dari empatnya
    **tidak** menolak.

    Cuti per kejadian lazimnya memang boleh berulang — orang bisa
    menikahkan anak keduanya, dan bisa berduka dua kali dalam setahun.
    Yang tidak bisa diputuskan sistem adalah apakah kejadiannya memang
    kejadian yang berbeda; itu pertanyaan untuk orang yang memegang
    dokumennya, bukan untuk kode yang cuma melihat dua tanggal.
    """

    NONE = "none", "None"

    # Ditampilkan ke pengaju dan approver, tidak menahan apa pun.
    WARN = "warn", "Warning"

    # Sama seperti WARN, plus ditandai sebagai butuh diperiksa —
    # peringatan yang ikut terbawa sampai meja terakhir.
    REVIEW = "review", "Warning + Review"

    # Satu-satunya yang benar-benar menolak. Dipakai untuk hak yang
    # memang sekali seumur kerja.
    BLOCK = "block", "Block"


class LeavePolicy(BaseModel):
    """
    Satu aturan jatah untuk satu jenis cuti.

    Pencocokannya berjenjang dari yang paling khusus ke paling umum,
    lihat `LeavePolicyResolver`. Aturan yang menyebut Employee Group
    mengalahkan yang tidak; yang menyebut company mengalahkan yang
    global. Pola yang sama dengan `DocumentSeries` dan `ApprovalFlow`.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leave_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak "
            "punya aturannya sendiri."
        ),
    )

    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.CASCADE,
        related_name="policies",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Untuk siapa
    # ------------------------------------------------------------------
    #
    # Dua-duanya opsional dan boleh dipakai bersama. Kosong berarti
    # "berlaku untuk semua" — bukan "tidak berlaku". Ini yang membuat
    # satu tenant bisa memberi jatah berbeda untuk pegawai roster site
    # dan pegawai kantor tanpa menulis aturan per orang.

    employee_group = models.ForeignKey(
        "administration.EmployeeGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leave_policies",
    )

    employment_type = models.ForeignKey(
        "administration.EmploymentType",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leave_policies",
    )

    # ------------------------------------------------------------------
    # Berbentuk saldo atau tidak
    # ------------------------------------------------------------------
    #
    # Saklar yang membelah seluruh isi aturan ini jadi dua kelompok yang
    # tidak pernah dipakai bersamaan. Menyala: cuti tahunan dan
    # sejenisnya — ada jatah, ada sisa, ada carry over, dan `LeaveBalance`
    # yang mencatat semuanya. Mati: cuti menikah, melahirkan, duka —
    # haknya melekat pada **kejadian**, bukan pada tahun, jadi tidak ada
    # angka yang perlu disimpan per pegawai per tahun.
    #
    # Kenapa saklar, bukan daftar kode di dalam kode: yang membedakan
    # keduanya adalah kebijakan perusahaan, bukan sifat jenis cutinya.
    # Ada tenant yang memberi jatah cuti besar berbentuk saldo dan ada
    # yang memberikannya per kejadian, dan `if leave_type.code == "BIG"`
    # akan salah di salah satunya tanpa bisa diperbaiki dari layar mana
    # pun.

    uses_balance = models.BooleanField(
        default=True,
        help_text=(
            "Jika aktif, policy menerbitkan dan menggunakan "
            "LeaveBalance. Dimatikan untuk cuti yang haknya per "
            "kejadian — cutinya tetap dicatat, tapi tidak ada saldo "
            "yang dipotong."
        ),
    )

    # ------------------------------------------------------------------
    # Berapa
    # ------------------------------------------------------------------

    entitlement_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=12,
        help_text=(
            "Jatah penuh untuk satu periode, mis. 12 hari setahun. "
            "Tidak berpengaruh apa-apa saat Uses Balance dimatikan."
        ),
    )

    accrual = models.CharField(
        max_length=20,
        choices=LeaveAccrual.choices,
        default=LeaveAccrual.UPFRONT,
    )

    period_basis = models.CharField(
        max_length=20,
        choices=LeavePeriodBasis.choices,
        default=LeavePeriodBasis.CALENDAR_YEAR,
    )

    # ------------------------------------------------------------------
    # Sejak kapan
    # ------------------------------------------------------------------

    eligible_after_months = models.PositiveSmallIntegerField(
        default=12,
        help_text=(
            "Masa tunggu sejak Join Date sebelum jatah pertama terbit. "
            "12 = cuti tahunan baru ada setelah setahun bekerja "
            "(UU Ketenagakerjaan). 0 = berlaku sejak hari pertama."
        ),
    )

    prorate_first_period = models.BooleanField(
        default=True,
        help_text=(
            "Periode pertama dihitung sebanding sisa bulannya, bukan "
            "penuh. Pegawai yang mulai berhak di bulan Agustus dapat "
            "5/12 jatah untuk tahun itu."
        ),
    )

    # ------------------------------------------------------------------
    # Sisa tahun lalu
    # ------------------------------------------------------------------

    allow_carry_over = models.BooleanField(default=False)

    carry_over_max_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Batas sisa yang boleh dibawa ke periode berikutnya. "
            "Dikosongkan = tanpa batas."
        ),
    )

    carry_over_expiry_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Sisa bawaan hangus setelah sekian bulan periode baru "
            "berjalan. Dikosongkan = tidak hangus."
        ),
    )

    carry_over_reminder_days = models.CharField(
        max_length=100,
        default="30,14,7",
        blank=True,
        help_text=(
            "Sisa hari saat pegawai diingatkan bahwa cuti bawaannya akan "
            "hangus, dipisah koma. Dikosongkan = tidak ada pengingat. "
            "Ditaruh di sini, bukan di setelan sistem, karena yang "
            "menciptakan tanggal hangusnya adalah aturan ini."
        ),
    )

    # ------------------------------------------------------------------
    # Aturan untuk cuti tanpa saldo
    # ------------------------------------------------------------------
    #
    # Seluruh blok ini yang menggantikan `entitlement_days` dkk. saat
    # `uses_balance` mati. Tidak ada angka yang diterbitkan ke kartu
    # pegawai; yang ada batas dan pemeriksaan, dan keduanya dinilai saat
    # cutinya diajukan.

    max_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Maksimum hari yang boleh digunakan untuk satu "
            "request/event. Dikosongkan = tanpa batas — dipakai cuti "
            "yang lamanya ditentukan surat dokter atau keterangan "
            "resmi, bukan oleh perusahaan."
        ),
    )

    per_event = models.BooleanField(
        default=False,
        help_text=(
            "Hak berlaku per kejadian, bukan sebagai saldo tahunan. "
            "Menyala: dua kelahiran anak masing-masing berhak penuh, "
            "dan yang diperiksa riwayatnya adalah kejadiannya."
        ),
    )

    document_required = models.BooleanField(
        default=False,
        help_text=(
            "Pengajuan wajib melampirkan dokumen pendukung — surat "
            "dokter, surat nikah, akta."
        ),
    )

    history_check = models.BooleanField(
        default=False,
        help_text=(
            "Periksa riwayat penggunaan jenis cuti ini saat request "
            "dibuat, lalu tampilkan temuannya. Yang menentukan "
            "akibatnya kolom di bawah."
        ),
    )

    history_action = models.CharField(
        max_length=20,
        choices=LeaveHistoryAction.choices,
        default=LeaveHistoryAction.NONE,
        help_text=(
            "Warning = ditampilkan saja. Warning + Review = ikut "
            "terbawa sampai meja persetujuan terakhir. Block = "
            "pengajuannya ditolak."
        ),
    )

    class Meta:
        db_table = "master_leave_policy"

        ordering = ["leave_type", "company", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_leavepolicy_code",
            ),
            # Satu kombinasi sasaran hanya boleh punya satu aturan aktif.
            # Dua aturan yang sama-sama cocok berarti jatah seseorang
            # bergantung pada urutan baris di database — dan itu tidak
            # bisa dijelaskan ke siapa pun.
            models.UniqueConstraint(
                fields=[
                    "company",
                    "leave_type",
                    "employee_group",
                    "employment_type",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_leavepolicy_target",
            ),
        ]

    @property
    def reminder_days(self) -> list[int]:
        """
        Tonggak pengingat sebagai daftar angka, urut menurun.

        Nilai yang tidak masuk akal **dibuang diam-diam**, bukan
        menggagalkan seluruh pengingat: kolom ini diketik tangan, dan
        satu koma berlebih tidak boleh membuat seluruh tenant berhenti
        diberi tahu cutinya akan hangus.
        """
        found: set[int] = set()

        for piece in str(self.carry_over_reminder_days or "").split(","):
            piece = piece.strip()

            if not piece.isdigit():
                continue

            found.add(int(piece))

        return sorted(found, reverse=True)

    @property
    def is_balance_based(self) -> bool:
        """
        Alias yang bisa dibaca di tempat pemakaiannya.

        Ditulis sebagai properti, bukan dibaca langsung dari kolomnya,
        supaya pemanggil tidak perlu tahu bahwa nilainya bisa `None`
        pada baris yang belum pernah tersentuh migrasi.
        """
        return bool(self.uses_balance)

    @property
    def specificity(self) -> int:
        """
        Seberapa khusus aturan ini. Makin tinggi makin menang.

        Dipakai `LeavePolicyResolver` untuk memilih di antara beberapa
        aturan yang sama-sama cocok, tanpa bergantung pada urutan baris.
        """
        return (
            (4 if self.company_id else 0)
            + (2 if self.employee_group_id else 0)
            + (1 if self.employment_type_id else 0)
        )

    def clean(self):
        super().clean()

        errors = {}

        if self.entitlement_days is not None and self.entitlement_days < 0:
            errors["entitlement_days"] = (
                "Jatah cuti tidak boleh negatif."
            )

        # Batas dan masa hangus tanpa izin membawa sisa tidak pernah
        # terpakai — dan yang mengisinya mengira sudah mengatur sesuatu.
        if not self.allow_carry_over:
            if self.carry_over_max_days is not None:
                errors["carry_over_max_days"] = (
                    "Nyalakan dulu 'Boleh Dibawa ke Tahun Depan'."
                )

            if self.carry_over_expiry_months is not None:
                errors["carry_over_expiry_months"] = (
                    "Nyalakan dulu 'Boleh Dibawa ke Tahun Depan'."
                )

        if (
            self.carry_over_max_days is not None
            and self.carry_over_max_days < 0
        ):
            errors["carry_over_max_days"] = (
                "Batas bawaan tidak boleh negatif."
            )

        # ------------------------------------------------------------------
        # Saldo vs per kejadian
        # ------------------------------------------------------------------
        #
        # Ketiga pemeriksaan di bawah menolak setelan yang **tersimpan
        # rapi lalu tidak pernah dibaca siapa pun**. Itu bentuk kegagalan
        # yang paling mahal di master seperti ini: yang mengisinya yakin
        # sudah mengatur sesuatu, dan tidak ada satu pun tanda di layar
        # yang memberi tahu bahwa isiannya tidak berpengaruh.

        if not self.uses_balance:
            if self.allow_carry_over:
                errors["allow_carry_over"] = (
                    "Carry over hanya berlaku untuk cuti bersaldo. "
                    "Nyalakan 'Uses Balance' dulu, atau matikan ini."
                )

        elif self.per_event:
            errors["per_event"] = (
                "Hak per kejadian dan saldo tahunan tidak bisa "
                "bersamaan — yang satu dihitung per kejadian, yang "
                "satunya per tahun. Matikan 'Uses Balance' kalau "
                "cutinya memang per kejadian."
            )

        if self.max_days is not None and self.max_days < 0:
            errors["max_days"] = "Batas hari tidak boleh negatif."

        if (
            self.history_action
            and self.history_action != LeaveHistoryAction.NONE
            and not self.history_check
        ):
            errors["history_check"] = (
                "Nyalakan dulu 'History Check' — tanpa itu tindakan "
                "riwayat tidak pernah dijalankan."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.code} — {self.name}"
