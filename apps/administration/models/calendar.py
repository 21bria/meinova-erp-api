from django.conf import settings
from django.db import models

from apps.core.models.base import BaseModel
from .organization import Company, Location

# `FiscalYear` dan `PostingPeriod` **tidak lagi di sini.** Keduanya
# tahun buku dan periode akuntansi, dan itu milik Finance — bukan
# kalender kerja. Kepemilikannya dipindah ke `apps.finance` lewat
# `finance.0002_adopt_administration_fiscal`, yang menyalin barisnya
# beserta id aslinya; migrasi penghapusan di app ini sengaja
# bergantung padanya, kalau tidak urutannya ditentukan abjad nama app
# dan tabelnya terhapus sebelum sempat disalin.
#
# Yang tinggal di berkas ini kalender kerja dan hari libur: kapan
# orang bekerja. Kapan sebuah transaksi boleh dibukukan pertanyaan
# yang berbeda, dan jawabannya sekarang punya satu rumah.

# ======================================================================
# CAKUPAN KALENDER
#
# Work Calendar dan Holiday memakai aturan cakupan yang **sama**, dan
# ditulis sekali di sini. Dua salinan aturan yang harus tetap sepakat
# adalah persis cara satu layar mulai menerima baris yang ditolak layar
# sebelahnya.
# ======================================================================

WEEKDAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

WEEKDAY_SHORT = (
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
)


def validate_calendar_scope(
    *,
    scope: str,
    company_id,
    location,
    location_id,
    selected_scope: str | None = None,
) -> dict[str, str]:
    """
    Aturan konsistensi cakupan, dikembalikan sebagai dict error.

    Ketiganya dijaga dua arah — bukan cuma "yang wajib harus ada", tapi
    juga "yang tidak berlaku harus kosong". Baris `GLOBAL` yang masih
    menyimpan company adalah baris yang artinya bergantung pada kolom
    mana yang kebetulan dibaca lebih dulu, dan itu bug yang tidak
    pernah melempar apa-apa.
    """
    errors: dict[str, str] = {}

    if scope == "GLOBAL":
        if company_id:
            errors["company"] = (
                "Cakupan GLOBAL berlaku untuk seluruh perusahaan, "
                "jadi kolom Company harus dikosongkan."
            )

        if location_id:
            errors["location"] = (
                "Cakupan GLOBAL tidak boleh menyebut Location."
            )

    elif scope == "COMPANY":
        if not company_id:
            errors["company"] = "Cakupan COMPANY wajib menyebut Company."

        if location_id:
            errors["location"] = (
                "Cakupan COMPANY berlaku untuk seluruh lokasi "
                "perusahaan itu, jadi kolom Location harus dikosongkan. "
                "Untuk satu lokasi saja, pakai cakupan LOCATION."
            )

    elif scope == "LOCATION":
        if not company_id:
            errors["company"] = "Cakupan LOCATION wajib menyebut Company."

        if not location_id:
            errors["location"] = "Cakupan LOCATION wajib menyebut Location."

        elif (
            company_id
            and location is not None
            and location.company_id != company_id
        ):
            errors["location"] = (
                "Location tidak termasuk dalam Company yang dipilih."
            )

    elif selected_scope and scope == selected_scope:
        # Daftar perusahaannya ada di tabel relasi, bukan di kolom.
        # Kolom `company` yang terisi di baris seperti ini adalah sisa
        # dari cakupan sebelumnya, dan resolver akan membacanya.
        if company_id:
            errors["company"] = (
                "Cakupan SELECTED_COMPANIES memakai daftar perusahaan "
                "terpisah, jadi kolom Company harus dikosongkan."
            )

        if location_id:
            errors["location"] = (
                "Cakupan SELECTED_COMPANIES tidak boleh menyebut "
                "Location."
            )

    return errors


