"""
Manpower Summary — ringkasan manajemen atas jumlah dan komposisi
tenaga kerja, READ ONLY.

Yang dijawabnya satu pertanyaan: **berapa orang, tersebar di mana, dan
komposisinya apa** — per company, location, department, Employee Group,
dan jenis kepegawaian. Bukan daftar pegawai: satu baris di sini adalah
satu kelompok, bukan satu orang.

Tiga laporan yang sering tertukar dengannya, dan bedanya bukan
tampilannya:

* **Employee Master** (`apps/hr/api/employee`) — tempat data pegawai
  **diisi dan dirawat**. Punya tulis; yang ini tidak.
* **Employee Reporting Audit** (`../employee_reporting_audit`) — audit
  **kelengkapan** struktur, garis pelaporan, dan akun. Satu baris per
  pegawai, karena yang dicari justru baris yang datanya bolong.
* **HR Period Summary** (`../period_summary`) — hasil **operasional**
  per periode (hadir, cuti, lembur). Angkanya berubah kalau bulannya
  diganti; angka di sini tidak.

Populasinya:

```
Population = Authorized Organization Scope ∩ filter yang dipilih
```

**Feature Applicability sengaja tidak menyaring.** Manpower adalah
angka organisasi, bukan angka proses: direksi yang seluruh proses
HR-nya dimatikan tetap orang yang digaji dan tetap menempati kursi di
struktur. Menyaringnya membuat "Total Headcount" di laporan manpower
lebih kecil daripada jumlah orang yang benar-benar bekerja, dan tidak
ada satu pun di layar yang memberi tahu selisihnya. Aturan yang sama
dengan Employee Reporting Audit — lihat `docs/claude/reports.md`.

Tidak ada satu pun kode Employee Group yang dibaca di berkas ini
(`BOARD`, `BOD`, `MANAGEMENT`, …). Yang memutuskan komposisi cuma
master: `EmployeeGroup` untuk pengelompokan, dan
`EmploymentType.requires_contract` untuk belah Permanent/Contract.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.hr.models import Employee


UNASSIGNED_LABEL = "Belum Ditentukan"

# Kunci urut untuk master yang kodenya belum terisi. Bukan string
# kosong: yang belum ditentukan harus berdiri di **ujung** daftar, dan
# string kosong justru mengurutkannya paling depan — baris "Belum
# Ditentukan" di baris pertama tabel terbaca seperti kelompok
# terpenting. `~` (0x7E) berdiri sesudah seluruh huruf dan angka yang
# dipakai kode master.
LAST_SORT_KEY = "~~~"

# Ekor chart dipotong dan dijumlahkan ke satu batang. Dua puluh batang
# tidak terbaca, dan totalnya tetap utuh — pola yang sama dengan
# `department_comparison` di HR Period Summary dan donut HR Dashboard.
MAX_CHART_SEGMENTS = 8
OTHER_LABEL = "Lainnya"


# Cakupan data per baris. Sama persis dengan `EMPLOYEE_SCOPE` di HR
# Period Summary, Employee Reporting Audit, dan `EmployeeViewSet.
# data_scope` — kalau yang di sana berubah, yang di sini ikut.
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
# dua laporan HR lainnya supaya satu tombol Location tidak berperilaku
# berbeda di tiga layar.
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


CONTEXT_KEY = "_hr_manpower_summary"


@dataclass(frozen=True)
class ManpowerRow:
    """
    Satu pegawai, sudah rata dan hanya membawa yang dipakai menghitung.

    Sengaja bukan `Employee`: laporan ini tidak pernah menampilkan satu
    pun kolom identitas, dan merakit ribuan instance model untuk
    kemudian cuma menjumlahkannya adalah memori yang dibayar tanpa ada
    yang membacanya.
    """

    employee_id: int

    company_code: str
    company: str
    location_code: str
    location: str
    department_code: str
    department: str

    employee_group: str
    employment_type: str

    # `EmploymentType.requires_contract`, dan `None` kalau pegawainya
    # belum punya jenis kepegawaian sama sekali. Tiga keadaan, bukan
    # dua — lihat `ManpowerSummary`.
    contract_based: bool | None

    @property
    def group_key(self) -> tuple:
        """Kunci grouping tabel: company → location → department."""
        return (
            self.company_code,
            self.company,
            self.location_code,
            self.location,
            self.department_code,
            self.department,
        )

    @property
    def search_text(self) -> str:
        return f"{self.company} {self.location} {self.department}"


@dataclass(frozen=True)
class Composition:
    """
    Belah kepegawaian satu kelompok, **tiga angka**.

    `permanent + contract + unspecified = headcount` selalu benar,
    apa pun isi master Employment Type-nya. Yang tidak dijamin adalah
    `permanent + contract = headcount`: itu baru benar kalau setiap
    pegawai punya jenis kepegawaian, dan `unspecified` ada justru
    supaya selisihnya kelihatan alih-alih menguap.
    """

    headcount: int = 0
    permanent: int = 0
    contract: int = 0
    unspecified: int = 0

    def add(self, row: ManpowerRow) -> "Composition":
        contract_based = row.contract_based

        return Composition(
            headcount=self.headcount + 1,
            permanent=self.permanent + (1 if contract_based is False else 0),
            contract=self.contract + (1 if contract_based is True else 0),
            unspecified=(
                self.unspecified + (1 if contract_based is None else 0)
            ),
        )


@dataclass(frozen=True)
class GroupRow:
    """Satu baris tabel agregat: satu kombinasi company/location/department."""

    company_code: str
    company: str
    location_code: str
    location: str
    department_code: str
    department: str
    composition: Composition

    @property
    def search_text(self) -> str:
        return f"{self.company} {self.location} {self.department}"


class ManpowerSummary:
    """
    Hasil laporan untuk satu request: populasi yang sudah rata plus
    seluruh agregatnya.

    Dirakit **sekali** dan dipakai bersama oleh KPI, chart, dan tabel.
    Itu bukan sekadar penghematan query: tiga penghitung yang membangun
    querysetnya masing-masing adalah cara paling pasti membuat KPI dan
    tabel di satu layar menyebut angka yang berbeda setelah salah satu
    filternya diubah dan yang lain lupa diikutkan.
    """

    def __init__(self, rows: list[ManpowerRow]):
        self.rows = rows

    # ------------------------------------------------------------------
    # Angka pokok
    # ------------------------------------------------------------------

    @property
    def headcount(self) -> int:
        return len(self.rows)

    @property
    def composition(self) -> Composition:
        total = Composition()

        for row in self.rows:
            total = total.add(row)

        return total

    # ------------------------------------------------------------------
    # Breakdown
    # ------------------------------------------------------------------

    def count_by(self, attribute: str) -> list[tuple[str, int]]:
        """
        Jumlah pegawai per nilai satu kolom, terbanyak dulu.

        Nama dipakai sebagai kunci — bukan id — karena yang dibaca
        pemakainya memang namanya, dan dua master dengan nama sama
        adalah masalah master, bukan masalah laporan (Branch/Department/
        Section berlabel ambigu sudah tercatat sebagai gap tersendiri).
        Urutan kedua abjad supaya hasil dengan jumlah sama tidak
        berpindah-pindah antar request.
        """
        counted = Counter(getattr(row, attribute) for row in self.rows)

        return sorted(counted.items(), key=lambda item: (-item[1], item[0]))

    def composition_by(self, attribute: str) -> list[tuple[str, Composition]]:
        """`count_by`, tapi tiap kelompok ikut membawa belah kepegawaiannya."""
        buckets: dict[str, Composition] = defaultdict(Composition)

        for row in self.rows:
            key = getattr(row, attribute)

            buckets[key] = buckets[key].add(row)

        return sorted(
            buckets.items(),
            key=lambda item: (-item[1].headcount, item[0]),
        )

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    def group_rows(self) -> list[GroupRow]:
        """
        Satu baris per kombinasi company → location → department.

        Diurutkan menurut **kode** master, bukan jumlah: tabel ini
        dibaca sebagai daftar organisasi, dan urutan yang berpindah
        tiap kali ada satu orang pindah department membuat pembacanya
        kehilangan barisnya sendiri.
        """
        buckets: dict[tuple, Composition] = defaultdict(Composition)

        for row in self.rows:
            key = row.group_key

            buckets[key] = buckets[key].add(row)

        return [
            GroupRow(
                company_code=key[0],
                company=key[1],
                location_code=key[2],
                location=key[3],
                department_code=key[4],
                department=key[5],
                composition=value,
            )
            for key, value in sorted(buckets.items())
        ]


class ManpowerSummaryService:
    """Perakit populasi. Tidak punya satu pun jalan menulis."""

    @classmethod
    def employee_queryset(cls, context: dict):
        """
        Populasi laporan: **cakupan organisasi ∩ filter yang dipilih**.

        Dua hal yang sengaja tidak ikut menyaring:

        * **Feature Applicability.** Manpower adalah angka organisasi,
          bukan angka proses. Lihat docstring modul.
        * **Periode.** Laporan ini adalah potret hari ini; tidak ada
          satu kolom pun yang berubah karena bulan yang dipilih.

        Yang ikut menyaring di luar filter: `is_deleted=False` (soft
        delete) dan `is_active=True`. Yang kedua yang menjadikannya
        *headcount* dan bukan *jumlah baris pegawai yang pernah ada* —
        orang yang sudah keluar bukan lagi manpower, dan menghitungnya
        membuat angka laporan naik terus selamanya.
        """
        queryset = Employee.objects.filter(is_deleted=False, is_active=True)

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
        return DataScopeService.filter(
            queryset,
            EMPLOYEE_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(Employee),
        ).distinct()

    # Kolom yang benar-benar dibaca laporan ini, dan cuma itu.
    # `values_list` alih-alih instance model: satu tenant tiga ribu
    # pegawai berarti tiga ribu objek Django plus relasinya, dirakit
    # untuk kemudian hanya dijumlahkan.
    ROW_FIELDS = (
        "id",
        "organization__company__code",
        "organization__company__name",
        "organization__location__code",
        "organization__location__name",
        "organization__department__code",
        "organization__department__name",
        "employment__employee_group__name",
        "employment__employment_type__name",
        "employment__employment_type__requires_contract",
    )

    @classmethod
    def summary(cls, context: dict) -> ManpowerSummary:
        """
        Dihitung **sekali per request** dan disimpan di context — KPI,
        lima chart, dan tabelnya membaca hasil yang sama persis.
        """
        cached = context.get(CONTEXT_KEY)

        if cached is not None:
            return cached

        rows = [
            cls.build_row(values)
            for values in cls.employee_queryset(context).values_list(
                *cls.ROW_FIELDS
            )
        ]

        result = ManpowerSummary(rows)

        context[CONTEXT_KEY] = result

        return result

    @classmethod
    def build_row(cls, values: tuple) -> ManpowerRow:
        (
            employee_id,
            company_code,
            company,
            location_code,
            location,
            department_code,
            department,
            employee_group,
            employment_type,
            requires_contract,
        ) = values

        return ManpowerRow(
            employee_id=employee_id,
            company_code=cls._sort_key(company_code),
            company=cls._label(company),
            location_code=cls._sort_key(location_code),
            location=cls._label(location),
            department_code=cls._sort_key(department_code),
            department=cls._label(department),
            employee_group=cls._label(employee_group),
            employment_type=cls._label(employment_type),
            contract_based=requires_contract,
        )

    @staticmethod
    def _label(value) -> str:
        """
        Kolom yang memang belum diisi harus **berbunyi** sebagai belum
        diisi. Sel kosong di tengah tabel agregat terbaca seperti
        kolomnya gagal dimuat, dan barisnya tetap membawa headcount
        yang harus ikut dijumlahkan.
        """
        return value or UNASSIGNED_LABEL

    @staticmethod
    def _sort_key(code) -> str:
        """Kode master untuk pengurutan; yang kosong jatuh ke belakang."""
        return code or LAST_SORT_KEY


class ManpowerSummaryPresenter:
    """
    Perapi bentuk respons. Tidak ada agregasi baru di sini — semuanya
    pembacaan ulang dari `ManpowerSummary` yang sudah jadi.
    """

    service = ManpowerSummaryService

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    @classmethod
    def headcount(cls, context: dict) -> dict:
        return {"value": cls.service.summary(context).headcount}

    @classmethod
    def permanent(cls, context: dict) -> dict:
        return {"value": cls.service.summary(context).composition.permanent}

    @classmethod
    def contract(cls, context: dict) -> dict:
        return {"value": cls.service.summary(context).composition.contract}

    @classmethod
    def unspecified_employment_type(cls, context: dict) -> dict:
        """
        Sisa yang tidak masuk Permanent maupun Contract.

        Kartunya ada supaya `Permanent + Contract < Headcount` tidak
        pernah menjadi selisih yang harus dicari sendiri oleh yang
        membacanya. Di tenant yang masternya rapi angkanya nol, dan itu
        justru jawaban yang berguna.
        """
        return {
            "value": cls.service.summary(context).composition.unspecified,
        }

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @classmethod
    def composition_chart(cls, context: dict, attribute: str) -> dict:
        """
        Batang bertumpuk Permanent/Contract per kelompok organisasi.

        Tinggi tiap batang = headcount kelompok itu, jadi chart dan KPI
        menjawab pertanyaan yang sama dengan angka yang sama.
        "Belum Ditentukan" hanya ikut sebagai tumpukan ketiga kalau
        memang ada isinya — legenda dengan satu entri yang selalu nol
        cuma derau.
        """
        summary = cls.service.summary(context)

        ordered = summary.composition_by(attribute)

        head = ordered[:MAX_CHART_SEGMENTS]
        tail = ordered[MAX_CHART_SEGMENTS:]

        categories = [label for label, _ in head]

        permanent = [item.permanent for _, item in head]
        contract = [item.contract for _, item in head]
        unspecified = [item.unspecified for _, item in head]

        if tail:
            categories.append(OTHER_LABEL)

            permanent.append(sum(item.permanent for _, item in tail))
            contract.append(sum(item.contract for _, item in tail))
            unspecified.append(sum(item.unspecified for _, item in tail))

        datasets = [
            {"label": "Permanent", "data": permanent, "color": "primary"},
            {"label": "Contract", "data": contract, "color": "warning"},
        ]

        if any(unspecified):
            datasets.append(
                {
                    "label": UNASSIGNED_LABEL,
                    "data": unspecified,
                    "color": "neutral",
                }
            )

        return {"categories": categories, "datasets": datasets}

    @classmethod
    def company_breakdown(cls, context: dict) -> dict:
        return cls.composition_chart(context, "company")

    @classmethod
    def location_breakdown(cls, context: dict) -> dict:
        return cls.composition_chart(context, "location")

    @classmethod
    def department_breakdown(cls, context: dict) -> dict:
        return cls.composition_chart(context, "department")

    @classmethod
    def share_chart(cls, context: dict, attribute: str) -> dict:
        """
        Donut proporsi. Ekornya dipotong jadi "Lainnya" — totalnya tetap
        sama dengan Total Headcount, dan itu yang membuat donut ini bisa
        dibandingkan langsung dengan kartu KPI di atasnya.
        """
        summary = cls.service.summary(context)

        ordered = summary.count_by(attribute)

        head = ordered[:MAX_CHART_SEGMENTS]
        tail = ordered[MAX_CHART_SEGMENTS:]

        series = [
            {"label": label, "value": value}
            for label, value in head
        ]

        if tail:
            series.append(
                {
                    "label": OTHER_LABEL,
                    "value": sum(value for _, value in tail),
                }
            )

        total = sum(item["value"] for item in series)

        for item in series:
            item["percentage"] = (
                round(item["value"] / total * 100, 1) if total else 0
            )

        return {"series": series, "total": total}

    @classmethod
    def employee_group_breakdown(cls, context: dict) -> dict:
        return cls.share_chart(context, "employee_group")

    @classmethod
    def employment_type_breakdown(cls, context: dict) -> dict:
        return cls.share_chart(context, "employment_type")

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    @classmethod
    def manpower_table(cls, context: dict, *, page=None) -> dict:
        """
        Satu baris per company → location → department, dipotong per
        halaman.

        Tiga angka yang sengaja dihitung dari tempat berbeda:

        * `items`   — hanya halaman yang diminta, sesudah kotak cari
        * `matched` — baris yang lolos kotak cari, untuk jumlah halaman
        * `total` + `totals` — **seluruh** kelompok yang lolos filter
          laporan; `totals` menjumlahkan pegawainya, bukan barisnya

        Baris Total karena itu tidak ikut berubah saat halaman digeser
        maupun saat ada yang diketik di kotak cari — dan `totals`
        selalu sama persis dengan kartu KPI di atas.
        """
        summary = cls.service.summary(context)

        rows = summary.group_rows()

        totals = cls.composition_values(summary.composition)

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
    def composition_values(composition: Composition) -> dict:
        return {
            "headcount": composition.headcount,
            "permanent": composition.permanent,
            "contract": composition.contract,
            "unspecified": composition.unspecified,
        }

    @classmethod
    def table_row(cls, row: GroupRow) -> dict:
        """
        `id` dirakit dari kombinasi organisasinya, bukan dari id baris
        master mana pun: yang diwakili baris ini adalah **kelompok**,
        dan meminjam id company atau department membuat frontend
        menyangka baris ini bisa dibuka jadi dokumen.

        Yang dirangkai **kodenya**, bukan namanya: Branch/Department/
        Section di sistem ini masih bisa punya nama yang sama persis di
        dua company, dan dua baris ber-`id` sama membuat daftar
        ber-`:key` di frontend merender salah satunya dua kali.
        """
        return {
            "id": f"{row.company_code}|{row.location_code}"
                  f"|{row.department_code}",
            "company": row.company,
            "location": row.location,
            "department": row.department,
            **cls.composition_values(row.composition),
        }
