"""
Employee Reporting Audit — laporan master organisasi, READ ONLY.

Bedanya dengan HR Period Summary bukan cuma tidak adanya periode.
Yang dilaporkan di sini adalah **isi master**: penempatan organisasi,
garis pelaporan, dan akun login yang menempel padanya. Tidak ada satu
pun transaksi yang dibaca, jadi tidak ada satu pun angka yang bisa
berubah karena bulan yang dipilih.

Sumber tiap kolom, dan tidak ada yang ditebak:

* penempatan (company … section, position) → `OrganizationAssignment`
* Report To → `OrganizationAssignment.reports_to`, **hubungan yang
  benar-benar tersimpan**. Bukan diturunkan dari Employee Group, nama
  jabatan, role, atau "manager department-nya siapa" — empat tebakan
  yang semuanya menghasilkan atasan yang terlihat masuk akal dan tidak
  pernah dipilih siapa pun
* Employee Group / Employment Type / Join Date → `EmploymentAssignment`
* akun dan emailnya → `Employee.user` (`User.username`, `User.email`)
* akun atasan → `reports_to.user`, akun **milik orang yang menjadi
  reports_to**, bukan akun lain yang kebetulan sejabatan

**Feature Applicability tidak menyaring laporan ini**, dan itu justru
inti kegunaannya. Populasinya = cakupan organisasi + filter yang
dipilih. Direksi yang seluruh proses HR-nya dimatikan tetap terbit
sebagai baris: yang diaudit di sini adalah struktur pegawainya, bukan
kepesertaannya di Attendance/Leave/Roster. Menyaringnya berarti
lubang di garis pelaporan justru paling mungkin tersembunyi tepat di
puncak struktur — lihat `docs/claude/reports.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from django.utils import timezone

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.hr.models import Employee

from .statuses import (
    HAS_REPORT_TO,
    NO_REPORT_TO,
    AccountStatus,
    ReportingStatus,
    reporting_status_code,
)


UNASSIGNED_LABEL = "Belum Ditentukan"

# Sel yang memang kosong dikirim sebagai string kosong, bukan sebagai
# tanda pisah yang dirakit backend. `formatDashboardValue` di frontend
# sudah merender nilai kosong sebagai "—" untuk **seluruh** tabel
# dashboard; menuliskan "-" sendiri di sini menghasilkan dua lambang
# kosong yang berbeda di satu layar.
EMPTY = ""


# Cakupan data per baris. Sama persis dengan `EMPLOYEE_SCOPE` di HR
# Period Summary dan `EmployeeViewSet.data_scope` — kalau yang di sana
# berubah, yang di sini ikut.
#
# Ini satu-satunya penjagaan baris di laporan ini, dan tidak ada
# aturan keamanan baru yang ditulis di berkas ini: filter dropdown
# hanya boleh **mempersempit** apa yang sudah lolos dari sini.
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
# HR Period Summary supaya satu tombol Location tidak berperilaku
# berbeda di dua laporan.
FILTER_PATHS = {
    "company": "organization__company_id",
    "branch": "organization__branch_id",
    "location": "organization__location_id",
    "department": "organization__department_id",
    "section": "organization__section_id",
    "employee_group": "employment__employee_group_id",
    "employment_type": "employment__employment_type_id",
    "employee": "id",
}


CONTEXT_KEY = "_hr_employee_reporting_audit"


def tenure_label(join_date: date | None, today: date) -> str:
    """
    Masa kerja, **dihitung saat respons dirakit**.

    Sengaja bukan kolom di database: masa kerja bertambah sendiri tiap
    hari, dan angka yang disimpan mulai salah pada hari pertama setelah
    ditulis — tanpa satu pun proses yang berbunyi.

    Tanggal masuk yang belum tiba (pegawai baru yang sudah didata)
    mengembalikan kosong, bukan "0 th 0 bl": nol bulan kerja untuk
    orang yang belum masuk adalah jawaban yang salah, bukan jawaban
    yang kecil.
    """
    if not join_date or join_date > today:
        return EMPTY

    elapsed = relativedelta(today, join_date)

    return f"{elapsed.years} th {elapsed.months} bl"


@dataclass(frozen=True)
class AuditRow:
    """Satu pegawai, sudah rata — tidak ada relasi yang tersisa."""

    employee_id: int
    employee_number: str
    employee_name: str

    company: str
    location: str
    department: str
    section: str
    position: str

    employee_group: str
    employment_type: str
    join_date: date | None
    tenure: str

    report_to_number: str
    report_to_name: str

    account: str
    account_email: str
    report_account: str
    report_account_email: str

    account_status: str
    reporting_status: str

    @property
    def search_text(self) -> str:
        """
        Yang dicocokkan kotak cari.

        Enam identitas, bukan seluruh baris: mengetik "PERM" di kotak
        yang mencocokkan semua kolom akan menyisakan hampir seluruh
        tabel, dan hasilnya terbaca seperti pencarian yang rusak.
        Email ikut karena justru itu yang dipegang orang saat menelusuri
        akun ("siapa pemilik brya.seran+gm@…") — dan datanya sudah ada
        di baris ini, jadi tidak ada query tambahan.
        """
        return " ".join(
            [
                self.employee_number,
                self.employee_name,
                self.account,
                self.account_email,
                self.report_to_number,
                self.report_to_name,
                self.report_account,
                self.report_account_email,
            ]
        )


class EmployeeReportingAuditService:
    """
    Perakit baris audit. Tidak punya satu pun jalan menulis.
    """

    @classmethod
    def employee_queryset(cls, context: dict):
        """
        Populasi laporan: **cakupan organisasi ∩ filter yang dipilih**.

        Tiga hal yang sengaja tidak ikut menyaring:

        * **Feature Applicability.** Ini audit struktur, bukan laporan
          proses. Lihat docstring modul.
        * **Periode.** Master tidak punya periode; laporan yang
          menyodorkan pemilih bulan untuk data yang tidak berubah per
          bulan mengundang pembacanya menyimpulkan sebaliknya.
        * **Punya akun atau tidak.** Pegawai tanpa akun justru salah
          satu temuan yang dicari laporan ini.

        Yang ikut menyaring: `is_deleted=False` (soft delete) dan
        `is_active=True`. Yang kedua mengikuti konsep
        `audit_employee_reporting` — garis pelaporan orang yang sudah
        keluar bukan lagi temuan, dan membiarkannya membuat kolom
        Reporting Status penuh temuan yang tidak ada gunanya
        ditindaklanjuti.
        """
        queryset = (
            Employee.objects
            .filter(is_deleted=False, is_active=True)
            # Seluruh kolom laporan ini diambil dari sini. Tanpa
            # `select_related`, satu halaman berisi 25 baris menembak
            # ratusan query — dan yang paling mahal justru akun atasan
            # (`organization__reports_to__user`), dua lompatan relasi
            # yang tidak akan pernah di-prefetch sendiri oleh Django.
            .select_related(
                "user",
                "organization__company",
                "organization__branch",
                "organization__location",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__reports_to",
                "organization__reports_to__user",
                "employment__employee_group",
                "employment__employment_type",
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

        queryset = cls._filter_reporting_status(queryset, context)

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
            "organization__company__code",
            "organization__location__code",
            "employee_number",
            "id",
        ).distinct()

    @staticmethod
    def _filter_reporting_status(queryset, context: dict):
        """
        `?reporting_status=1|2`, dan cuma itu yang bisa dimintanya.

        Pegawai yang belum punya baris `OrganizationAssignment` sama
        sekali ikut ke "No Report To" — join-nya `LEFT OUTER`, dan
        memang itu jawaban yang benar: yang ditanya kolom ini bukan
        "apakah barisnya ada", melainkan "apakah atasannya tercatat".
        """
        code = reporting_status_code(context.get("reporting_status"))

        if code == HAS_REPORT_TO:
            return queryset.filter(organization__reports_to__isnull=False)

        if code == NO_REPORT_TO:
            return queryset.filter(organization__reports_to__isnull=True)

        return queryset

    # ------------------------------------------------------------------
    # Perakitan
    # ------------------------------------------------------------------

    @classmethod
    def rows(cls, context: dict) -> list[AuditRow]:
        """
        Hasil yang dipakai bersama tabel dan penghitung barisnya,
        dihitung **sekali per request** dan disimpan di context.
        """
        cached = context.get(CONTEXT_KEY)

        if cached is not None:
            return cached

        today = timezone.localdate()

        result = [
            cls.build_row(employee, today=today)
            for employee in cls.employee_queryset(context)
        ]

        context[CONTEXT_KEY] = result

        return result

    @classmethod
    def build_row(cls, employee: Employee, *, today: date) -> AuditRow:
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        report_to = getattr(organization, "reports_to", None)

        join_date = getattr(employment, "join_date", None)

        account = getattr(employee, "user", None)
        report_account = getattr(report_to, "user", None)

        return AuditRow(
            employee_id=employee.id,
            employee_number=employee.employee_number or EMPTY,
            employee_name=employee.full_name,

            company=cls._label(organization, "company"),
            location=cls._label(organization, "location"),
            department=cls._label(organization, "department"),
            section=cls._label(organization, "section"),
            position=cls._label(organization, "position"),

            employee_group=cls._label(employment, "employee_group"),
            employment_type=cls._label(employment, "employment_type"),
            join_date=join_date,
            tenure=tenure_label(join_date, today),

            report_to_number=(
                (report_to.employee_number or EMPTY) if report_to else EMPTY
            ),
            report_to_name=report_to.full_name if report_to else EMPTY,

            account=getattr(account, "username", EMPTY) or EMPTY,
            account_email=getattr(account, "email", EMPTY) or EMPTY,
            report_account=(
                getattr(report_account, "username", EMPTY) or EMPTY
            ),
            report_account_email=(
                getattr(report_account, "email", EMPTY) or EMPTY
            ),

            account_status=cls.account_status(account),
            reporting_status=(
                ReportingStatus.HAS if report_to else ReportingStatus.NONE
            ),
        )

    @staticmethod
    def account_status(account) -> str:
        """
        Dibacakan dari `User`, tidak disimpulkan.

        Tiga keadaan yang berbeda dan sering tertukar: **tidak punya
        akun** (belum pernah dibuatkan) berbeda dari **akun yang
        dimatikan** (pernah ada, lalu dicabut). Menggabungkannya jadi
        satu "tidak aktif" menghapus persis perbedaan yang dicari
        pengaudit — yang pertama tugas HR, yang kedua sudah selesai
        ditangani.
        """
        if account is None:
            return AccountStatus.NO_ACCOUNT

        if not account.is_active:
            return AccountStatus.INACTIVE

        return AccountStatus.CONNECTED

    @staticmethod
    def _label(owner, relation: str) -> str:
        if owner is None:
            return UNASSIGNED_LABEL

        value = getattr(owner, relation, None)

        return getattr(value, "name", None) or UNASSIGNED_LABEL


class EmployeeReportingAuditPresenter:
    """
    Perapi bentuk respons. Satu widget, jadi satu method.
    """

    service = EmployeeReportingAuditService

    @classmethod
    def employee_table(cls, context: dict, *, page=None) -> dict:
        """
        Satu baris per pegawai, dipotong per halaman.

        `total` selalu seluruh baris yang lolos filter laporan,
        `matched` yang lolos kotak cari — dua angka yang berbeda arti
        dan keduanya dipakai frontend: yang pertama memberi tahu bahwa
        laporan mencakup lebih banyak orang daripada yang sedang
        terlihat, yang kedua menghitung jumlah halaman.

        Tidak ada baris Total di sini, dan itu disengaja: seluruh
        kolomnya identitas, dan menjumlahkan nomor pegawai menghasilkan
        angka yang tidak salah hitung, cuma tidak berarti apa pun.
        """
        rows = cls.service.rows(context)

        if page is None:
            return {
                "items": [cls.table_row(row) for row in rows],
                "total": len(rows),
            }

        matched = page.matching(rows, text=lambda row: row.search_text)

        return page.envelope(
            items=[cls.table_row(row) for row in page.slice(matched)],
            matched=len(matched),
            total=len(rows),
        )

    @staticmethod
    def table_row(row: AuditRow) -> dict:
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
            "join_date": row.join_date.isoformat() if row.join_date else EMPTY,
            "tenure": row.tenure,
            "report_to_number": row.report_to_number,
            "report_to_name": row.report_to_name,
            "account": row.account,
            "account_email": row.account_email,
            "report_account": row.report_account,
            "report_account_email": row.report_account_email,
            "account_status": row.account_status,
            "reporting_status": row.reporting_status,
        }
