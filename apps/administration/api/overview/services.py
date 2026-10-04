"""
Angka dashboard modul Administration.

Sebelum ini seluruh isinya `data.ts` di repo Nuxt: "Companies 5",
"Users 286", "Master Records 1,245", grafik berjudul "Dummy monthly
growth", dan "Today · 08 Jul 2026" yang ditulis mati di template. Angka
yang sama persis untuk setiap orang yang login, di tenant mana pun,
termasuk saat didemokan ke klien. Ini yang menggantikannya.

Aturannya sama dengan dashboard HR: **widget yang datanya belum ada
modelnya tidak dibuat, bukan diisi angka contoh.** Karena itu "Master
Records Growth" hilang — tidak ada satu pun model yang mencatat
pertumbuhan master per bulan, dan menghitungnya dari `created_at` master
yang diseed sekaligus hanya akan menghasilkan satu batang raksasa di
bulan tenant dibuat.

Penggantinya aktivitas dari `AuditTrail`, yang sejak jejak audit punya
penulis memang berisi. Sebelum itu tabelnya nol baris, dan chart
aktivitas yang selalu kosong memang tidak layak dibuat.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from apps.accounts.permissions import view_permission_for
from apps.accounts.models import Menu, Role
from apps.accounts.scoping import DataScopeService
from apps.administration.models import (
    AuditTrail,
    Branch,
    Company,
    Currency,
    Department,
    Division,
    Holiday,
    Location,
    NumberingSequence,
    Position,
    Section,
    WorkCalendar,
)
from apps.administration.services.calendar_resolver import (
    scope_holidays_for_user,
)
from apps.framework.periods import trend_buckets
from apps.workflow.models import WorkflowDefinition


User = get_user_model()


UNASSIGNED_LABEL = "Tidak Diketahui"
OTHER_LABEL = "Lainnya"

MAX_CHART_SEGMENTS = 6

# Hari libur yang dianggap "mendekat". Cukup panjang untuk memuat libur
# nasional berikutnya di bulan mana pun, cukup pendek supaya daftarnya
# tidak jadi kalender setahun penuh.
HOLIDAY_HORIZON_DAYS = 90


# ----------------------------------------------------------------------
# Cakupan data per baris
# ----------------------------------------------------------------------
#
# Dashboard adalah `APIView` biasa — `filter_queryset()` milik
# `BaseMasterViewSet` tidak pernah dilewati, jadi cakupan data
# tidak ikut sendiri. Tanpa peta di bawah, admin site yang layar
# Locations-nya cuma berisi satu baris tetap membaca "Site 13" di
# beranda modulnya.
#
# Petanya disamakan dengan `data_scope` viewset organisasi masing-masing.

# Company dan Branch ikut membawa **jalur balik** ke tingkat di
# bawahnya, dan itu bukan hiasan: penugasan bermode "ikut penempatan
# pemegang" sedalam Location (`KTT`, `ADMIN-SECTION`, atau `EXECUTIVE`
# yang dipegang GM site) hanya menyebut
# `location` di cakupannya, dan jenis yang tidak ada di peta
# **dilewati** — jadi tanpa jalur balik, GM site yang dropdown
# Company-nya cuma berisi satu perusahaan tetap membaca "Company 3" di
# kartu KPI beranda. Angka yang tidak cocok dengan isi dropdown di
# layar yang sama adalah selisih yang tidak berbunyi.
#
# `distinct()` dipasang pemanggilnya (`_scoped`) untuk peta yang
# menyeberang relasi — jalur balik menggandakan baris induk.

COMPANY_SCOPE = {
    "company": "id",
    "branch": "branches__id",
    "location": "locations__id",
    "division": "divisions__id",
    "department": "departments__id",
    "section": "sections__id",
}

BRANCH_SCOPE = {
    "company": "company",
    "branch": "id",
    "location": "locations__id",
    "division": "divisions__id",
    "department": "departments__id",
    "section": "sections__id",
}

LOCATION_SCOPE = {"company": "company", "branch": "branch", "location": "id"}

# Division / Department / Section / Position. Dipakai dengan
# `allow_null=True`, dan itu bukan pelonggaran asal: hanya Company yang
# wajib di struktur ini, jadi department yang `location`-nya kosong
# berarti **berlaku lintas site**, bukan "belum diisi". Tanpa itu, admin
# yang dicakup ke satu lokasi membaca "Department 0" di batang chart —
# padahal departmentnya sendiri ada, cuma tidak menempel ke site mana
# pun. Nol yang salah lebih menyesatkan daripada angka yang longgar.
ORGANIZATION_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
}

# `AuditTrail.company` sering kosong, dan bukan karena datanya belum
# diisi: perubahan pada Role, Currency, dan seluruh master referensi
# memang tidak menempel ke perusahaan mana pun. Menyaringnya dengan
# aturan biasa membuat baris-baris itu tak terlihat siapa pun kecuali
# superuser — jejak audit yang paling sering dicari justru menghilang.
# Karena itu `allow_null=True`: yang kosong lolos, yang menyebut
# perusahaan lain tetap tertutup.
AUDIT_SCOPE = {"company": "company", "location": "location"}

# Dipakai health check saja sekarang; daftar Upcoming Holidays
# memakai `scope_holidays_for_user()`.
HOLIDAY_SCOPE = {"company": "company", "location": "location"}


def trend(current, previous, *, period: str = "dari periode sebelumnya"):
    """
    Perubahan relatif terhadap periode sebelumnya.

    None kalau pembandingnya nol — "naik 100%" untuk data yang baru mulai
    terisi lebih menyesatkan daripada tidak menampilkan apa-apa, dan
    frontend memang menyembunyikan bagian tren saat nilainya null.
    """
    if previous in (None, 0) or current is None:
        return None

    change = ((float(current) - float(previous)) / abs(float(previous))) * 100

    return {
        "value": round(abs(change), 2),
        "direction": "up" if change >= 0 else "down",
        "period": period,
    }


class AdministrationDashboardService:
    """
    Seluruh angka dihitung dari data — tidak ada nilai yang di-hardcode.
    """

    # ------------------------------------------------------------------
    # Periode
    # ------------------------------------------------------------------

    @staticmethod
    def bounds(context: dict) -> tuple[date, date]:
        period = context["period"]

        return period["start"], period["end"]

    @staticmethod
    def previous_bounds(context: dict) -> tuple[date, date]:
        previous = context["period"]["previous"]

        return previous["start"], previous["end"]

    @staticmethod
    def compare_label(context: dict) -> str:
        return context["period"].get(
            "compare_label",
            "dari periode sebelumnya",
        )

    # ------------------------------------------------------------------
    # Queryset dasar
    # ------------------------------------------------------------------

    @staticmethod
    def _company_id(context: dict) -> list:
        """
        Company yang dipilih di toolbar, selalu sebagai daftar.

        Filternya **bercentang banyak** sejak Organization Scope: GM
        yang memegang tiga company membaca ketiganya sekaligus. Nilai
        tunggal tetap diterima — sesi lama dan pemanggil skrip yang
        mengirim `?company=1` tidak boleh ikut rusak.
        """
        value = context.get("company")

        if value in (None, ""):
            return []

        if isinstance(value, (list, tuple, set)):
            return [item for item in value if item not in (None, "")]

        return [value]

    @classmethod
    def _scoped(cls, queryset, mapping: dict, context: dict, *,
                company_path: str = "company_id", allow_null=None):
        """
        Dua penyaringan bertumpuk, dan keduanya perlu: filter Company
        yang **dipilih** pengguna di toolbar, lalu cakupan data yang
        **tidak bisa** ia lepas.
        """
        companies = cls._company_id(context)

        if companies and company_path:
            queryset = queryset.filter(**{f"{company_path}__in": companies})

        scoped = DataScopeService.filter(
            queryset,
            mapping,
            context.get("user"),
            allow_null=allow_null,
            required_permission=view_permission_for(queryset.model),
        )

        # Peta yang menyeberang relasi (`locations__id`) menggandakan
        # baris induknya, dan widget di sini menghitung `count()` —
        # tanpa `distinct()` satu perusahaan berlokasi lima terhitung
        # lima perusahaan.
        if any("__" in path for path in mapping.values()):
            scoped = scoped.distinct()

        return scoped

    @classmethod
    def companies(cls, context: dict):
        return cls._scoped(
            Company.objects.filter(is_deleted=False),
            COMPANY_SCOPE,
            context,
            company_path="id",
        )

    @classmethod
    def branches(cls, context: dict):
        return cls._scoped(
            Branch.objects.filter(is_deleted=False),
            BRANCH_SCOPE,
            context,
        )

    @classmethod
    def locations(cls, context: dict):
        return cls._scoped(
            Location.objects.filter(is_deleted=False),
            LOCATION_SCOPE,
            context,
        )

    @classmethod
    def audit_rows(cls, context: dict):
        return cls._scoped(
            AuditTrail.objects.all(),
            AUDIT_SCOPE,
            context,
            allow_null=True,
        )

    # ------------------------------------------------------------------
    # Kartu KPI
    # ------------------------------------------------------------------
    #
    # Jumlah perusahaan, cabang, dan lokasi sengaja **tanpa tren**:
    # struktur organisasi tidak berubah tiap bulan, dan "naik 0%" di
    # bawah setiap kartu cuma derau. Yang bertren cuma aktivitas.

    @classmethod
    def total_companies(cls, context: dict) -> dict:
        return {"value": cls.companies(context).count()}

    @classmethod
    def total_branches(cls, context: dict) -> dict:
        return {"value": cls.branches(context).count()}

    @classmethod
    def total_locations(cls, context: dict) -> dict:
        return {"value": cls.locations(context).count()}

    @classmethod
    def active_users(cls, context: dict) -> dict:
        """
        Akun yang bisa login.

        `User` tidak menyimpan company/branch/location, jadi tidak ada
        yang bisa dipetakan ke cakupan data — angkanya se-tenant
        untuk siapa pun yang bisa membuka layar ini. Itu batas yang
        disadari, bukan kelalaian: menyaringnya lewat penempatan pegawai
        akan membuang akun yang memang tidak punya baris Employee
        (integrasi, service account, admin IT).
        """
        return {"value": User.objects.filter(is_active=True).count()}

    @classmethod
    def audit_events(cls, context: dict) -> dict:
        start, end = cls.bounds(context)
        prev_start, prev_end = cls.previous_bounds(context)

        rows = cls.audit_rows(context)

        current = rows.filter(
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).count()

        previous = rows.filter(
            created_at__date__gte=prev_start,
            created_at__date__lte=prev_end,
        ).count()

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    @classmethod
    def configuration_issues(cls, context: dict) -> dict:
        checks = cls.configuration_health(context)["items"]

        return {
            "value": sum(
                1
                for item in checks
                if item["state"] != "success"
            ),
        }

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @classmethod
    def activity_trend(cls, context: dict) -> dict:
        """
        Aktivitas tercatat per satuan periode.

        Satuannya mengikuti mode: harian saat user memilih satu hari,
        bulanan saat memilih bulan. Tanpa `trend_buckets`, memilih "hari
        ini" menghasilkan chart satu titik.
        """
        rows = cls.audit_rows(context)
        today = date.today()

        series = []

        for bucket in trend_buckets(context["period"]):
            # Bucket yang belum terjadi tidak dikirim sebagai nol —
            # garis yang jatuh ke nol terbaca seperti aktivitas berhenti,
            # padahal harinya memang belum tiba.
            if bucket["start"] > today:
                break

            series.append(
                {
                    "label": bucket["label"],
                    "value": rows.filter(
                        created_at__date__gte=bucket["start"],
                        created_at__date__lte=bucket["end"],
                    ).count(),
                }
            )

        return {"series": series}

    @classmethod
    def activity_by_module(cls, context: dict) -> dict:
        start, end = cls.bounds(context)

        counts = (
            cls.audit_rows(context)
            .filter(
                created_at__date__gte=start,
                created_at__date__lte=end,
            )
            .values("module")
            .annotate(total=Count("id"))
            .order_by("-total")
        )

        rows = [
            (item["module"] or UNASSIGNED_LABEL, item["total"])
            for item in counts
        ]

        return cls._distribution(rows)

    @classmethod
    def organization_structure(cls, context: dict) -> dict:
        """
        Tinggi batangnya jumlah baris master per level.

        Menggantikan "Master Records Growth" yang dulu memakai deret
        bulanan karangan. Ini bukan tren — ini bentuk organisasinya, dan
        justru itu yang dicari di dashboard Administration: level mana
        yang sudah terisi dan mana yang masih kosong.
        """
        levels = [
            ("Company", cls.companies(context)),
            ("Branch", cls.branches(context)),
            ("Location", cls.locations(context)),
            (
                "Division",
                cls._scoped(
                    Division.objects.filter(is_deleted=False),
                    ORGANIZATION_SCOPE,
                    context,
                    allow_null=True,
                ),
            ),
            (
                "Department",
                cls._scoped(
                    Department.objects.filter(is_deleted=False),
                    ORGANIZATION_SCOPE,
                    context,
                    allow_null=True,
                ),
            ),
            (
                "Section",
                cls._scoped(
                    Section.objects.filter(is_deleted=False),
                    ORGANIZATION_SCOPE,
                    context,
                    allow_null=True,
                ),
            ),
            (
                "Position",
                cls._scoped(
                    Position.objects.filter(is_deleted=False),
                    ORGANIZATION_SCOPE,
                    context,
                    allow_null=True,
                ),
            ),
        ]

        series = [
            {"label": label, "value": queryset.count()}
            for label, queryset in levels
        ]

        return {
            "series": series,
            "total": sum(item["value"] for item in series),
        }

    @classmethod
    def _distribution(cls, rows) -> dict:
        """Memotong ekor distribusi jadi "Lainnya"; totalnya tetap utuh."""
        total = sum(count for _, count in rows)

        segments = []
        tail = 0

        for index, (label, count) in enumerate(rows):
            if index < MAX_CHART_SEGMENTS:
                segments.append(
                    {
                        "label": label,
                        "value": count,
                        "percentage": (
                            round(count / total * 100, 1) if total else 0
                        ),
                    }
                )
            else:
                tail += count

        if tail:
            segments.append(
                {
                    "label": OTHER_LABEL,
                    "value": tail,
                    "percentage": (
                        round(tail / total * 100, 1) if total else 0
                    ),
                }
            )

        return {"series": segments, "total": total}

    # ------------------------------------------------------------------
    # Daftar
    # ------------------------------------------------------------------

    @classmethod
    def recent_audit(cls, context: dict, limit: int = 8) -> dict:
        rows = (
            cls.audit_rows(context)
            .select_related("user", "company")
            .order_by("-created_at", "-id")[:limit]
        )

        return {
            "items": [
                {
                    "id": row.id,
                    "time": row.created_at,
                    "module": row.module or UNASSIGNED_LABEL,
                    "action": row.action,
                    "object": row.object_repr or row.object_type,
                    "user": cls._actor_name(row.user),
                }
                for row in rows
            ],
        }

    @staticmethod
    def _actor_name(user) -> str:
        """
        Nama yang terbaca, bukan username.

        `demo.hrmanager` di kolom "Oleh" memaksa pembacanya menerjemahkan
        sendiri; nama lengkapnya sudah ada di akun yang sama.
        """
        if user is None:
            return UNASSIGNED_LABEL

        return (
            user.get_full_name()
            or user.username
            or UNASSIGNED_LABEL
        )

    @classmethod
    def upcoming_holidays(cls, context: dict, limit: int = 6) -> dict:
        """
        Sengaja **tidak** ikut filter periode: hari libur pekan depan
        tetap harus terlihat walau layarnya sedang menampilkan angka
        bulan lalu. Pola yang sama dengan Pengingat Kepegawaian di
        dashboard HR.

        **Dikelompokkan per (tanggal, nama), bukan per baris.**
        Pengelompokan ini lahir saat `Holiday` masih wajib menyebut
        company, sehingga satu libur nasional tersimpan dua belas kali
        di tenant berisi dua belas perusahaan. Cakupan GLOBAL sudah
        menghapus duplikasi itu di sumbernya, tapi pengelompokannya
        dipertahankan: tenant lama masih menyimpan baris per company
        sampai `collapse_calendar_duplicates` dijalankan, dan libur
        bercakupan COMPANY di beberapa perusahaan memang tetap beberapa
        baris.
        """
        today = date.today()
        horizon = today + timedelta(days=HOLIDAY_HORIZON_DAYS)

        # Cakupannya lewat `scope_holidays_for_user()` — aturan yang
        # sama dipakai layar Holiday dan sorotan dashboard HR. Filter
        # Company dari toolbar tetap ditumpuk di atasnya, tapi
        # **tidak** boleh membuang baris GLOBAL: memilih satu company
        # di toolbar tidak berarti libur nasional berhenti berlaku
        # untuknya.
        queryset = scope_holidays_for_user(
            Holiday.objects.filter(
                is_deleted=False,
                date__gte=today,
                date__lte=horizon,
            ),
            context.get("user"),
        )

        selected_companies = cls._company_id(context)

        if selected_companies:
            queryset = queryset.filter(
                Q(company_id__in=selected_companies)
                | Q(company_id__isnull=True),
            )

        rows = (
            queryset
            .values("date", "name", "is_national", "scope")
            .annotate(companies=Count("company_id", distinct=True))
            .order_by("date", "name")[:limit]
        )

        def describe(row) -> str:
            # Baris GLOBAL tidak menyebut company sama sekali, jadi
            # `Count("company_id")` menghasilkan **nol** — dan tanpa
            # cabang ini libur yang berlaku paling luas tampil sebagai
            # "0 perusahaan", persis kebalikan artinya.
            if row["scope"] == "GLOBAL":
                return "Nasional" if row["is_national"] else "Seluruh perusahaan"

            if row["is_national"]:
                return "Nasional"

            if row["scope"] == "SELECTED_COMPANIES":
                return "Beberapa perusahaan"

            return f"{row['companies']} perusahaan"

        return {
            "items": [
                {
                    "id": f"{row['date']}-{row['name']}",
                    "name": row["name"],
                    "date": row["date"],
                    "days_left": (row["date"] - today).days,
                    "scope": describe(row),
                }
                for row in rows
            ],
        }

    # ------------------------------------------------------------------
    # Kesehatan konfigurasi
    # ------------------------------------------------------------------
    #
    # Menggantikan daftar yang dulu ditulis mati di `data.ts` — enam
    # baris yang selalu berbunyi sama, termasuk "Email Notification: Not
    # configured" di tenant yang tidak punya modul notifikasi email sama
    # sekali. Sekarang tiap baris adalah pemeriksaan sungguhan, dan
    # `link` menunjuk layar tempat memperbaikinya: temuan tanpa jalan
    # keluar cuma memindahkan kebingungan.

    @classmethod
    def configuration_health(cls, context: dict) -> dict:
        today = date.today()

        checks = [
            cls._check(
                "Organization",
                ok=cls.companies(context).exists()
                and cls.locations(context).exists(),
                ok_text="Siap",
                fail_text="Belum lengkap",
                hint="Company dan Location wajib ada sebelum modul lain bisa dipakai.",
                link="/administration/organization/companies",
                critical=True,
            ),
            cls._check(
                "Numbering",
                ok=NumberingSequence.objects.filter(is_deleted=False).exists(),
                ok_text="Siap",
                fail_text="Belum diseed",
                # Kegagalannya diam: dokumen tetap tersimpan, nomornya
                # kosong. Baru ketahuan saat ada yang mencetaknya.
                hint="Tanpa deret nomor, dokumen tersimpan tanpa nomor.",
                link="/administration/numbering",
                critical=True,
            ),
            cls._check(
                "Currency",
                ok=Currency.objects.filter(
                    is_deleted=False,
                    is_base_currency=True,
                ).exists(),
                ok_text="Siap",
                fail_text="Belum ada mata uang dasar",
                hint="Payroll dan penempatan memakai mata uang dasar sebagai bawaan.",
                link="/administration/currency",
            ),
            cls._check(
                "Work Calendar",
                ok=WorkCalendar.objects.filter(is_deleted=False).exists(),
                ok_text="Siap",
                fail_text="Belum diseed",
                hint=(
                    "Perhitungan hari cuti jatuh ke Senin–Jumat "
                    "selama kalender kerja kosong."
                ),
                link="/administration/calendar",
                critical=True,
            ),
            cls._check(
                "Holiday",
                ok=Holiday.objects.filter(
                    is_deleted=False,
                    date__year=today.year,
                ).exists(),
                ok_text=f"Terisi {today.year}",
                fail_text=f"Kosong untuk {today.year}",
                hint="Hari libur nasional ikut memotong saldo cuti kalau tidak terdaftar.",
                link="/administration/calendar",
            ),
            cls._check(
                "Security Roles",
                ok=Role.objects.filter(is_deleted=False)
                .annotate(total=Count("permissions"))
                .filter(total__gt=0)
                .exists(),
                ok_text="Siap",
                fail_text="Belum ada izin",
                hint=(
                    "Role tanpa satu pun izin model membuat seluruh "
                    "sistem read-only kecuali superuser."
                ),
                link="/administration/security/roles",
                critical=True,
            ),
            cls._check(
                "Menu Access",
                ok=Menu.objects.filter(is_deleted=False).exists(),
                ok_text="Siap",
                fail_text="Belum diseed",
                hint=(
                    "Selama tabel menu kosong, pembatasan menu per role "
                    "tidak bisa diatur sama sekali."
                ),
                link="/administration/security/menu-permissions",
            ),
            cls._check(
                "Workflow Approval",
                ok=WorkflowDefinition.objects.filter(
                    is_deleted=False,
                    is_active=True,
                ).exists(),
                ok_text="Siap",
                fail_text="Belum ada alur aktif",
                hint="Pengajuan cuti dan travel request gagal tanpa alur aktif.",
                link="/workflow/definitions",
            ),
        ]

        return {"items": checks}

    @staticmethod
    def _check(
        name: str,
        *,
        ok: bool,
        ok_text: str,
        fail_text: str,
        hint: str,
        link: str,
        critical: bool = False,
    ) -> dict:
        """
        `critical` memisahkan "sistem tidak bisa dipakai" dari "sebaiknya
        diisi". Satu warna untuk keduanya membuat yang benar-benar
        menghentikan pekerjaan tenggelam di antara saran.
        """
        return {
            "name": name,
            "status": ok_text if ok else fail_text,
            "state": (
                "success"
                if ok
                else ("danger" if critical else "warning")
            ),
            "hint": "" if ok else hint,
            "link": link,
        }
