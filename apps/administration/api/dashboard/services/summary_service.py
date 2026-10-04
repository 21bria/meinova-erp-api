"""
Angka halaman depan, dihitung dari data — bukan lagi `dashboardDummy`.

Sebelum ini seluruh isi beranda ditulis mati di frontend: "Total
Companies 4", "Active Employees 248" di tenant berisi 10 orang,
"Monthly Payroll Rp 1.2B" untuk modul payroll yang belum punya model
payroll run sama sekali. Angka yang sama untuk semua orang yang login,
termasuk saat didemokan ke klien.

Aturan yang dipakai sama dengan dashboard HR: **widget yang datanya
belum ada modelnya tidak dibuat, bukan diisi angka contoh.** Karena itu
"Revenue vs Expense" hilang — `finance` masih kerangka kosong dan tidak
ada satu baris pun yang bisa digambar.

Dua sumber angka yang perlu dibedakan, dan ini yang gampang tertukar:

* **Milik pengguna** — kotak masuk dan pengajuannya sendiri. Disaring
  berdasarkan keterlibatan (`apps.workflow.selectors`), tidak ikut
  cakupan organisasi: approver lintas lokasi memang harus melihat
  dokumen yang mendarat di mejanya.
* **Milik organisasi** — jumlah pegawai. Disaring cakupan data,
  sama persis dengan tabel Employee. Kalau tidak, admin Gebe membaca
  "10" di beranda dan "6" di tabelnya, dan selisih itu justru memberi
  tahu ada 4 baris yang disembunyikan darinya.
"""

from __future__ import annotations

from apps.accounts.permissions import view_permission_for
from apps.administration.api.dashboard.quick_actions import QUICK_ACTIONS
from apps.administration.models import Notification


# Berapa banyak yang ditarik untuk daftar di beranda. Beranda adalah
# ringkasan; yang mau melihat semuanya menekan tautannya.
# Kartu di beranda menggulir di dalam kotaknya sendiri, jadi jumlahnya
# tidak lagi dibatasi tinggi layar. Dinaikkan dari 5 karena 5 baris
# pertama saja membuat "Recent Documents" tidak bisa dipakai menjawab
# "dokumen saya kemarin sampai mana" — dan menggulir sudah tidak
# mengubah tata letak apa pun.
RECENT_LIMIT = 10


# Sejauh mana hari libur ditengok ke depan untuk sorotan di kepala
# beranda. Sepekan: lebih jauh dari itu bukan lagi "hari ini", dan
# daftar 90 harinya sudah ada di dashboard Administration.
HOLIDAY_LOOKAHEAD_DAYS = 7