def derive_scope(*, scope: str, company_id, location_id, default: str) -> str:
    """
    Menyelaraskan `scope` dengan kolom yang benar-benar terisi.

    Dibutuhkan karena `scope` punya nilai bawaan, dan Django tidak bisa
    membedakan "COMPANY karena diketik" dari "COMPANY karena tidak
    diisi". Kode lama yang membuat kalender lokasi lewat
    `WorkCalendar.objects.create(company=…, location=…)` — seed, shell,
    dan puluhan test yang sudah ada — tidak menyebut cakupan sama
    sekali, dan tanpa penyelarasan ini barisnya tersimpan sebagai
    COMPANY yang menyebut location: kombinasi yang **ditolak**
    `clean()`, dan yang oleh resolver tidak pernah ditemukan sebagai
    kalender lokasi. Kalender site-nya ada di database dan tidak
    berlaku untuk siapa pun.

    Hanya kombinasi yang memang tidak sah yang diperbaiki. Baris yang
    sudah konsisten dibiarkan apa adanya, jadi cakupan yang dipilih
    orang di layar tidak pernah ditimpa.
    """
    if scope not in {"GLOBAL", "COMPANY", "LOCATION"}:
        # SELECTED_COMPANIES dan nilai tak dikenal bukan urusan fungsi
        # ini — yang menilainya `clean()`.
        return scope or default

    if location_id:
        return "LOCATION"

    if not company_id:
        return "GLOBAL"

    if scope == "LOCATION":
        # Menyebut LOCATION tanpa location. `clean()` yang menolaknya;
        # di sini cukup tidak memperburuk.
        return scope

    return "COMPANY"


def scope_label(*, scope: str, company, location) -> str:
    """
    Cakupan sebagai satu kalimat pendek untuk kolom tabel.

    `GLOBAL` sengaja berbunyi **All Companies**, bukan tanda hubung:
    kolom kosong di sebelah baris yang justru berlaku paling luas
    terbaca seperti data yang belum diisi.
    """
    if scope == "GLOBAL":
        return "All Companies"

    if scope == "LOCATION" and location is not None:
        company_name = company.name if company is not None else ""

        return f"{company_name} · {location.name}".strip(" ·")

    if company is not None:
        return company.name

    return "-"


def working_days_label(source) -> str:
    """
    `Mon-Fri`, `Mon-Sat`, `Mon,Wed,Fri` — pola hari kerjanya sebagai
    satu sel, bukan tujuh kolom centang yang harus dibaca menyamping.

    Menerima instance model **atau** dict. Bentuk kedua dipakai layar
    preview import, yang harus menampilkan polanya sebelum ada baris
    yang tersimpan — jadi belum ada objek untuk dibaca atributnya.
    """
    if isinstance(source, dict):
        def read(field_name):
            return source.get(field_name, False)
    else:
        def read(field_name):
            return getattr(source, field_name, False)

    days = [
        index
        for index, field_name in enumerate(WEEKDAY_FIELDS)
        if read(field_name)
    ]

    if not days:
        return "-"

    if len(days) == 7:
        return "Every day"

    # Deret berurutan ditulis sebagai rentang; yang berlubang
    # (Senin/Rabu/Jumat) ditulis apa adanya.
    if days == list(range(days[0], days[-1] + 1)):
        if len(days) == 1:
            return WEEKDAY_SHORT[days[0]]

        return f"{WEEKDAY_SHORT[days[0]]}-{WEEKDAY_SHORT[days[-1]]}"

    return ",".join(WEEKDAY_SHORT[index] for index in days)


class CalendarScope(models.TextChoices):
    """
    Cakupan berlaku satu master kalender.

    Ini yang menggantikan duplikasi per company. Sebelumnya satu pola
    Senin–Jumat harus ditulis ulang untuk tiap perusahaan, jadi tenant
    berisi dua puluh perusahaan menyimpan dua puluh baris yang isinya
    sama persis — dan mengubah polanya berarti menyunting dua puluh
    baris, yang tidak pernah selesai serentak.
    """

    GLOBAL = "GLOBAL", "All Companies"
    COMPANY = "COMPANY", "Company"
    LOCATION = "LOCATION", "Location"


