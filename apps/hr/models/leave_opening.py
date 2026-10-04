"""
Saldo cuti awal saat ERP mulai dipakai.

Kenapa perlu model tersendiri
-----------------------------
Klien yang pindah dari sistem lama datang membawa saldo, bukan histori.
Andi masuk 10 Maret 2024 dan pada hari go-live punya sisa 7 hari — tapi
catatan cuti tahun-tahun sebelumnya tidak lengkap dan tidak akan pernah
lengkap. Membuat `EmployeeLeave` untuk mengarang pemakaiannya berarti
menulis histori fiktif; membuat `LeaveBalance` tahun 2022–2025 berarti
menerbitkan jatah yang tidak pernah bisa dijelaskan.

Yang benar cuma satu: **satu titik awal**, bertanggal, beralasan, dan
sesudah itu seluruh transaksi kembali lewat jalur normal.

Artinya tunggal, dan itu disengaja
----------------------------------
Angka di dokumen ini **selalu** berarti satu hal: saldo aktual pegawai
pada tanggal go-live. Tidak ada penanda per baris yang mengubah artinya.

Dulu ada — `replaces_entitlement`, "sudah termasuk jatah tahun ini" —
dan itu kesalahan bentuk: satu kolom yang membuat angka yang sama berarti
7 di satu baris dan 7-di-atas-12 di baris sebelahnya, dengan bawaan yang
justru lebih jarang benar. Yang mengisi file harus memutuskannya per
orang, dan yang membaca kartu saldo enam bulan kemudian tidak punya cara
tahu keputusan mana yang diambil. Sekarang jatah tahun go-live memang
tidak diterbitkan sistem ini — lihat gerbangnya di
`LeaveEntitlementCalculator.for_employee` — jadi tidak ada apa pun untuk
ditumpuki, dan tidak ada yang perlu ditanyakan per baris.

Kenapa bukan kolom di `LeaveBalance`
------------------------------------
Dua kolom yang sudah ada di sana sama-sama tidak bisa dipakai:

* `entitlement` **ditimpa** `LeaveBalanceGenerator`, dan generator itu
  dipanggil otomatis dari `EmploymentService.save()` setiap kali Join
  Date / Employee Group / Employment Type disunting. Saldo migrasi yang
  diketik ke sana hilang begitu ada yang membetulkan satu huruf di
  kartu pegawainya — tanpa satu pun pesan.
* `adjustment` memang bertahan dari perhitungan ulang, tapi bentuknya
  satu angka skalar: tanpa tanggal go-live, tanpa alasan per koreksi,
  dan tanpa cara mencegah duplikat. Begitu saldo migrasi dan koreksi
  manajemen menempati kolom yang sama, "7 hari ini dari mana" tidak
  punya jawaban di layar mana pun.

Jadi ini kantong **ketiga**, ditulis sebagai dokumen. Angkanya tetap
dibaca di kartu saldo — `LeaveBalance.opening_balance` dijumlah ulang
dari baris di sini, pola yang sama dengan `used` yang dijumlah ulang
dari catatan cuti. Jangan pernah mengetik kolom itu langsung.

Satu baris per pegawai per jenis cuti
-------------------------------------
Ditegakkan constraint, dan itu yang membuatnya tetap jadi alat migrasi.
Tanpa batas itu, opening balance akan dipakai sebagai cara menambah
saldo sehari-hari dalam tiga bulan — dan koreksi harian tempatnya
`LeaveBalance.adjustment`, yang memang dibuat untuk itu.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class LeaveOpeningSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    IMPORT = "import", "Import"


class LeaveOpeningStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    POSTED = "posted", "Posted"


class LeaveGoLive(BaseModel):
    """
    Tanggal sebuah perusahaan menyerahkan cutinya ke sistem ini.

    Ini yang membalik urutan implementasi cuti untuk perusahaan yang
    **sudah berjalan**. Tanpa tanggal ini, satu-satunya titik awal yang
    dikenal sistem adalah Leave Policy — jadi jatah tahun berjalan
    diterbitkan lebih dulu, lalu saldo dari sistem lama ditambahkan di
    atasnya, dan kartunya berbunyi 19 untuk orang yang sisanya 7. Yang
    salah bukan angkanya; yang salah adalah menghitung setahun penuh
    untuk periode yang tidak pernah dipegang sistem ini.

    Dengan tanggal ini terisi, yang berlaku pada tahun go-live adalah
    **saldo awal**, bukan jatah hasil hitungan. Lihat gerbangnya di
    ``LeaveEntitlementCalculator.for_employee``.

    Kenapa per company, bukan satu setelan tenant
    ---------------------------------------------
    Batas yang tidak pernah dilewati apa pun di sistem ini adalah
    company, dan tenant berisi dua belas badan usaha lazim
    memindahkannya bertahap — satu perusahaan bulan ini, sisanya kuartal
    depan. Satu setelan tenant memaksa yang belum siap ikut pindah.

    Kenapa "tidak ada barisnya" berarti sesuatu
    -------------------------------------------
    Perusahaan tanpa baris di sini **tidak** dianggap go-live hari ini —
    ia dianggap tidak pernah bermigrasi, dan jatahnya terbit seperti
    biasa. Itu yang membuat perubahan ini tidak menggeser satu angka pun
    di tenant yang sudah berjalan. Pembedanya **ada barisnya**, pola
    yang sama dengan ``FavoriteApp.DEFAULT_CODES`` dan susunan widget
    beranda.
    """

    company = models.OneToOneField(
        "administration.Company",
        on_delete=models.CASCADE,
        related_name="leave_go_live",
    )

    # Hari pertama sistem ini yang berwenang atas cuti perusahaan itu.
    #
    # Bukan tanggal tenant dibuat dan bukan tanggal datanya diimport:
    # HR yang mengetik saldonya minggu depan tetap menyatakan keadaan
    # per tanggal ini.
    go_live_date = models.DateField(
        help_text=(
            "Hari pertama cuti dikelola di sistem ini. Saldo per hari "
            "sebelumnya masuk lewat Leave Opening Balance."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Matikan untuk mengembalikan perhitungan jatah ke aturan "
            "biasa, mis. kalau tanggalnya ternyata salah."
        ),
    )

    notes = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Dari sistem apa datanya dipindah, dan siapa yang "
            "menyerahkan angkanya."
        ),
    )

    class Meta:
        db_table = "hr_leave_go_live"

        ordering = ["-go_live_date", "company"]

        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_leave_go_live_company",
            ),
        ]

    @property
    def cutoff_date(self):
        """
        Hari terakhir yang masih dipegang sistem lama.

        Diturunkan, bukan disimpan: dua tanggal yang harus selalu
        berselisih satu hari cepat atau lambat berselisih dua, dan yang
        membacanya tidak punya cara tahu mana yang benar.
        """
        if self.go_live_date is None:
            return None

        return self.go_live_date - timedelta(days=1)

    @property
    def year(self) -> int | None:
        return self.go_live_date.year if self.go_live_date else None

    def clean(self):
        super().clean()

        if self.go_live_date and not (
            2000 <= self.go_live_date.year <= 2100
        ):
            raise ValidationError(
                {"go_live_date": "Tahun harus di antara 2000 dan 2100."},
            )

    def __str__(self):
        return f"Leave Go-Live - {self.company_id} ({self.go_live_date})"


class LeaveOpeningBalance(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_opening_balances",
    )

    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.PROTECT,
        related_name="leave_opening_balances",
    )

    # Tanggal keadaan ini berlaku — lazimnya tanggal go-live ERP.
    #
    # Bukan tanggal pengetikan: HR yang memasukkan datanya minggu depan
    # tetap menyatakan saldo per hari go-live, dan tanggal itu yang
    # dipakai menghitung masa berlakunya.
    opening_date = models.DateField(
        help_text=(
            "Tanggal saldo ini berlaku, lazimnya tanggal ERP mulai "
            "dipakai."
        ),
    )

    # Bucket tujuan. Diisi service dari tahun `opening_date` kalau
    # dikosongkan — disimpan, bukan diturunkan saat dibaca, supaya
    # baris ini tetap menunjuk kartu saldo yang sama walau tanggalnya
    # dikoreksi kemudian.
    year = models.PositiveSmallIntegerField(
        help_text="Tahun kartu saldo yang menerima angka ini.",
    )

    days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="Sisa saldo dari sistem lama, dalam hari.",
    )

    # Kapan sisa saldo awal hangus.
    #
    # **Dibekukan saat dokumen dibuat**, bukan dihitung ulang dari
    # policy saat dibaca: `carry_over_expiry_months` boleh diubah orang
    # besok, dan tanggal hangus yang sudah dikabarkan ke pegawai tidak
    # boleh ikut bergeser. Pola yang sama dengan
    # `LeaveBalance.carried_over_expires_at` dan dengan approver yang
    # dibekukan saat submit di engine workflow.
    #
    # Kosong = tidak hangus, dan itu keadaan yang sah.
    expires_at = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Tanggal saldo awal hangus. Dikosongkan = tidak hangus."
        ),
    )

    source = models.CharField(
        max_length=20,
        choices=LeaveOpeningSource.choices,
        default=LeaveOpeningSource.MANUAL,
    )

    # Draft dulu, baru berlaku.
    #
    # Import saldo awal adalah satu tarikan berisi ratusan baris yang
    # angkanya datang dari luar sistem ini, dan sebagian di antaranya
    # **akan** salah — kolom yang tertukar, pegawai yang sudah keluar,
    # satuan jam yang terbaca sebagai hari. Kalau barisnya langsung
    # berlaku, kesalahan itu sudah menempel di kartu cuti seluruh
    # perusahaan sebelum ada satu orang pun sempat membacanya, dan yang
    # membatalkannya harus menghapus barisnya satu per satu.
    #
    # Yang DRAFT tidak dihitung `sync_balance` sama sekali: ia terbaca
    # di layar, bisa dibetulkan, bisa dibuang — dan kartu saldonya tetap
    # kosong sampai seseorang menekan Post. Itu yang membuat langkah
    # "Review" punya arti; tanpa status, review cuma berarti membaca
    # angka yang sudah terlanjur berlaku.
    status = models.CharField(
        max_length=20,
        choices=LeaveOpeningStatus.choices,
        default=LeaveOpeningStatus.DRAFT,
        help_text=(
            "Draft belum memengaruhi kartu saldo. Posted sudah."
        ),
    )

    posted_at = models.DateTimeField(null=True, blank=True)

    posted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_leave_opening_balances",
    )

    remark = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Dari mana angkanya, mis. 'Saldo per 16 Agustus 2026 dari "
            "sistem HR lama'."
        ),
    )

    class Meta:
        db_table = "hr_leave_opening_balance"

        ordering = [
            "-opening_date",
            "employee",
        ]

        constraints = [
            # Satu titik awal per pegawai per jenis cuti. Ini yang
            # membedakannya dari koreksi manual — kalau boleh berkali
            # -kali, ia berhenti jadi alat migrasi.
            models.UniqueConstraint(
                fields=["employee", "leave_type"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_leave_opening_balance",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "year"],
                name="idx_leave_opening_emp_year",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.days is not None and self.days < 0:
            # Saldo awal negatif berarti hutang cuti, dan hutang cuti
            # punya perlakuannya sendiri (pelunasan, perhitungan saat
            # berhenti) yang belum ada di sistem ini. Menerimanya di
            # sini akan menghasilkan angka yang tidak bisa ditindak
            # lanjuti siapa pun.
            errors["days"] = (
                "Saldo awal tidak boleh negatif. Untuk koreksi "
                "pengurangan, pakai Adjustment di kartu saldo."
            )

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "Tahun harus di antara 2000 dan 2100."

        if (
            self.expires_at
            and self.opening_date
            and self.expires_at <= self.opening_date
        ):
            errors["expires_at"] = (
                "Tanggal hangus harus setelah tanggal berlaku."
            )

        employment = getattr(
            getattr(self, "employee", None),
            "employment",
            None,
        )

        join_date = getattr(employment, "join_date", None)

        # Saldo yang berlaku sebelum orangnya masuk kerja selalu salah
        # ketik, dan salahnya tidak akan pernah terlihat di kartu saldo
        # — angkanya benar, tanggalnya yang mustahil.
        if (
            join_date
            and self.opening_date
            and self.opening_date < join_date
        ):
            errors["opening_date"] = (
                f"Tanggal berlaku lebih awal dari Join Date pegawai "
                f"({join_date})."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def is_posted(self) -> bool:
        return self.status == LeaveOpeningStatus.POSTED

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.leave_type_id} ({self.opening_date})"
        )