class DashboardSummaryService:
    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    @staticmethod
    def employee_count(user) -> int:
        from apps.accounts.scoping import DataScopeService
        from apps.hr.api.dashboard.services import EMPLOYEE_SCOPE
        from apps.hr.models import Employee

        return DataScopeService.filter(
            Employee.objects.filter(is_active=True, is_deleted=False),
            EMPLOYEE_SCOPE,
            user,
            required_permission=view_permission_for(Employee),
        ).count()

    @classmethod
    def kpis(cls, user) -> list[dict]:
        from apps.workflow import selectors
        from apps.workflow.models import InstanceStatus

        workflow = selectors.summary_for(user)

        running = (
            selectors.visible_instances(user)
            .filter(status=InstanceStatus.PENDING)
            .count()
        )

        return [
            {
                "code": "waiting_for_me",
                "title": "Waiting for My Approval",
                "value": workflow["waiting_for_me"],
                "icon": "inbox",
                "color": "amber",
                "link": "/workflow/inbox",
            },
            {
                "code": "my_submissions",
                "title": "My Open Submissions",
                "value": workflow["my_open_submissions"],
                "icon": "send",
                "color": "sky",
                "link": "/workflow/submissions",
            },
            {
                "code": "running_documents",
                "title": "Running Documents",
                "value": running,
                "icon": "workflow",
                "color": "violet",
                "link": "/workflow",
            },
            {
                "code": "active_employees",
                "title": "Active Employees",
                "value": cls.employee_count(user),
                "icon": "users",
                "color": "emerald",
                "link": "/hr/employees",
            },
        ]

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @staticmethod
    def approval_status(user) -> dict:
        """
        Donut status dokumen yang **boleh dilihat pengguna ini**, bukan
        seluruh tenant. Angkanya ikut aturan `visible_instances`, jadi
        beranda tidak jadi celah baca untuk dokumen yang layar
        monitoringnya sendiri menyembunyikannya.
        """
        from django.db.models import Count

        from apps.workflow import selectors
        from apps.workflow.models import InstanceStatus

        labels = dict(InstanceStatus.choices)

        rows = (
            selectors.visible_instances(user)
            .values("status")
            # `distinct=True` wajib: `visible_instances` menyaring lewat
            # join ke `approvals`, jadi dokumen yang punya tiga kotak
            # tanda tangan muncul tiga kali. `.distinct()` di queryset
            # tidak menolong setelah `values().annotate()` — yang
            # dikelompokkan sudah barisnya, bukan dokumennya.
            .annotate(total=Count("id", distinct=True))
            .order_by("-total")
        )

        series = [
            {
                "label": labels.get(row["status"], row["status"]),
                "code": row["status"],
                "value": row["total"],
            }
            for row in rows
        ]

        return {
            "code": "approval-status",
            "title": "Approval Status",
            "type": "donut",
            "series": series,
            "total": sum(item["value"] for item in series),
        }

    # ------------------------------------------------------------------
    # Daftar
    # ------------------------------------------------------------------

    @staticmethod
    def recent_workflows(user, limit: int = RECENT_LIMIT) -> list[dict]:
        from apps.workflow import selectors

        rows = (
            selectors.visible_instances(user)
            .order_by("-created_at", "-id")[:limit]
        )

        return [
            {
                "id": row.id,
                "title": row.document_label or row.document_number or "-",
                "document_number": row.document_number,
                "module": row.module,
                "requester": (
                    row.submitted_by.get_full_name()
                    or row.submitted_by.username
                    if row.submitted_by_id
                    else None
                ),
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    @staticmethod
    def notifications(user, limit: int = RECENT_LIMIT) -> list[dict]:
        rows = Notification.objects.filter(user=user)[:limit]

        return [
            {
                "id": str(row.id),
                "title": row.title,
                "description": row.message,
                "type": row.type,
                "link": row.link,
                "is_read": row.is_read,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Quick actions
    # ------------------------------------------------------------------

    @staticmethod
    def quick_actions(user) -> list[dict]:
        """
        Katalog pintasan **beserta** mana yang dipilih pengguna.

        Katalog, bukan daftar terpilih — satu request memberi kedua
        keadaan, jadi masuk mode Customize tidak menembak API lagi.
        Pola yang sama dengan katalog aplikasi dan susunan widget.

        Penyaringan menu + izin tetap di sini dan **tidak bisa dilewati
        pilihan pengguna**: yang tidak lolos tidak pernah masuk katalog,
        jadi tidak ada cara memilihnya. Pilihan hanya mempersempit apa
        yang sudah boleh.
        """
        from apps.accounts.api.menu_permissions.access import MenuAccessService

        from apps.administration.api.dashboard.services.layout_service import (
            LayoutService,
        )

        access = MenuAccessService.visible_for(user)

        unrestricted = access.get("unrestricted", False)
        routes = set(access.get("routes") or [])

        allowed = []

        for entry in QUICK_ACTIONS:
            if not unrestricted and entry["menu"] not in routes:
                continue

            permission = entry.get("permission")

            if permission and not user.has_perm(permission):
                continue

            allowed.append({
                key: value
                for key, value in entry.items()
                if key not in {"menu", "permission"}
            })

        chosen = LayoutService.config_for(user, "quick_actions").get("codes")

        # Belum pernah memilih = semuanya dipilih. Beranda yang kosong
        # sampai penggunanya membuka pengaturan adalah bawaan yang
        # tidak pernah membantu siapa pun.
        if not isinstance(chosen, list):
            for entry in allowed:
                entry["is_selected"] = True

            return allowed

        order = {code: index for index, code in enumerate(chosen)}

        for entry in allowed:
            entry["is_selected"] = entry["code"] in order

        # Yang dipilih lebih dulu, urut pilihan; sisanya menyusul urut
        # katalog supaya tetap bisa ditemukan di mode Customize.
        return sorted(
            allowed,
            key=lambda entry: order.get(entry["code"], len(order)),
        )

    # ------------------------------------------------------------------

    @classmethod
    def build(cls, user) -> dict:
        return {
            "highlights": cls.highlights(user),
            "kpis": cls.kpis(user),
            "charts": [cls.approval_status(user)],
            "quick_actions": cls.quick_actions(user),
            "notifications": cls.notifications(user),
            "workflows": cls.recent_workflows(user),
        }

    # ------------------------------------------------------------------
    # Sorotan hari ini
    # ------------------------------------------------------------------

    @classmethod
    def highlights(cls, user) -> list[dict]:
        """
        Hal-hal yang berlaku **hari ini** dan tidak muncul di mana pun
        lagi: ulang tahun, ulang tahun kerja, dan hari libur.

        Ditumpuk jadi satu daftar, bukan satu widget per jenis. Di hari
        biasa daftarnya kosong dan kepala halaman tampil apa adanya —
        tiga kartu yang 360 hari setahun berbunyi "tidak ada apa-apa
        hari ini" hanya melatih orang untuk berhenti membacanya.

        Ikut cakupan data: admin site tidak perlu diberi tahu ulang
        tahun pegawai site lain, dan angka pegawai di kartu sebelahnya
        pun sudah disaring dengan peta yang sama.
        """
        highlights = []

        holiday = cls._holiday_today(user)

        if holiday:
            highlights.append(holiday)

        highlights.extend(cls._birthdays_today(user))
        highlights.extend(cls._work_anniversaries_today(user))

        return highlights

    @staticmethod
    def _employee_queryset(user):
        from apps.accounts.scoping import DataScopeService
        from apps.hr.api.dashboard.services import EMPLOYEE_SCOPE
        from apps.hr.models import Employee

        return DataScopeService.filter(
            Employee.objects.filter(is_active=True, is_deleted=False),
            EMPLOYEE_SCOPE,
            user,
            required_permission=view_permission_for(Employee),
        )

    @classmethod
    def _birthdays_today(cls, user) -> list[dict]:
        from datetime import date

        today = date.today()

        rows = (
            cls._employee_queryset(user)
            .filter(
                birth_date__month=today.month,
                birth_date__day=today.day,
            )
            .order_by("first_name", "last_name")[:5]
        )

        return [
            {
                "kind": "birthday",
                "title": row.full_name,
                # Umurnya sengaja **tidak** disebut. Yang berulang tahun
                # belum tentu ingin usianya diumumkan ke seluruh kantor,
                # dan ucapannya tidak butuh angka itu.
                "subtitle": "Berulang tahun hari ini",
                "icon": "cake",
            }
            for row in rows
        ]

    @classmethod
    def _work_anniversaries_today(cls, user) -> list[dict]:
        from datetime import date

        today = date.today()

        rows = (
            cls._employee_queryset(user)
            .filter(
                employment__join_date__month=today.month,
                employment__join_date__day=today.day,
            )
            .exclude(employment__join_date__year=today.year)
            .select_related("employment")
            .order_by("first_name", "last_name")[:5]
        )

        highlights = []

        for row in rows:
            years = today.year - row.employment.join_date.year

            highlights.append({
                "kind": "work_anniversary",
                "title": row.full_name,
                "subtitle": f"{years} tahun bergabung hari ini",
                "icon": "award",
            })

        return highlights

    @staticmethod
    def _holiday_today(user) -> dict | None:
        """
        Hari libur hari ini, atau yang paling dekat dalam sepekan.

        **Satu baris, bukan dua belas.** `Holiday` wajib menyebut
        company, jadi satu libur nasional tersimpan sekali per
        perusahaan — menampilkannya apa adanya membuat kepala halaman
        berisi dua belas baris yang sama persis.

        Menengok ke depan, bukan hanya hari-H: libur yang baru
        diberitahukan pada hari liburnya sendiri tidak berguna untuk
        siapa pun — yang mau menggeser rapat atau mengejar dokumen
        sudah terlambat. Batasnya sepekan; lebih jauh dari itu bukan
        lagi "sorotan hari ini", dan daftar 90 harinya sudah ada di
        dashboard Administration.
        """
        from datetime import date, timedelta

        from apps.administration.models import Holiday
        from apps.administration.services.calendar_resolver import (
            scope_holidays_for_user,
        )

        today = date.today()

        row = (
            scope_holidays_for_user(
                Holiday.objects.filter(
                    is_deleted=False,
                    date__gte=today,
                    date__lte=today + timedelta(days=HOLIDAY_LOOKAHEAD_DAYS),
                ),
                user,
            )
            .order_by("date", "name")
            .first()
        )

        if row is None:
            return None

        days_left = (row.date - today).days

        if days_left == 0:
            subtitle = "Hari libur hari ini"
        elif days_left == 1:
            subtitle = "Libur besok"
        else:
            subtitle = f"Libur {days_left} hari lagi"

        return {
            "kind": "holiday",
            "title": row.name,
            "subtitle": subtitle,
            "icon": "party-popper",
        }