class HolidayScope(models.TextChoices):
    """
    Sama seperti `CalendarScope`, plus satu cakupan yang memang
    dibutuhkan hari libur: **sebagian** perusahaan, bukan semua dan
    bukan satu.

    Cuti bersama yang cuma berlaku di tiga dari dua belas perusahaan
    tidak punya tempat di tiga cakupan lainnya, dan satu-satunya jalan
    keluar sebelumnya adalah menulis tiga baris identik. Barisnya tetap
    satu; daftar perusahaannya di `HolidayCompany`.
    """

    GLOBAL = "GLOBAL", "National / All Companies"
    COMPANY = "COMPANY", "Company"
    LOCATION = "LOCATION", "Location"
    SELECTED_COMPANIES = "SELECTED_COMPANIES", "Selected Companies"


class HolidaySource(models.TextChoices):
    """Dari mana baris hari libur ini datang."""

    MANUAL = "MANUAL", "Manual"
    IMPORT = "IMPORT", "Import"
    GOOGLE = "GOOGLE", "Google Calendar"
    GOVERNMENT = "GOVERNMENT", "Government"
    ICS = "ICS", "ICS Feed"


class HolidaySyncStatus(models.TextChoices):
    """
    Gerbang antara sumber luar dan kalender yang berlaku.

    Penyedia dari luar **bukan** sumber kebenaran langsung untuk
    Attendance dan Payroll: SK cuti bersama bisa berubah, dan feed
    kalender publik bisa memuat tanggal yang tidak berlaku bagi
    perusahaan ini. Baris `PENDING` tersimpan tapi **tidak** dibaca
    resolver — jadi hasil sync tidak pernah menggeser hari kerja siapa
    pun sebelum ada yang menekan Confirm.

    `CONFIRMED` adalah bawaan, dan itu disengaja: baris yang ditulis
    tangan atau lewat import Excel sudah melewati orang yang
    mengetiknya.
    """

    CONFIRMED = "CONFIRMED", "Confirmed"
    PENDING = "PENDING", "Pending Review"
    REJECTED = "REJECTED", "Rejected"


