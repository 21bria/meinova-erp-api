"""
Manpower Movement — perubahan jumlah tenaga kerja dalam satu periode,
READ ONLY.

Yang dijawabnya satu pertanyaan, dan jawabannya harus berupa
persamaan yang tertutup:

```
Opening Headcount + Join + Transfer In − Transfer Out − Exit
    = Closing Headcount
```

Bedanya dengan **Manpower Summary** di sebelah bukan tampilannya:
Summary adalah potret **hari ini** dan memakai `is_active`; laporan ini
adalah **selisih antara dua tanggal** dan sama sekali tidak membaca
`is_active`. Orang yang sudah keluar bulan lalu tetap harus terhitung
di Opening bulan lalu — kalau tidak, Opening akan berubah tiap kali ada
yang resign, dan laporan bulan Januari yang dibuka bulan Juni
menunjukkan angka yang berbeda dari yang dicetak bulan Februari.

--------------------------------------------------------------------
Sumber kebenaran, dan apa yang **tidak** ada
--------------------------------------------------------------------

Audit sebelum laporan ini ditulis menemukan tiga hal, dan ketiganya
menentukan bentuk laporan ini:

1. **Tidak ada satu pun riwayat penempatan organisasi.**
   `OrganizationAssignment` menyimpan keadaan sekarang, satu baris per
   pegawai. Tidak ada tabel yang menyimpan "dulu di mana".
   `EmployeeMovement` di `apps/hr/models/employee_history.py` **bukan**
   jawabannya: modulnya tidak pernah diimpor, tidak punya migrasi, dan
   tabelnya tidak ada — kode mati yang bentuknya justru mirip solusi.

2. **Join dan Exit memang bisa direkonstruksi**, dan cuma dari tanggal:
   `EmploymentAssignment.join_date` dan `termination_date`. Keduanya
   kolom bersejarah yang `EmploymentService.PROTECTED_FIELDS`
   melindunginya (`termination_date`) atau memang koreksi HR biasa
   (`join_date`).

3. **Transfer sebelumnya tidak meninggalkan jejak apa pun.**
   `OrganizationService` dulu tidak punya padanan `PROTECTED_FIELDS`,
   jadi satu PATCH ke form Employee memindahkan orang antarperusahaan
   tanpa dokumen, tanpa persetujuan, dan tanpa audit trail. Itu sudah
   ditutup — lihat `PROTECTED_FIELDS` di
   `apps/hr/api/employee/services/organization_service.py`. Sejak
   penjagaan itu, mutasi menerbitkan `EmployeeAction`, dan **dokumen
   itulah** satu-satunya sumber Transfer In/Out di sini.

Konsekuensinya jujur dan harus dibaca sebagai bagian dari kontrak:
**Transfer In/Out hanya terisi untuk periode sesudah penjagaan itu
berlaku.** Periode sebelumnya menampilkan 0, dan itu bukan "tidak ada
mutasi" melainkan "tidak ada yang mencatatnya". Laporan ini tidak
menebak mutasi lama dari master hari ini: angka yang direkonstruksi
dari master terbaca persis seperti angka yang benar, dan selisihnya
baru ketahuan bertahun-tahun kemudian.

--------------------------------------------------------------------
Batas yang disengaja
--------------------------------------------------------------------

* **Penempatan dibaca dari keadaan sekarang.** Baris Join dan Exit
  memakai company/location/department pegawainya **hari ini**, bukan
  saat peristiwanya. Selama belum ada riwayat penempatan, itu satu
  satunya yang diketahui. Untuk baris Transfer, dua ujungnya justru
  diketahui — dokumennya menyimpan keduanya.
* **Transfer dinilai pada batas company/branch/location.** Cuma tiga
  dimensi itu yang `EmployeeAction` simpan sebagai id di **kedua**
  ujungnya (`company_id` didenormalisasi saat dokumen dibuat,
  `proposed_company_id` diisi usulannya). Department dan section hanya
  ada di sisi usulan; sisi lamanya cuma ada sebagai **nama** di
  `values_before`, dan mencocokkan riwayat lewat nama adalah cara
  laporan mulai berbohong begitu ada master yang diganti nama.
* **`is_active` tidak dibaca sama sekali**, dan itu menutup satu
  kebocoran: `Employee.is_active` masih bisa dimatikan langsung dari
  form tanpa mengisi `termination_date`. Kalau headcount di sini
  memakainya, orang yang dinonaktifkan tanpa tanggal akan hilang dari
  Closing tanpa pernah muncul sebagai Exit — dan identitasnya pecah
  tanpa ada yang tahu sebabnya.
* **Pegawai tanpa `join_date` tidak bisa dilaporkan** dan sengaja
  dikeluarkan, bukan dianggap bergabung di awal waktu. Jumlahnya
  diterbitkan sebagai KPI tersendiri supaya populasinya bisa
  direkonsiliasi dengan Manpower Summary alih-alih diam-diam berbeda.
* **`variance` selalu ikut dikirim.** Selisih antara Closing yang
  dihitung dari tanggal dan Closing hasil identitas. Nol untuk seluruh
  keadaan yang dijaga test; kalau suatu saat tidak nol, itu harus
  **terlihat** di payload dan bukan tertutup pembulatan diam-diam.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models.functions import Coalesce

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.hr.models import (
    EmployeeAction,
    EmployeeActionStatus,
    Employee,
    ORGANIZATION_ACTION_TYPES,
)

from .movements import (
    MOVEMENT_ORDER,
    MOVEMENT_SIGNS,
    MovementType,
    movement_label,
)


EMPTY = ""
UNASSIGNED_LABEL = "Belum Ditentukan"

MAX_CHART_SEGMENTS = 8
OTHER_LABEL = "Lainnya"

NO_REASON_LABEL = "Tidak Disebutkan"


# Cakupan data per pegawai. Sama persis dengan `EMPLOYEE_SCOPE` di
# Manpower Summary, Contract Expiry, Employee Reporting Audit, dan
# `EmployeeViewSet.data_scope` — kalau yang di sana berubah, yang di
# sini ikut.
EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}


# Cakupan untuk **sisi lama** dokumen mutasi. `EmployeeAction`
# mendenormalisasi company/branch/location saat dokumen dibuat — itu
# penempatan pegawainya sebelum pindah.
ACTION_SCOPE_FROM = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    # Division/department/section **tidak** ada di dokumen sebagai id
    # sisi lama, jadi ketiganya jatuh ke penempatan pegawainya sekarang.
    # Itu pendekatan, dan pendekatan yang disengaja: alternatifnya
    # membiarkan ketiganya kosong di peta, dan
    # `DataScopeService.filter()` **melewati** jenis yang tidak ada di
    # peta — cakupan setingkat department jadi tidak menyaring apa pun,
    # dan baris milik department lain ikut terbaca. Salah ke arah yang
    # aman lebih baik daripada bocor tanpa suara.
    "division": "employee__organization__division",
    "department": "employee__organization__department",
    "section": "employee__organization__section",
    "own": "employee__user_id",
}


# Cakupan untuk **sisi baru**. Menunjuk anotasi hasil `Coalesce`, bukan
# `proposed_*` langsung: usulan yang dikosongkan berarti "tidak
# berubah", dan menyaringnya apa adanya akan membuang mutasi yang cuma
# memindahkan department — dokumen yang paling sering terjadi.
ACTION_SCOPE_TO = {
    "company": "to_company",
    "branch": "to_branch",
    "location": "to_location",
    # Alasan yang sama dengan `ACTION_SCOPE_FROM`. Untuk sisi baru,
    # penempatan sekarang justru **lebih** tepat: itu memang hasil
    # mutasinya, selama belum ada mutasi berikutnya.
    "division": "employee__organization__division",
    "department": "employee__organization__department",
    "section": "employee__organization__section",
    "own": "employee__user_id",
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


# Filter yang bisa dinilai pada **kedua** ujung dokumen mutasi. Yang
# tidak ada di sini (department, section, employee group, employment
# type/status) tetap mempersempit Join/Exit/headcount, tapi tidak ikut
# menentukan sebuah mutasi masuk atau keluar — sisi lamanya memang
# tidak tersimpan sebagai id. Lihat docstring modul.
ACTION_FILTER_PATHS = {
    "company": ("company_id", "to_company"),
    "branch": ("branch_id", "to_branch"),
    "location": ("location_id", "to_location"),
}


# Filter organisasi yang **tidak** bisa dinilai per ujung, jadi dinilai
# dari penempatan pegawainya sekarang — untuk kedua ujung sekaligus.
#
# Tanpa ini, menyaring laporan ke satu department akan tetap menghitung
# seluruh pegawai yang punya dokumen mutasi, department mana pun mereka,
# karena tidak ada satu baris pun di `ACTION_FILTER_PATHS` yang
# membuangnya. Headcount lampau ikut menggelembung, dan
# menggelembungnya persis sebanyak orang yang kebetulan pernah pindah.
ACTION_FALLBACK_FILTER_PATHS = {
    "department": "employee__organization__department_id",
    "section": "employee__organization__section_id",
}


# Filter yang menyatakan **di mana** seseorang ditempatkan. Dipisahkan
# dari sisanya karena cuma kelompok ini yang penempatannya bisa berubah
# di tengah periode — dan karena itu cuma kelompok ini yang harus
# diputar mundur saat menghitung headcount pada tanggal lampau.
# `employee_group` dan `employment_type/status` tidak ikut: keduanya
# atribut kepegawaian, bukan penempatan, dan dokumen mutasi tidak
# menyimpan sisi lamanya sama sekali.
ORG_FILTER_KEYS = {
    "company",
    "branch",
    "location",
    "department",
    "section",
}


CONTEXT_KEY = "_hr_manpower_movement"


# ----------------------------------------------------------------------
# Baris
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class MovementRow:
    """Satu peristiwa, bukan satu pegawai.

    Orang yang bergabung lalu pindah lokasi dalam periode yang sama
    menghasilkan **dua** baris; itu memang yang harus terlihat di
    laporan pergerakan.
    """

    employee_id: int
    employee_number: str
    employee_name: str

    movement_type: str
    movement_date: date

    company: str
    location: str
    department: str
    position: str

    movement_from: str
    movement_to: str

    document_number: str
    reason: str

    @property
    def type_label(self) -> str:
        return movement_label(self.movement_type)

    @property
    def sign(self) -> int:
        return MOVEMENT_SIGNS.get(self.movement_type, 0)

    @property
    def sort_key(self) -> tuple:
        # Kronologis, lalu jenis mengikuti urutan jembatan, lalu nomor
        # pegawai. Urutan ketiga bukan hiasan: tanpa kunci yang stabil,
        # dua baris bertanggal sama bisa bertukar tempat antarhalaman
        # dan tabel terlihat berubah sendiri saat dipaginasi.
        try:
            type_order = MOVEMENT_ORDER.index(self.movement_type)
        except ValueError:
            type_order = len(MOVEMENT_ORDER)

        return (self.movement_date, type_order, self.employee_number)

    @property
    def search_text(self) -> str:
        return f"{self.employee_number} {self.employee_name} {self.document_number}"


@dataclass
class ManpowerMovementReport:
    """Hasil satu request. Seluruh KPI, chart, dan tabel membacanya."""

    opening: int
    closing: int
    rows: list[MovementRow]
    missing_join_date: int
    exit_reasons: Counter = field(default_factory=Counter)

    # ------------------------------------------------------------------
    # Suku identitas
    # ------------------------------------------------------------------

    def count(self, movement_type: str) -> int:
        return sum(
            1 for row in self.rows if row.movement_type == movement_type
        )

    @property
    def joins(self) -> int:
        return self.count(MovementType.JOIN)

    @property
    def transfers_in(self) -> int:
        return self.count(MovementType.TRANSFER_IN)

    @property
    def transfers_out(self) -> int:
        return self.count(MovementType.TRANSFER_OUT)

    @property
    def internal_moves(self) -> int:
        return self.count(MovementType.INTERNAL_MOVE)

    @property
    def exits(self) -> int:
        return self.count(MovementType.EXIT)

    @property
    def net_change(self) -> int:
        return self.closing - self.opening

    @property
    def expected_closing(self) -> int:
        """Closing menurut identitas, bukan menurut tanggal."""
        return self.opening + sum(row.sign for row in self.rows)

    @property
    def variance(self) -> int:
        """
        Selisih antara dua cara menghitung Closing yang seharusnya
        selalu sama.

        Diterbitkan, bukan di-assert: laporan yang melempar 500 saat
        datanya ganjil tidak menolong siapa pun, sedangkan angka yang
        diam-diam dibulatkan agar cocok justru berbahaya. Nol untuk
        seluruh keadaan yang dijaga test.
        """
        return self.closing - self.expected_closing

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def bridge(self) -> list[tuple[str, int]]:
        """
        Jembatan Opening → Closing, bertanda.

        Keluar dan Exit dikirim **negatif** supaya aritmetikanya
        terlihat di chart-nya sendiri: enam batang yang semuanya
        positif memaksa pembacanya mengingat mana yang dikurangkan.
        """
        return [
            ("Opening", self.opening),
            ("Join", self.joins),
            ("Transfer In", self.transfers_in),
            ("Transfer Out", -self.transfers_out),
            ("Exit", -self.exits),
            ("Closing", self.closing),
        ]

    def by_exit_reason(self) -> list[tuple[str, int]]:
        """Alasan keluar, terbanyak dulu."""
        return sorted(
            self.exit_reasons.items(),
            key=lambda item: (-item[1], item[0]),
        )

    def type_totals(self) -> dict:
        """Rekap per jenis untuk baris Total tabel."""
        totals = {
            code: self.count(code)
            for code in MOVEMENT_ORDER
        }

        totals["variance"] = self.variance

        return totals


# ----------------------------------------------------------------------
# Perakit
# ----------------------------------------------------------------------


class ManpowerMovementService:
    """Perakit laporan. Tidak punya satu pun jalan menulis."""

    # ------------------------------------------------------------------
    # Periode
    # ------------------------------------------------------------------

    @staticmethod
    def bounds(context: dict) -> tuple[date, date]:
        period = context.get("period") or {}

        start = period.get("start")
        end = period.get("end")

        # Periode yang tidak terisi jatuh ke bulan berjalan lewat
        # `resolve_period`; ini cuma jaring terakhir supaya service
        # tetap bisa dipanggil langsung dari test dan management
        # command tanpa merakit dict periode utuh.
        today = date.today()

        if start is None or end is None:
            start = today.replace(day=1)
            end = today

        return start, end

    # ------------------------------------------------------------------
    # Populasi
    # ------------------------------------------------------------------

    @classmethod
    def employee_queryset(cls, context: dict):
        """
        Populasi laporan: **cakupan organisasi ∩ filter yang dipilih**.

        `is_active` sengaja **tidak** ikut menyaring — lihat docstring
        modul. Yang menentukan seseorang terhitung pada sebuah tanggal
        cuma `join_date` dan `termination_date`.
        """
        queryset = Employee.objects.filter(is_deleted=False)

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
        # menutup.
        return DataScopeService.filter(
            queryset,
            EMPLOYEE_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(Employee),
        ).distinct()

    @classmethod
    def base_queryset(cls, context: dict):
        """
        Populasi **tanpa** saringan organisasi dan tanpa cakupan.

        Dipakai satu-satunya untuk menghitung ulang penempatan lampau;
        filter non-organisasi (Employee Group, Employment Type/Status)
        tetap ikut karena keduanya atribut kepegawaian yang tidak
        berpindah bersama orangnya.
        """
        queryset = Employee.objects.filter(is_deleted=False)

        for key, path in FILTER_PATHS.items():
            if key in ORG_FILTER_KEYS:
                continue

            value = context.get(key)

            if not value:
                continue

            if isinstance(value, (list, tuple, set)):
                queryset = queryset.filter(**{f"{path}__in": list(value)})
            else:
                queryset = queryset.filter(**{path: value})

        return queryset

    @staticmethod
    def _dated(queryset, on: date):
        """
        Yang berstatus pegawai **pada detik awal tanggal `on`**.

        Ini pencacahan *sesaat*, bukan pencacahan *sehari*, dan bedanya
        menentukan apakah identitasnya tertutup:

        * `join_date < on` — **tegas**, bukan `<=`. Orang yang bergabung
          tepat di hari pertama periode belum ada saat periodenya
          dibuka; ia masuk lewat suku Join. Dengan `<=` ia terhitung di
          Opening **dan** di Join sekaligus, dan Closing meleset satu
          untuk tiap orang yang bergabung di tanggal 1.
        * `termination_date >= on` — orang yang hari terakhir bekerjanya
          tepat tanggal `on` masih ada saat itu dibuka.

        Pasangannya di `report()`: Opening dibaca pada `start`, Closing
        pada `end + 1 hari`. Keduanya detik batas, bukan hari — dan
        karena itu orang yang hari terakhirnya jatuh di akhir periode
        terhitung sebagai Exit dan **tidak** ikut di Closing.
        """
        return (
            queryset
            .filter(
                employment__join_date__isnull=False,
                employment__join_date__lt=on,
            )
            .exclude(employment__termination_date__lt=on)
        )

    @classmethod
    def _rewind(cls, context: dict, on: date) -> dict:
        """
        Dokumen mutasi paling awal **sesudah** `on`, per pegawai.

        Inilah yang memberi tahu di mana seseorang berada pada tanggal
        lampau: sisi lama dokumen berikutnya **adalah** penempatannya
        saat itu. Tanpa langkah ini, headcount lampau dihitung dari
        penempatan hari ini, dan orang yang sudah pindah keluar akan
        hilang dari Opening lokasinya sendiri — Opening yang berubah
        surut tiap ada mutasi baru, padahal bulan lampau sudah lewat.

        Yang diambil hanya dokumen **paling awal**: penempatan pada
        `on` adalah asal dari perpindahan berikutnya, bukan asal dari
        perpindahan terjauh.
        """
        dated_ids = set(
            cls._dated(cls.base_queryset(context), on)
            .values_list("pk", flat=True)
        )

        if not dated_ids:
            return {}

        documents = (
            cls._org_actions()
            .filter(
                effective_date__gt=on,
                employee_id__in=dated_ids,
            )
            .order_by("employee_id", "effective_date", "pk")
        )

        earliest: dict[int, object] = {}

        for action in documents:
            earliest.setdefault(action.employee_id, action)

        return earliest

    @classmethod
    def headcount_at(cls, context: dict, on: date) -> int:
        """
        Jumlah kepala pada tanggal `on`, di dalam populasi yang
        dilaporkan.

        Dua kelompok, dan yang kedua yang membuat identitasnya
        tertutup:

        * pegawai yang penempatannya **belum berubah lagi** sesudah
          tanggal ini — dinilai dari penempatannya sekarang;
        * pegawai yang **masih akan pindah** sesudahnya — dinilai dari
          sisi lama dokumen mutasi berikutnya, bukan dari penempatan
          hari ini.

        Tanpa kelompok kedua, orang yang pindah keluar lokasi di tengah
        periode tidak terhitung di Opening lokasi itu **maupun** di
        Closing-nya, sementara Transfer Out tetap mengurangi satu — dan
        identitasnya meleset persis sebanyak mutasi yang terjadi.
        """
        moved = cls._rewind(context, on)

        unmoved = (
            cls._dated(cls.employee_queryset(context), on)
            .exclude(pk__in=list(moved))
            .count()
        )

        if not moved:
            return unmoved

        inside = cls._inside_ids(
            context,
            cls._org_actions().filter(
                pk__in=[action.pk for action in moved.values()],
            ),
            ACTION_SCOPE_FROM,
            0,
            context.get("user"),
        )

        return unmoved + sum(
            1 for action in moved.values() if action.pk in inside
        )

    # ------------------------------------------------------------------
    # Join & Exit
    # ------------------------------------------------------------------

    RELATED = (
        "organization__company",
        "organization__location",
        "organization__department",
        "organization__position",
        "employment__termination_reason",
    )

    @classmethod
    def join_rows(cls, context: dict, start: date, end: date):
        queryset = (
            cls.employee_queryset(context)
            .select_related(*cls.RELATED)
            .filter(
                employment__join_date__gte=start,
                employment__join_date__lte=end,
            )
        )

        return [
            cls._employee_row(
                employee,
                movement_type=MovementType.JOIN,
                movement_date=employee.employment.join_date,
                movement_from=EMPTY,
                movement_to=cls._placement_label(employee),
                reason=EMPTY,
            )
            for employee in queryset
        ]

    @classmethod
    def exit_rows(cls, context: dict, start: date, end: date):
        queryset = (
            cls.employee_queryset(context)
            .select_related(*cls.RELATED)
            .filter(
                employment__termination_date__gte=start,
                employment__termination_date__lte=end,
            )
        )

        rows = []

        for employee in queryset:
            employment = employee.employment

            reason = getattr(employment.termination_reason, "name", None)

            rows.append(
                cls._employee_row(
                    employee,
                    movement_type=MovementType.EXIT,
                    movement_date=employment.termination_date,
                    movement_from=cls._placement_label(employee),
                    movement_to=EMPTY,
                    reason=reason or EMPTY,
                )
            )

        return rows

    # ------------------------------------------------------------------
    # Transfer
    # ------------------------------------------------------------------

    @classmethod
    def _org_actions(cls):
        """
        Seluruh dokumen mutasi yang **sudah diterapkan**, tanpa batas
        tanggal.

        `status=APPLIED` dan bukan `APPROVED`: dokumen yang alurnya
        selesai tapi penerapannya gagal (`apply_error` terisi) belum
        mengubah data pegawainya sama sekali, jadi ia belum jadi
        pergerakan apa pun — dan memakainya untuk memutar mundur
        penempatan akan memindahkan orang yang sebenarnya tidak pernah
        pindah.

        Sisi baru di-`Coalesce` di sini, sekali: usulan yang
        dikosongkan berarti "tidak berubah", dan membacanya apa adanya
        akan menganggap mutasi yang cuma memindahkan department
        sebagai perpindahan ke perusahaan kosong.
        """
        return (
            EmployeeAction.objects
            .filter(
                is_deleted=False,
                status=EmployeeActionStatus.APPLIED,
                action_type__in=ORGANIZATION_ACTION_TYPES,
            )
            .annotate(
                to_company=Coalesce("proposed_company_id", "company_id"),
                to_branch=Coalesce("proposed_branch_id", "branch_id"),
                to_location=Coalesce("proposed_location_id", "location_id"),
            )
        )

    @classmethod
    def action_queryset(cls, start: date, end: date):
        """
        Dokumen mutasi yang diterapkan **pada periode ini**.

        `effective_date` yang dipakai, bukan `applied_at`: mutasi yang
        disetujui 20 Agustus untuk berlaku 1 September adalah
        pergerakan bulan September, dan laporan Agustus yang
        memuatnya akan berselisih dengan Closing-nya sendiri.
        """
        return cls._org_actions().filter(
            effective_date__gte=start,
            effective_date__lte=end,
        )

    @classmethod
    def transfer_rows(cls, context: dict, start: date, end: date):
        """
        Mutasi, dinilai dari **sisi mana batas populasi dilewati**.

        Sebuah dokumen jadi Transfer In kalau ujung barunya berada di
        dalam populasi yang dilaporkan sementara ujung lamanya di luar,
        dan Transfer Out untuk kebalikannya. Yang kedua ujungnya di
        dalam adalah Internal Move — tetap diterbitkan sebagai baris,
        tapi tidak mengubah satu pun suku identitas. Yang kedua
        ujungnya di luar tidak diterbitkan sama sekali; itu pergerakan
        milik laporan orang lain.

        Ditentukan begini, bukan dari `action_type`: yang membedakan
        Transfer dari Promotion adalah alasan dan meja yang
        menyetujuinya, bukan kolom yang ditulis — `EmployeeAction`
        sendiri memakai satu handler untuk keempatnya. Promosi yang
        memindahkan orang ke perusahaan lain **adalah** Transfer Out
        bagi perusahaan yang ditinggalkan, apa pun nama dokumennya.
        """
        user = context.get("user")

        base = cls.action_queryset(start, end)

        inside_from = cls._inside_ids(context, base, ACTION_SCOPE_FROM, 0, user)
        inside_to = cls._inside_ids(context, base, ACTION_SCOPE_TO, 1, user)

        relevant = inside_from | inside_to

        if not relevant:
            return []

        documents = (
            base.filter(pk__in=relevant)
            .select_related(
                "employee",
                "employee__organization__company",
                "employee__organization__location",
                "employee__organization__department",
                "employee__organization__position",
                "company",
                "location",
                "proposed_company",
                "proposed_location",
                "proposed_department",
                "proposed_position",
            )
        )

        rows = []

        for action in documents:
            was_inside = action.pk in inside_from
            now_inside = action.pk in inside_to

            if was_inside and now_inside:
                movement_type = MovementType.INTERNAL_MOVE
            elif now_inside:
                movement_type = MovementType.TRANSFER_IN
            else:
                movement_type = MovementType.TRANSFER_OUT

            rows.append(
                cls._employee_row(
                    action.employee,
                    movement_type=movement_type,
                    movement_date=action.effective_date,
                    movement_from=cls._action_side(
                        action.company,
                        action.location,
                    ),
                    movement_to=cls._action_side(
                        action.proposed_company or action.company,
                        action.proposed_location or action.location,
                    ),
                    document_number=action.document_number or EMPTY,
                    reason=action.reason or EMPTY,
                )
            )

        return rows

    @classmethod
    def _inside_ids(
        cls,
        context: dict,
        queryset,
        scope_map: dict,
        side: int,
        user,
    ) -> set[int]:
        """
        Id dokumen yang **salah satu ujungnya** berada di dalam
        populasi — cakupan organisasi ∩ filter company/branch/location.

        `side` memilih ujung mana yang dinilai: 0 untuk kolom
        denormalisasi (penempatan lama), 1 untuk anotasi `Coalesce`
        (penempatan baru).
        """
        paths_for_side = {
            key: paths[side]
            for key, paths in ACTION_FILTER_PATHS.items()
        }

        for key, path in {
            **paths_for_side,
            **ACTION_FALLBACK_FILTER_PATHS,
        }.items():
            value = context.get(key)

            if not value:
                continue

            if isinstance(value, (list, tuple, set)):
                queryset = queryset.filter(**{f"{path}__in": list(value)})
            else:
                queryset = queryset.filter(**{path: value})

        # Izinnya **`hr.view_employee`**, sama dengan populasi laporan
        # ini — bukan `hr.view_employeeaction` milik barisnya sendiri.
        #
        # Ini pernah salah, dan salahnya diam. Opening dan Closing
        # dihitung dari `Employee`; barisnya dari `EmployeeAction`.
        # Begitu keduanya menuntut izin yang **berbeda**, pemegang satu
        # izin saja mendapat laporan yang identitasnya tidak tertutup —
        # Opening + Join + In − Out − Exit tidak lagi sama dengan
        # Closing, dan yang terlihat di layar cuma angka yang ganjil
        # tanpa satu pun pesan. `test_identitas_tertutup_untuk_akun_
        # bercakupan` yang menangkapnya.
        #
        # Satu laporan, satu kemampuan bisnis, satu izin. Barisnya di
        # sini bukan resource tersendiri melainkan turunan dari populasi
        # yang sudah dijaga di `population_queryset()`.
        scoped = DataScopeService.filter(
            queryset,
            scope_map,
            user,
            required_permission=view_permission_for(Employee),
        )

        return set(scoped.values_list("pk", flat=True))

    # ------------------------------------------------------------------
    # Perakitan
    # ------------------------------------------------------------------

    @classmethod
    def report(cls, context: dict) -> ManpowerMovementReport:
        """
        Dihitung **sekali per request** dan disimpan di context — KPI,
        dua chart, dan tabelnya membaca hasil yang sama persis.
        """
        cached = context.get(CONTEXT_KEY)

        if cached is not None:
            return cached

        start, end = cls.bounds(context)

        rows = [
            *cls.join_rows(context, start, end),
            *cls.transfer_rows(context, start, end),
            *cls.exit_rows(context, start, end),
        ]

        rows.sort(key=lambda row: row.sort_key)

        exit_reasons = Counter(
            row.reason or NO_REASON_LABEL
            for row in rows
            if row.movement_type == MovementType.EXIT
        )

        result = ManpowerMovementReport(
            opening=cls.headcount_at(context, start),
            # Penutup dibaca pada detik awal **hari sesudah** periode
            # berakhir. Kalau dibaca pada `end`, orang yang hari
            # terakhir bekerjanya tepat di akhir periode terhitung dua
            # kali — sebagai Exit **dan** sebagai bagian Closing — dan
            # yang bergabung di hari terakhir justru tidak terhitung
            # sama sekali.
            closing=cls.headcount_at(context, end + timedelta(days=1)),
            rows=rows,
            missing_join_date=cls.employee_queryset(context)
            .filter(employment__join_date__isnull=True)
            .count(),
            exit_reasons=exit_reasons,
        )

        context[CONTEXT_KEY] = result

        return result

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    @classmethod
    def _employee_row(
        cls,
        employee,
        *,
        movement_type: str,
        movement_date: date,
        movement_from: str,
        movement_to: str,
        document_number: str = EMPTY,
        reason: str = EMPTY,
    ) -> MovementRow:
        organization = getattr(employee, "organization", None)

        return MovementRow(
            employee_id=employee.pk,
            employee_number=employee.employee_number or EMPTY,
            employee_name=employee.full_name,
            movement_type=movement_type,
            movement_date=movement_date,
            company=cls._name(organization, "company"),
            location=cls._name(organization, "location"),
            department=cls._name(organization, "department"),
            position=cls._name(organization, "position"),
            movement_from=movement_from,
            movement_to=movement_to,
            document_number=document_number,
            reason=reason,
        )

    @staticmethod
    def _name(source, field_name: str) -> str:
        """
        Kolom yang memang belum diisi harus **berbunyi** sebagai belum
        diisi. Sel kosong di tengah tabel terbaca seperti kolomnya
        gagal dimuat.
        """
        value = getattr(source, field_name, None) if source else None

        return getattr(value, "name", None) or UNASSIGNED_LABEL

    @classmethod
    def _placement_label(cls, employee) -> str:
        organization = getattr(employee, "organization", None)

        return cls._side_label(
            getattr(organization, "company", None),
            getattr(organization, "location", None),
        )

    @classmethod
    def _action_side(cls, company, location) -> str:
        return cls._side_label(company, location)

    @staticmethod
    def _side_label(company, location) -> str:
        """
        `Company — Location`, dan yang kosong dilewati alih-alih
        menyisakan tanda pisah menggantung.
        """
        parts = [
            getattr(company, "name", None),
            getattr(location, "name", None),
        ]

        parts = [part for part in parts if part]

        return " — ".join(parts) if parts else UNASSIGNED_LABEL


# ----------------------------------------------------------------------
# Presenter
# ----------------------------------------------------------------------


class ManpowerMovementPresenter:
    """
    Perapi bentuk respons. Tidak ada agregasi baru di sini — semuanya
    pembacaan ulang dari `ManpowerMovementReport` yang sudah jadi.
    """

    service = ManpowerMovementService

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    @classmethod
    def opening_headcount(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).opening}

    @classmethod
    def joins(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).joins}

    @classmethod
    def transfers_in(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).transfers_in}

    @classmethod
    def transfers_out(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).transfers_out}

    @classmethod
    def exits(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).exits}

    @classmethod
    def closing_headcount(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).closing}

    @classmethod
    def net_change(cls, context: dict) -> dict:
        return {"value": cls.service.report(context).net_change}

    @classmethod
    def missing_join_date(cls, context: dict) -> dict:
        """
        Pegawai yang tidak bisa dilaporkan sama sekali.

        Kartunya ada supaya populasi laporan ini bisa direkonsiliasi
        dengan Manpower Summary: tanpa angka ini, selisih antara dua
        layar terbaca seperti salah satunya salah hitung.
        """
        return {"value": cls.service.report(context).missing_join_date}

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @classmethod
    def headcount_bridge(cls, context: dict) -> dict:
        series = cls.service.report(context).bridge()

        return {
            "categories": [label for label, _ in series],
            "datasets": [
                {
                    "label": "Headcount",
                    "data": [value for _, value in series],
                    "color": "primary",
                },
            ],
        }

    @classmethod
    def exit_by_reason(cls, context: dict) -> dict:
        """
        Alasan keluar, terbanyak dulu; ekornya dijumlahkan ke satu
        potongan "Lainnya" supaya totalnya tetap sama dengan KPI Exit.
        """
        ordered = cls.service.report(context).by_exit_reason()

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
                    "label": "Exit",
                    "data": data,
                    "color": "danger",
                },
            ],
        }

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    @classmethod
    def movement_table(cls, context: dict, *, page=None) -> dict:
        """
        Satu baris per peristiwa, kronologis.

        `total` selalu seluruh baris yang lolos filter laporan,
        `matched` yang lolos kotak cari. `totals` merekap per jenis,
        jadi baris Total tidak bergeser saat halaman diganti maupun
        saat ada yang diketik di kotak cari.
        """
        report = cls.service.report(context)

        rows = report.rows
        totals = report.type_totals()

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
    def table_row(row: MovementRow) -> dict:
        return {
            "id": f"{row.movement_type}-{row.employee_id}-{row.movement_date}",
            "employee_number": row.employee_number,
            "employee_name": row.employee_name,
            "movement_type": row.type_label,
            "movement_date": row.movement_date.isoformat(),
            "company": row.company,
            "location": row.location,
            "department": row.department,
            "position": row.position,
            "movement_from": row.movement_from,
            "movement_to": row.movement_to,
            "document_number": row.document_number,
            "reason": row.reason,
        }
