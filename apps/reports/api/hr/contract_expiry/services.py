"""
Contract Expiry — laporan manajemen atas masa kontrak, READ ONLY.

Satu pertanyaan yang dijawabnya: **kontrak siapa yang akan atau sudah
habis, dan mana yang harus segera ditindaklanjuti.**

Sumber kebenarannya sudah ada, dan tidak satu pun model baru dibuat
untuk laporan ini:

* **Kontrak yang berlaku** → `EmploymentAssignment.contract_type /
  contract_start / contract_end`. Itu baris **keadaan sekarang**, satu
  per pegawai, dan `clean()`-nya sudah menegakkan artinya: jenis
  kepegawaian yang tidak berkontrak tidak boleh membawa masa kontrak
  sama sekali. Karena itu tidak ada "memilih record kontrak yang
  authoritative" di sini — kontrak berjalan seorang pegawai hanya ada
  satu, dan letaknya di baris itu.
* **Riwayat kontrak** → `EmployeeAction` yang sudah `APPLIED`. Dibaca
  layar Employment History, **tidak** dibaca laporan ini: yang ditanya
  di sini masa kontrak yang berlaku, bukan berapa kali ia pernah
  diperpanjang.
* **Perpanjangan yang sedang berjalan** → `EmployeeAction` bertipe
  Contract Extension / Contract Change yang statusnya masih terbuka
  (`ACTION_OPEN_STATUSES`). Itu satu-satunya sumber kolom Renewal
  Status; tidak ada workflow perpanjangan baru yang dibuat demi laporan.

Populasinya:

```
Population = Authorized Organization Scope
           ∩ jenis kepegawaian yang menuntut kontrak
           ∩ pegawai yang memang punya catatan kontrak
           ∩ filter yang dipilih
```

Yang **memutuskan siapa berkontrak adalah `EmploymentType.
requires_contract`**, bukan nama atau kode master. Tenant yang menamai
jenis kepegawaiannya sendiri ("PKWTT", "Harian Lepas", "Kontrak Proyek")
tidak boleh hilang dari laporan hanya karena kodenya bukan yang ditebak
kode ini — dan `EmploymentAssignment.clean()` sudah memakai penanda yang
sama, jadi laporan dan validasi tidak bisa berbeda pendapat.

**Feature Applicability sengaja tidak menyaring.** Contract Expiry
adalah laporan kepegawaian, bukan laporan proses Attendance/Leave/
Roster. Direksi yang seluruh proses HR-nya dimatikan tetap orang yang
kontraknya bisa habis, dan menghilangkannya dari layar berarti kontrak
yang paling mahal justru yang paling mungkin terlewat. Aturan yang sama
dengan Manpower Summary dan Employee Reporting Audit — lihat
`docs/claude/reports.md`.

**Potret hari ini, tanpa periode.** Lihat `as_of()`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.framework.periods import MONTH_ABBR
from apps.hr.models import (
    ACTION_OPEN_STATUSES,
    Employee,
    EmployeeAction,
    EmployeeActionStatus,
    EmployeeActionType,
)

from .statuses import (
    EXPIRY_LABELS,
    EXPIRY_ORDER,
    FOLLOW_UP_STATUSES,
    RENEWAL_LABELS,
    ExpiryStatus,
    RenewalStatus,
    expiry_status,
    expiry_status_code,
    renewal_status_code,
)


UNASSIGNED_LABEL = "Belum Ditentukan"

# Sel yang memang kosong dikirim sebagai string kosong, bukan sebagai
# tanda pisah yang dirakit backend. `formatDashboardValue` di frontend
# sudah merender nilai kosong sebagai "—" untuk seluruh tabel dashboard;
# menuliskan "-" sendiri di sini menghasilkan dua lambang kosong yang
# berbeda di satu layar.
EMPTY = ""


# Jenis dokumen yang dianggap perpanjangan/penerbitan kontrak. Dibaca
# dari `EmployeeActionType`, bukan ditulis ulang sebagai teks: menambah
# jenis dokumen kontrak baru di sana harus terbaca di sini juga.
CONTRACT_ACTION_TYPES = (
    EmployeeActionType.CONTRACT_EXTENSION,
    EmployeeActionType.CONTRACT_CHANGE,
)


# Status dokumen `EmployeeAction` → status renewal yang ditampilkan.
# Yang tidak terdaftar di sini (APPLIED, REJECTED, CANCELLED) bukan
# perpanjangan yang sedang berjalan, jadi tidak pernah jadi jawaban
# kolom Renewal Status.
RENEWAL_FROM_ACTION = {
    EmployeeActionStatus.DRAFT: RenewalStatus.DRAFT,
    EmployeeActionStatus.SUBMITTED: RenewalStatus.SUBMITTED,
    EmployeeActionStatus.APPROVED: RenewalStatus.APPROVED,
}


# Berapa bulan ke depan yang digambar Contract Expiry Timeline, dihitung
# dari bulan tanggal acuan. Dua belas bulan menjawab "kapan gelombang
# perpanjangan berikutnya datang" tanpa membuat sumbu X jadi kabur.
TIMELINE_MONTHS = 12

PAST_LABEL = "Sudah Lewat"
BEYOND_LABEL = f"> {TIMELINE_MONTHS} Bulan"
NO_END_LABEL = EXPIRY_LABELS[ExpiryStatus.NO_END_DATE]

# Ekor chart dipotong dan dijumlahkan ke satu batang. Pola yang sama
# dengan `department_breakdown` di Manpower Summary — totalnya tetap
# utuh, dan dua puluh batang memang tidak terbaca.
MAX_CHART_SEGMENTS = 8
OTHER_LABEL = "Lainnya"

# Kunci urut untuk master yang kodenya belum terisi: yang belum
# ditentukan berdiri di **ujung** daftar, bukan di depan.
LAST_SORT_KEY = "~~~"


# Cakupan data per baris. Sama persis dengan `EMPLOYEE_SCOPE` di
# Manpower Summary, Employee Reporting Audit, HR Period Summary, dan
# `EmployeeViewSet.data_scope` — kalau yang di sana berubah, yang di
# sini ikut.
#
# Ini satu-satunya penjagaan baris di laporan ini: filter dropdown cuma
# boleh **mempersempit** apa yang sudah lolos dari sini.
EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}


# Filter dropdown → jalur ORM dari `Employee`. Dialek yang sama dengan
# tiga laporan HR lainnya supaya satu tombol Location tidak berperilaku
# berbeda di empat layar.
FILTER_PATHS = {
    "company": "organization__company_id",
    "branch": "organization__branch_id",
    "location": "organization__location_id",
    "department": "organization__department_id",
    "section": "organization__section_id",
    "employee_group": "employment__employee_group_id",
    "employment_type": "employment__employment_type_id",
    "employment_status": "employment__employment_status_id",
}


CONTEXT_KEY = "_hr_contract_expiry"


def month_label(value: date) -> str:
    return f"{MONTH_ABBR[value.month - 1]} {value.year}"


def add_months(anchor: date, count: int) -> date:
    """
    Hari pertama bulan ke-`count` sesudah `anchor`.

    Selalu tanggal 1, jadi tidak ada kasus 31 Januari + 1 bulan yang
    harus ditebak — sumbu chart ini memang bulan, bukan tanggal.
    """
    index = (anchor.year * 12 + anchor.month - 1) + count

    return date(index // 12, index % 12 + 1, 1)


@dataclass(frozen=True)
class ContractRow:
    """Satu kontrak berjalan, sudah rata — tidak ada relasi tersisa."""

    employee_id: int
    employee_number: str
    employee_name: str

    company: str
    location: str
    department: str
    department_code: str
    section: str
    position: str

    employee_group: str
    employment_type: str
    employment_status: str

    contract_type: str
    contract_start: date | None
    contract_end: date | None

    # `None` hanya untuk kontrak tanpa tanggal akhir. Nol berarti habis
    # **hari ini** — dua keadaan yang menuntut tindakan berbeda.
    days_remaining: int | None
    expiry_status: str

    renewal_status: str
    renewal_document: str

    report_to_number: str
    report_to_name: str

    @property
    def expiry_label(self) -> str:
        return EXPIRY_LABELS[self.expiry_status]

    @property
    def renewal_label(self) -> str:
        return RENEWAL_LABELS[self.renewal_status]

    @property
    def sort_key(self) -> tuple:
        """
        Yang paling mendesak lebih dulu: Expired → yang terdekat →
        yang masih jauh, dan kontrak tanpa tanggal akhir paling akhir.

        Cukup mengurutkan `contract_end` menaik — tanggal yang sudah
        lewat memang yang terkecil. Yang perlu dijaga hanya baris tanpa
        tanggal, karena `None` tidak bisa dibandingkan dengan `date`.
        """
        return (
            self.contract_end is None,
            self.contract_end or date.max,
            self.employee_number,
            self.employee_id,
        )

    @property
    def search_text(self) -> str:
        """
        Yang dicocokkan kotak cari: **nomor dan nama pegawai**, dan
        cuma itu.

        Bukan seluruh baris: mengetik satu kata yang kebetulan ada di
        kolom Department atau Expiry Status akan menyisakan hampir
        seluruh tabel, dan hasilnya terbaca seperti pencarian yang
        rusak.
        """
        return f"{self.employee_number} {self.employee_name}"


class ContractExpiryReport:
    """
    Hasil laporan untuk satu request: populasi yang sudah rata plus
    seluruh agregatnya.

    Dirakit **sekali** dan dipakai bersama KPI, dua chart, dan tabel.
    Tiga penghitung yang membangun querysetnya masing-masing adalah cara
    paling pasti membuat kartu KPI dan tabel di satu layar menyebut
    angka yang berbeda setelah salah satu filternya diubah dan yang lain
    lupa diikutkan.
    """

    def __init__(self, rows: list[ContractRow], *, as_of: date):
        self.rows = rows
        self.as_of = as_of

    # ------------------------------------------------------------------
    # Angka pokok
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.rows)

    def count_status(self, *statuses: str) -> int:
        wanted = set(statuses)

        return sum(1 for row in self.rows if row.expiry_status in wanted)

    def follow_up_rows(self) -> list[ContractRow]:
        """
        Kontrak yang perlu ditindaklanjuti: sudah lewat, atau habis
        dalam 90 hari.

        Ini populasi chart per department — **bagian** dari populasi
        laporan, bukan populasi lain. Filter yang sama sudah menyaring
        keduanya; yang berbeda cuma potongan bucket-nya, dan itu yang
        ditulis di keterangan chart supaya tidak ada yang menyangka
        chart dan KPI berangkat dari tempat berbeda.
        """
        return [
            row for row in self.rows
            if row.expiry_status in FOLLOW_UP_STATUSES
        ]

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def timeline(self) -> list[tuple[str, int]]:
        """
        Jumlah kontrak yang berakhir per bulan, dari bulan tanggal acuan
        ke depan.

        Dua ember tambahan yang **hanya muncul kalau ada isinya**:
        "Sudah Lewat" untuk kontrak yang berakhir sebelum bulan berjalan,
        dan "> 12 Bulan" untuk yang jatuh sesudah jendela chart. Ada
        supaya jumlah seluruh batang tetap sama dengan Total Kontrak
        Aktif dikurangi kontrak tanpa tanggal akhir — chart yang
        memotong ekornya diam-diam terbaca sebagai chart yang lengkap.

        Kontrak tanpa tanggal akhir ikut sebagai ember terakhir dengan
        alasan yang sama: ia tidak punya bulan, dan menghilangkannya
        membuat selisihnya harus dicari sendiri oleh yang membacanya.
        """
        first = self.as_of.replace(day=1)
        beyond = add_months(first, TIMELINE_MONTHS)

        months = [add_months(first, index) for index in range(TIMELINE_MONTHS)]

        buckets: dict[str, int] = {month_label(item): 0 for item in months}

        past = 0
        later = 0
        undated = 0

        for row in self.rows:
            end = row.contract_end

            if end is None:
                undated += 1
            elif end < first:
                past += 1
            elif end >= beyond:
                later += 1
            else:
                buckets[month_label(end)] += 1

        series: list[tuple[str, int]] = []

        if past:
            series.append((PAST_LABEL, past))

        series.extend(buckets.items())

        if later:
            series.append((BEYOND_LABEL, later))

        if undated:
            series.append((NO_END_LABEL, undated))

        return series

    def by_department(self) -> list[tuple[str, int]]:
        """
        Kontrak yang perlu ditindaklanjuti per Department, terbanyak
        dulu.

        Nama dipakai sebagai kunci — bukan id — karena yang dibaca
        pemakainya memang namanya. Urutan kedua **kode** master supaya
        department dengan jumlah sama tidak berpindah-pindah antar
        request.
        """
        counted: Counter = Counter()
        codes: dict[str, str] = {}

        for row in self.follow_up_rows():
            counted[row.department] += 1
            codes.setdefault(row.department, row.department_code)

        return sorted(
            counted.items(),
            key=lambda item: (-item[1], codes.get(item[0], LAST_SORT_KEY)),
        )

    # ------------------------------------------------------------------
    # Rekap
    # ------------------------------------------------------------------

    def status_totals(self) -> dict[str, int]:
        """Jumlah per bucket, seluruh bucket disebut walau nol."""
        counted: dict[str, int] = defaultdict(int)

        for row in self.rows:
            counted[row.expiry_status] += 1

        return {code: counted[code] for code in EXPIRY_ORDER}


class ContractExpiryService:
    """Perakit populasi. Tidak punya satu pun jalan menulis."""

    # ------------------------------------------------------------------
    # Tanggal acuan
    # ------------------------------------------------------------------

    @staticmethod
    def as_of(context: dict) -> date:
        """
        Tanggal acuan laporan — **hari ini**, dan tidak bisa digeser
        dari luar.

        Bukan karena as-of yang bisa dipilih tidak berguna, melainkan
        karena runtime dashboard hari ini hanya melayani dua bentuk
        filter: pemilih periode dan dropdown lookup
        (`MDashboardFilters.vue`). Pemilih tanggal berarti runtime
        frontend baru, dan memakai pemilih **periode bulan** untuk
        laporan yang sebenarnya butuh satu tanggal berarti kotak yang
        terbaca seperti konfigurasi hidup padahal tidak menggeser satu
        angka pun.

        `context["as_of"]` dihormati kalau pemanggil menaruh objek
        `date` di sana — dipakai test dan pemanggil internal. Itu
        **bukan** jalan masuk dari query string: `BaseDashboardAPIView.
        get_context()` hanya menyalin kunci yang dideklarasikan sebagai
        filter di schema, dan `as_of` sengaja tidak ada di sana.
        """
        value = context.get("as_of")

        return value if isinstance(value, date) else timezone.localdate()

    # ------------------------------------------------------------------
    # Populasi
    # ------------------------------------------------------------------

    @classmethod
    def employee_queryset(cls, context: dict):
        """
        Populasi laporan: **cakupan organisasi ∩ pegawai berkontrak ∩
        filter yang dipilih**.

        Dua penyaring yang menentukan siapa "pegawai berkontrak", dan
        keduanya semantik master — bukan nama:

        * `employment_type.requires_contract=True`. Penanda yang sama
          yang dipakai `EmploymentAssignment.clean()` untuk menolak masa
          kontrak pada pegawai tetap.
        * punya **catatan kontrak** yang benar-benar terisi (Contract
          Start atau Contract End). Pegawai yang jenisnya menuntut
          kontrak tapi kolom kontraknya sama sekali kosong tidak punya
          tanggal yang bisa ditindaklanjuti — itu kelengkapan master,
          bukan masa kontrak yang akan habis. Dicatat sebagai NEXT di
          `docs/claude/reports.md`.

        Yang sengaja **tidak** ikut menyaring:

        * **Feature Applicability.** Lihat docstring modul.
        * **Periode.** Laporan ini potret satu tanggal; tidak ada satu
          kolom pun yang berubah karena bulan yang dipilih.

        Yang ikut menyaring di luar filter: `is_deleted=False` (soft
        delete) dan `is_active=True`. Yang kedua mengikuti aturan yang
        sama dengan Manpower Summary dan Employee Reporting Audit —
        kontrak orang yang sudah keluar bukan lagi pekerjaan yang
        tertunda, dan membiarkannya membuat kartu Expired penuh temuan
        yang tidak ada gunanya ditindaklanjuti.
        """
        queryset = (
            Employee.objects
            .filter(
                is_deleted=False,
                is_active=True,
                employment__employment_type__requires_contract=True,
            )
            .filter(
                Q(employment__contract_start__isnull=False)
                | Q(employment__contract_end__isnull=False)
            )
            # Seluruh kolom laporan diambil dari sini. Tanpa
            # `select_related`, satu halaman 25 baris menembak ratusan
            # query — dan yang paling mahal justru atasannya
            # (`organization__reports_to`), lompatan relasi yang tidak
            # akan pernah di-prefetch sendiri oleh Django.
            .select_related(
                "organization__company",
                "organization__location",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__reports_to",
                "employment__employee_group",
                "employment__employment_type",
                "employment__employment_status",
                "employment__contract_type",
            )
        )

        for key, path in FILTER_PATHS.items():
            value = context.get(key)

            if not value:
                continue

            if isinstance(value, (list, tuple, set)):
                queryset = queryset.filter(**{f"{path}__in": list(value)})
            else:
                queryset = queryset.filter(**{path: value})

        # **Terakhir, dan tidak pernah bisa dilewati.** Laporan adalah
        # `APIView`, jadi `filter_queryset()` milik `BaseMasterViewSet`
        # tidak pernah jalan di sini; baris inilah satu-satunya yang
        # menutup. Filter di atasnya cuma mempersempit hasilnya.
        queryset = DataScopeService.filter(
            queryset,
            EMPLOYEE_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(Employee),
        )

        return queryset.order_by(
            "employment__contract_end",
            "employee_number",
            "id",
        ).distinct()

    # ------------------------------------------------------------------
    # Renewal
    # ------------------------------------------------------------------

    @classmethod
    def open_renewals(cls, employee_ids: list[int]) -> dict[int, tuple]:
        """
        Dokumen kontrak yang **masih berjalan**, satu per pegawai.

        Satu query untuk seluruh halaman, bukan satu per baris. Yang
        diambil dokumen terbaru menurut tanggal berlaku: dua dokumen
        terbuka untuk pegawai dan jenis yang sama memang ditolak
        `EmployeeActionService`, tapi Contract Extension dan Contract
        Change adalah dua jenis yang berbeda dan boleh berdiri
        bersamaan.
        """
        if not employee_ids:
            return {}

        rows = (
            EmployeeAction.objects
            .filter(
                is_deleted=False,
                employee_id__in=employee_ids,
                action_type__in=CONTRACT_ACTION_TYPES,
                status__in=ACTION_OPEN_STATUSES,
            )
            .order_by("employee_id", "-effective_date", "-id")
            .values_list("employee_id", "status", "document_number")
        )

        latest: dict[int, tuple] = {}

        for employee_id, status, document_number in rows:
            if employee_id in latest:
                continue

            code = RENEWAL_FROM_ACTION.get(str(status))

            if code is None:
                continue

            latest[employee_id] = (code, document_number or EMPTY)

        return latest

    # ------------------------------------------------------------------
    # Perakitan
    # ------------------------------------------------------------------

    @classmethod
    def report(cls, context: dict) -> ContractExpiryReport:
        """
        Dihitung **sekali per request** dan disimpan di context — KPI,
        dua chart, dan tabelnya membaca hasil yang sama persis.
        """
        cached = context.get(CONTEXT_KEY)

        if cached is not None:
            return cached

        as_of = cls.as_of(context)

        employees = list(cls.employee_queryset(context))

        renewals = cls.open_renewals([employee.id for employee in employees])

        rows = [
            cls.build_row(
                employee,
                as_of=as_of,
                renewal=renewals.get(employee.id),
            )
            for employee in employees
        ]

        rows = cls.apply_derived_filters(rows, context)
        rows.sort(key=lambda row: row.sort_key)

        result = ContractExpiryReport(rows, as_of=as_of)

        context[CONTEXT_KEY] = result

        return result

    @classmethod
    def apply_derived_filters(
        cls,
        rows: list[ContractRow],
        context: dict,
    ) -> list[ContractRow]:
        """
        Dua filter yang tidak bisa jadi `WHERE`: Expiry Status dan
        Renewal Status keduanya **dihitung**, bukan disimpan.

        Disaring di sini, sesudah barisnya jadi dan **sebelum**
        `ContractExpiryReport` dibentuk, supaya KPI, chart, dan tabel
        tetap berangkat dari daftar yang sama persis. Menyaringnya di
        tabel saja menghasilkan layar yang kartunya menyebut 12 dan
        tabelnya berisi 3, tanpa satu pun keterangan bahwa keduanya
        menghitung hal yang berbeda.
        """
        expiry = expiry_status_code(context.get("expiry_status"))

        if expiry:
            rows = [row for row in rows if row.expiry_status == expiry]

        renewal = renewal_status_code(context.get("renewal_status"))

        if renewal:
            rows = [row for row in rows if row.renewal_status == renewal]

        return rows

    @classmethod
    def build_row(
        cls,
        employee: Employee,
        *,
        as_of: date,
        renewal: tuple | None,
    ) -> ContractRow:
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        report_to = getattr(organization, "reports_to", None)

        contract_end = getattr(employment, "contract_end", None)

        days = (contract_end - as_of).days if contract_end else None

        renewal_status, renewal_document = renewal or (
            RenewalStatus.NONE,
            EMPTY,
        )

        department = getattr(organization, "department", None)

        return ContractRow(
            employee_id=employee.id,
            employee_number=employee.employee_number or EMPTY,
            employee_name=employee.full_name,

            company=cls._label(organization, "company"),
            location=cls._label(organization, "location"),
            department=cls._label(organization, "department"),
            department_code=(
                getattr(department, "code", None) or LAST_SORT_KEY
            ),
            section=cls._label(organization, "section"),
            position=cls._label(organization, "position"),

            employee_group=cls._label(employment, "employee_group"),
            employment_type=cls._label(employment, "employment_type"),
            employment_status=cls._label(employment, "employment_status"),

            contract_type=cls._label(employment, "contract_type"),
            contract_start=getattr(employment, "contract_start", None),
            contract_end=contract_end,

            days_remaining=days,
            expiry_status=expiry_status(days),

            renewal_status=renewal_status,
            renewal_document=renewal_document,

            report_to_number=(
                (report_to.employee_number or EMPTY) if report_to else EMPTY
            ),
            report_to_name=report_to.full_name if report_to else EMPTY,
        )

    @staticmethod
    def _label(owner, relation: str) -> str:
        """
        Kolom yang memang belum diisi harus **berbunyi** sebagai belum
        diisi. Sel kosong di tengah tabel terbaca seperti kolomnya gagal
        dimuat, dan barisnya tetap membawa kontrak yang harus
        ditindaklanjuti.
        """
        if owner is None:
            return UNASSIGNED_LABEL

        value = getattr(owner, relation, None)

        return getattr(value, "name", None) or UNASSIGNED_LABEL


class ContractExpiryPresenter:
    """
    Perapi bentuk respons. Tidak ada agregasi baru di sini — semuanya
    pembacaan ulang dari `ContractExpiryReport` yang sudah jadi.
    """

    service = ContractExpiryService

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    @classmethod
    def _count(cls, context: dict, *statuses: str) -> dict:
        return {
            "value": cls.service.report(context).count_status(*statuses),
        }

    @classmethod
    def expired(cls, context: dict) -> dict:
        return cls._count(context, ExpiryStatus.EXPIRED)

    @classmethod
    def expiring_30(cls, context: dict) -> dict:
        return cls._count(context, ExpiryStatus.EXPIRING_30)

    @classmethod
    def expiring_60(cls, context: dict) -> dict:
        return cls._count(context, ExpiryStatus.EXPIRING_60)

    @classmethod
    def expiring_90(cls, context: dict) -> dict:
        return cls._count(context, ExpiryStatus.EXPIRING_90)

    @classmethod
    def active_contracts(cls, context: dict) -> dict:
        """
        Seluruh kontrak berjalan yang lolos filter.

        Kartunya ada supaya keempat kartu di sebelahnya bisa
        dijumlahkan: `Expired + ≤30 + 31–60 + 61–90 + >90 + Tanpa
        Tanggal Akhir = Total`. Tanpa kartu ini, empat angka pertama
        berdiri tanpa penyebut, dan "Expired 2" sama sekali berbeda
        artinya di tenant berkontrak 5 orang dan di tenant berkontrak
        500.
        """
        return {"value": cls.service.report(context).total}

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @classmethod
    def expiry_timeline(cls, context: dict) -> dict:
        series = cls.service.report(context).timeline()

        return {
            "categories": [label for label, _ in series],
            "datasets": [
                {
                    "label": "Kontrak Berakhir",
                    "data": [value for _, value in series],
                    "color": "primary",
                },
            ],
        }

    @classmethod
    def expiring_by_department(cls, context: dict) -> dict:
        """
        Department dengan kontrak yang perlu ditindaklanjuti, terbanyak
        dulu; ekornya dijumlahkan ke satu batang "Lainnya" supaya
        totalnya tetap sama dengan Expired + ≤30 + 31–60 + 61–90.
        """
        ordered = cls.service.report(context).by_department()

        head = ordered[:MAX_CHART_SEGMENTS]
        tail = ordered[MAX_CHART_SEGMENTS:]

        categories = [label for label, _ in head]
        data = [value for _, value in head]

        if tail:
            categories.append(OTHER_LABEL)
            data.append(sum(value for _, value in tail))

        return {
            "categories": categories,
            "datasets": [
                {
                    "label": "Perlu Ditindaklanjuti",
                    "data": data,
                    "color": "warning",
                },
            ],
        }

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    @classmethod
    def contract_table(cls, context: dict, *, page=None) -> dict:
        """
        Satu baris per kontrak berjalan, dipotong per halaman.

        `total` selalu seluruh baris yang lolos filter laporan,
        `matched` yang lolos kotak cari — dua angka berbeda arti yang
        keduanya dipakai frontend. `totals` menjumlahkan bucket-nya,
        jadi baris Total tidak ikut bergeser saat halaman diganti
        maupun saat ada yang diketik di kotak cari.
        """
        report = cls.service.report(context)

        rows = report.rows
        totals = report.status_totals()

        if page is None:
            return {
                "items": [cls.table_row(row) for row in rows],
                "total": len(rows),
                "totals": totals,
            }

        matched = page.matching(rows, text=lambda row: row.search_text)

        return page.envelope(
            items=[cls.table_row(row) for row in page.slice(matched)],
            matched=len(matched),
            total=len(rows),
            totals=totals,
        )

    @staticmethod
    def table_row(row: ContractRow) -> dict:
        return {
            "id": row.employee_id,
            "employee_number": row.employee_number,
            "employee_name": row.employee_name,
            "company": row.company,
            "location": row.location,
            "department": row.department,
            "section": row.section,
            "position": row.position,
            "employee_group": row.employee_group,
            "employment_type": row.employment_type,
            "employment_status": row.employment_status,
            "contract_type": row.contract_type,
            "contract_start": (
                row.contract_start.isoformat() if row.contract_start else EMPTY
            ),
            "contract_end": (
                row.contract_end.isoformat() if row.contract_end else EMPTY
            ),
            # Sengaja `""` dan bukan `0` untuk kontrak tanpa tanggal
            # akhir: nol hari berarti habis hari ini, dan kolom angka
            # yang menuliskan nol untuk "tidak diketahui" mengarang
            # jawaban yang paling mendesak dari data yang tidak ada.
            "days_remaining": (
                row.days_remaining if row.days_remaining is not None else EMPTY
            ),
            "expiry_status": row.expiry_label,
            "renewal_status": row.renewal_label,
            "renewal_document": row.renewal_document,
            "report_to_number": row.report_to_number,
            "report_to_name": row.report_to_name,
        }