class WorkCalendar(BaseModel):
    """
    **Pola** hari kerja, bukan kalender tahunan.

    Satu `HO-STANDARD` bercakupan GLOBAL melayani seluruh perusahaan
    yang mengikuti pola Senin–Jumat, berapa pun jumlahnya dan termasuk
    perusahaan yang baru dibuat besok. Site yang polanya memang berbeda
    membuat kalendernya sendiri bercakupan LOCATION; yang tidak berbeda
    **tidak perlu** membuat apa pun.

    Resolusinya terpusat di `CalendarResolver` — jangan menyalin urutan
    pencariannya ke Attendance/Leave/Payroll.

    Ini **bukan** pengganti Roster Crew. Kalender menjawab "pola hari
    kerja operasionalnya apa"; yang menjawab "pegawai ini kerja atau
    off tanggal sekian" tetap roster/rotasinya.
    """

    scope = models.CharField(
        max_length=20,
        choices=CalendarScope.choices,
        default=CalendarScope.COMPANY,
        db_index=True,
    )

    # Kosong = berlaku untuk seluruh perusahaan (`scope=GLOBAL`).
    # Sebelumnya wajib, dan itu persis yang memaksa duplikasi.
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="work_calendars",
    )

    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_calendars",
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)

    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    wednesday = models.BooleanField(default=True)
    thursday = models.BooleanField(default=True)
    friday = models.BooleanField(default=True)
    saturday = models.BooleanField(default=False)
    sunday = models.BooleanField(default=False)

    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "master_work_calendar"
        constraints = [
            # `nulls_distinct=False` yang membuat ini benar-benar
            # menjaga. Tanpa itu Postgres menganggap tiap NULL berbeda,
            # jadi dua kalender GLOBAL bernama sama — keduanya
            # `company IS NULL` — lolos tanpa suara, dan resolver akan
            # memilih salah satunya secara acak.
            models.UniqueConstraint(
                fields=["company", "location", "code"],
                condition=models.Q(is_deleted=False),
                nulls_distinct=False,
                name="uniq_active_work_calendar_scope_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.scope = derive_scope(
            scope=self.scope,
            company_id=self.company_id,
            location_id=self.location_id,
            default=CalendarScope.COMPANY,
        )

        return super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validasi cakupan
    # ------------------------------------------------------------------

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()

        errors = validate_calendar_scope(
            scope=self.scope,
            company_id=self.company_id,
            location=self.location if self.location_id else None,
            location_id=self.location_id,
        )

        if errors:
            raise ValidationError(errors)

    @property
    def applies_to(self) -> str:
        """Label cakupan untuk tabel dan export."""
        return scope_label(
            scope=self.scope,
            company=self.company if self.company_id else None,
            location=self.location if self.location_id else None,
        )

    @property
    def working_days_label(self) -> str:
        """`Mon–Fri` dan sejenisnya, untuk kolom tabel."""
        return working_days_label(self)


class Holiday(BaseModel):
    """
    Satu tanggal/peristiwa kalender — **satu baris**, berapa pun
    perusahaan yang terkena.

    17 Agustus 2026 adalah satu record bercakupan GLOBAL, bukan dua
    belas record yang isinya sama kecuali kolom Company. Perusahaan
    yang dibuat bulan depan ikut mendapatkannya tanpa import ulang,
    karena yang disimpan aturannya ("berlaku untuk semua"), bukan
    daftar nilainya.

    Yang **tidak** dijawab model ini: apakah adanya hari libur berarti
    pegawai roster ikut libur. Tidak — pegawai site tetap bekerja saat
    blok kerjanya jatuh di tanggal merah, dan rosternya yang jadi
    kalender. Lihat `docs/claude/hr/leave.md`.
    """

    scope = models.CharField(
        max_length=20,
        choices=HolidayScope.choices,
        default=HolidayScope.COMPANY,
        db_index=True,
    )

    # Kosong = berlaku untuk seluruh perusahaan (`GLOBAL`), atau
    # ditentukan lewat `HolidayCompany` (`SELECTED_COMPANIES`).
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="holidays",
    )

    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="holidays",
    )

    date = models.DateField()

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)

    # Negara yang menerbitkan libur ini. Dipakai libur nasional dan
    # sync dari luar; kosong untuk libur internal perusahaan.
    country_code = models.CharField(
        max_length=2,
        blank=True,
        default="",
    )

    is_national = models.BooleanField(default=False)
    is_recurring = models.BooleanField(default=False)

    # ------------------------------------------------------------------
    # Asal-usul (lihat `HolidaySyncStatus`)
    # ------------------------------------------------------------------

    source = models.CharField(
        max_length=20,
        choices=HolidaySource.choices,
        default=HolidaySource.MANUAL,
        db_index=True,
    )

    # Identitas baris ini di sistem asalnya. Itu yang membuat sync
    # kedua mengenali baris yang sudah pernah masuk, alih-alih
    # menerbitkan salinannya.
    external_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    source_url = models.URLField(blank=True, default="")

    synced_at = models.DateTimeField(null=True, blank=True)

    sync_status = models.CharField(
        max_length=20,
        choices=HolidaySyncStatus.choices,
        default=HolidaySyncStatus.CONFIRMED,
        db_index=True,
    )

    class Meta:
        db_table = "master_holiday"
        constraints = [
            # Identitas bisnis satu hari libur: **cakupan + tanggal +
            # kode**, bukan sekadar company.
            #
            # Yang lama `(company, location, date)` — tanpa kode, dan
            # tanpa syarat `is_deleted`. Dua akibatnya: satu perusahaan
            # tidak boleh punya dua peristiwa di tanggal yang sama
            # (Natal dan HUT perusahaan di 25 Desember mustahil), dan
            # baris yang sudah dihapus tetap memblokir penggantinya.
            models.UniqueConstraint(
                fields=["company", "location", "date", "code"],
                condition=models.Q(is_deleted=False),
                nulls_distinct=False,
                name="uniq_active_holiday_scope_date_code",
            ),
        ]
        ordering = ["date"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.scope = derive_scope(
            scope=self.scope,
            company_id=self.company_id,
            location_id=self.location_id,
            default=HolidayScope.COMPANY,
        )

        return super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validasi cakupan
    # ------------------------------------------------------------------

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()

        errors = validate_calendar_scope(
            scope=self.scope,
            company_id=self.company_id,
            location=self.location if self.location_id else None,
            location_id=self.location_id,
            selected_scope=HolidayScope.SELECTED_COMPANIES,
        )

        if errors:
            raise ValidationError(errors)

    @property
    def applies_to(self) -> str:
        if self.scope == HolidayScope.SELECTED_COMPANIES:
            # Jumlahnya, bukan daftarnya: nama dua belas perusahaan
            # tidak muat di satu sel tabel, dan yang membacanya butuh
            # tahu "sebagian" — rinciannya ada di form.
            count = self.companies.filter(is_deleted=False).count()

            return f"{count} companies"

        return scope_label(
            scope=self.scope,
            company=self.company if self.company_id else None,
            location=self.location if self.location_id else None,
        )


class HolidayCompany(BaseModel):
    """
    Perusahaan yang terkena satu hari libur bercakupan
    `SELECTED_COMPANIES`.

    **Hanya untuk cakupan itu.** Libur GLOBAL sengaja tidak menurunkan
    satu baris pun ke sini: memakai daftar untuk menyatakan "semua"
    berarti daftar itu harus diperbarui setiap kali ada perusahaan
    baru, dan yang lupa memperbaruinya menghasilkan perusahaan yang
    diam-diam bekerja pada tanggal merah.
    """

    holiday = models.ForeignKey(
        Holiday,
        on_delete=models.CASCADE,
        related_name="companies",
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="selected_holidays",
    )

    class Meta:
        db_table = "master_holiday_company"
        constraints = [
            models.UniqueConstraint(
                fields=["holiday", "company"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_holiday_company",
            ),
        ]
        ordering = ["company__name"]

    def __str__(self):
        return f"{self.holiday_id} - {self.company_id}"


class RosterCrew(BaseModel):
    """
    Gelombang/kru rotasi untuk pegawai site.

    `WorkSchedule` sudah menyimpan polanya (`cycle_work_days` /
    `cycle_off_days`), tapi pola saja tidak cukup: tanpa tanggal mulai
    siklus, sistem tidak tahu pegawai sedang di hari ke berapa. Kolom
    `cycle_start_date` di sini adalah titik jangkar itu.

    Dipisah dari pegawai karena di lapangan satu site punya beberapa
    gelombang yang bergantian (Crew A masuk, Crew B off). Menyimpan
    jangkar per crew berarti menggeser jadwal satu gelombang cukup
    mengubah satu baris, bukan ratusan. Pegawai yang swing-nya digeser
    sendiri tetap bisa menimpanya lewat
    `EmploymentAssignment.roster_start_override`.
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="roster_crews",
    )

    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roster_crews",
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)

    work_schedule = models.ForeignKey(
        "administration.WorkSchedule",
        on_delete=models.PROTECT,
        related_name="roster_crews",
    )

    cycle_start_date = models.DateField(
        help_text=(
            "Hari pertama blok kerja pada siklus mana pun. Dipakai "
            "sebagai titik hitung maju-mundur, jadi tanggal lampau "
            "juga sah."
        ),
    )

    description = models.TextField(blank=True, default="")

    class Meta:
        db_table = "master_roster_crew"
        ordering = ["company", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_administration_rostercrew_code",
            ),
        ]

    @property
    def cycle_length(self) -> int | None:
        schedule = self.work_schedule

        if schedule is None:
            return None

        work = schedule.cycle_work_days or 0
        off = schedule.cycle_off_days or 0

        return (work + off) or None

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()

        errors = {}

        schedule = (
            self.work_schedule
            if self.work_schedule_id
            else None
        )

        if schedule is not None:
            if schedule.schedule_type != schedule.ScheduleType.ROSTER:
                errors["work_schedule"] = (
                    "Work Schedule harus bertipe Roster."
                )
            elif not (schedule.cycle_work_days and schedule.cycle_off_days):
                errors["work_schedule"] = (
                    "Work Schedule roster belum mengisi cycle work/off "
                    "days, jadi siklusnya tidak bisa dihitung."
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
        return f"{self.code} - {self.name}"
