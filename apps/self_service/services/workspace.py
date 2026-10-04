"""
Perakit `GET /api/me/workspace/` — **lapisan agregasi, bukan pemilik data**.

Satu aturan yang mengatur seluruh berkas ini: *tidak ada satu pun angka
yang lahir di sini*. Jadwal datang dari `ShiftCalendarService`, presensi
dari baris `EmployeeAttendance` yang menitnya sudah dihitung
`AttendancePolicyResolver`, saldo cuti dari properti `LeaveBalance.remaining`,
dan hitungan approval dari `workflow.selectors.summary_for`. Yang
dikerjakan berkas ini cuma memilih *mana* yang ditampilkan dan
*bagaimana* bentuknya.

Kalau suatu hari sebuah perhitungan terasa perlu ditulis di sini, itu
tanda perhitungannya kurang di domainnya — bukan tanda berkas ini perlu
tumbuh.

Identitas
---------
`employee` **selalu** datang dari `CurrentEmployeeService`. Tidak ada
satu pun parameter di berkas ini yang menerima pegawai dari client, dan
tidak ada jalur yang menerimanya — jadi tidak ada jalur yang bisa lupa
memeriksanya.

Cakupan data (`DataScopeService`) sengaja **tidak** dipakai. Sumbunya
berbeda: cakupan menjawab "baris siapa yang boleh dilihat role ini",
Self Service menjawab "baris ini memang dirinya". Setiap query di bawah
karena itu menyaring `employee=employee` secara harfiah — bukan
menyaring cakupan lalu berharap hasilnya menyempit ke satu orang.

Tiga keadaan, dan ketiganya berbeda
-----------------------------------
* `ready`      — kemampuannya ada, datanya ada
* `empty`      — kemampuannya ada, pegawai ini memang belum punya datanya
* `restricted` — akun ini tidak berhak atas jenis datanya sama sekali

Yang ketiga hanya dipakai slip gaji, dan sebabnya ada di `_payslip`.
Kemampuan yang memang **belum dibangun** tidak muncul sebagai keadaan
apa pun di sini — ia tidak punya kunci, dan layarnya tidak menggambar
kartunya. Kartu "segera hadir" adalah cara tercepat melatih orang
berhenti membaca dashboard-nya.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.utils import timezone

# Jam dinding kantor, **dipinjam bukan disalin**. `TIME_ZONE` proyek ini
# UTC, jadi `timezone.localdate()` telanjang menggeser "hari ini" tujuh
# jam dari hari kerja orangnya — dan antara tengah malam sampai pukul
# tujuh pagi WIB, dashboard akan menampilkan jadwal kemarin. Konstanta
# yang sama sudah dipakai importer presensi, jalur agent, dan seed;
# salinan keempat di sini adalah persis cara selisih tujuh jam lahir di
# salah satunya saja.
from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ


READY = "ready"
EMPTY = "empty"
RESTRICTED = "restricted"


# ----------------------------------------------------------------------
# Tombol
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceAction:
    """
    Satu tombol dashboard beserta **dua syarat** yang harus lulus
    keduanya sebelum ia boleh tampil.

    `menu_route` — baris menu yang harus terlihat untuk akun ini. Ini
    bukan penjagaan dan tidak menggantikan satu pun: halamannya tetap
    menegakkan izinnya sendiri, dan URL-nya tetap bisa diketik. Yang
    dicegah cuma menyodorkan pintu yang sudah pasti tidak terbuka.
    Alasan dan mekanisme yang sama persis dengan
    `FavoriteAppService.allowed_codes()` pada launcher beranda.

    `permission` — izin model yang benar-benar dituntut endpoint di
    balik halamannya. Tanpa syarat kedua ini, tombol "Ajukan Lembur"
    tetap tampil untuk orang yang menu-nya terbuka tapi
    `hr.add_employeeovertime`-nya tidak ada — dan penolakannya baru
    terbaca sesudah ia mengisi seluruh formulir.
    """

    code: str
    route: str
    menu_route: str
    permission: str = ""


# Katalog tombol. **Eksplisit, bukan diturunkan dari daftar menu.**
# Rute tujuan dan rute menu sengaja dipisah: yang dibuka orang adalah
# formulir (`/hr/leave/create`), sedangkan yang diatur di layar Role
# Menu Permission adalah modulnya (`/hr/leave`).
#
# Tidak satu pun menunjuk layar administratif: `/hr/employees`,
# `/hr/leave-balances`, dan kerabatnya sengaja tidak ada di sini
# walaupun sebagian pegawai kebetulan boleh membukanya.
ACTIONS: dict[str, WorkspaceAction] = {
    "profile": WorkspaceAction(
        "profile",
        "/me/profile",
        "/me/profile",
    ),
    # `?mode=my` hanya **niat tampilan**: layar Shift Calendar membuka
    # "Jadwal Saya" dan mengambil datanya dari `/api/me/schedule/`, yang
    # subjeknya diresolusi dari akun — bukan dari query string ini.
    # Layar dan menunya tetap satu; tidak ada kalender kedua di `/me`.
    "schedule": WorkspaceAction(
        "schedule",
        "/hr/shift-calendar?mode=my",
        "/hr/shift-calendar",
    ),
    # **Bukan `/hr/attendance`.** Yang di HR adalah meja administratif:
    # ia menerima `?employee=`, menampilkan kolom keputusan HR, dan
    # barisnya baru tersaring ke pemiliknya lewat cakupan data — jalan
    # yang benar untuk admin dan jalan yang salah untuk orang yang cuma
    # ingin melihat presensinya sendiri. `/me/attendance` menjawab
    # pertanyaan itu langsung, dan identitasnya tidak bisa digeser.
    "attendance": WorkspaceAction(
        "attendance",
        "/me/attendance",
        "/me/attendance",
    ),
    "approvals": WorkspaceAction(
        "approvals",
        "/workflow/inbox",
        "/workflow/inbox",
    ),
    "submissions": WorkspaceAction(
        "submissions",
        "/workflow/submissions",
        "/workflow/submissions",
    ),
    # `?mode=my`: formulir pribadi yang mengirim ke `/api/me/*`, tanpa
    # pilihan pegawai. Menu dan izinnya tetap milik modul HR.
    "leave_request": WorkspaceAction(
        "leave_request",
        "/hr/leave/create?mode=my",
        "/hr/leave",
        "hr.add_employeeleave",
    ),
    "permission_request": WorkspaceAction(
        "permission_request",
        "/hr/attendance-permissions/create?mode=my",
        "/hr/attendance-permissions",
        "hr.add_attendancepermission",
    ),
    "overtime_request": WorkspaceAction(
        "overtime_request",
        "/hr/overtime/create",
        "/hr/overtime",
        "hr.add_employeeovertime",
    ),
    "payslip": WorkspaceAction(
        "payslip",
        "/payroll/payslips",
        "/payroll/payslips",
        "payroll.view_payslip",
    ),
}


# Aksi cepat, urut. Yang tidak lolos syaratnya **hilang**, bukan
# ditampilkan kelabu: tombol mati di dashboard pribadi tidak
# memberitahukan apa pun yang berguna — pemiliknya tidak bisa
# memberikan izin kepada dirinya sendiri.
QUICK_ACTION_CODES = (
    "profile",
    "leave_request",
    "permission_request",
    "overtime_request",
)


class ActionResolver:
    """
    Menjawab "tombol ini layak ditampilkan untuk akun ini?" sekali per
    request, bukan sekali per kartu.
    """

    def __init__(self, user):
        from apps.accounts.api.menu_permissions.access import MenuAccessService

        access = MenuAccessService.visible_for(user)

        self._user = user
        self._unrestricted = bool(access.get("unrestricted"))
        self._routes = set(access.get("routes") or [])

    def _menu_visible(self, route: str) -> bool:
        return self._unrestricted or route in self._routes

    def has_permission(self, permission: str) -> bool:
        if not permission:
            return True

        user = self._user

        if user is None:
            return False

        if getattr(user, "is_superuser", False):
            return True

        return bool(user.has_perm(permission))

    def resolve(self, code: str) -> dict | None:
        """`{"code", "route"}` kalau layak, `None` kalau tidak."""
        action = ACTIONS[code]

        if not self._menu_visible(action.menu_route):
            return None

        if not self.has_permission(action.permission):
            return None

        return {"code": action.code, "route": action.route}


# ----------------------------------------------------------------------
# Perakit
# ----------------------------------------------------------------------


def _reference(obj) -> dict | None:
    if obj is None:
        return None

    return {
        "id": obj.pk,
        "code": getattr(obj, "code", "") or "",
        "name": getattr(obj, "name", "") or "",
    }


def _wall_clock(value) -> str | None:
    """
    Jam dinding kantor untuk sebuah timestamp, `"HH:MM"`.

    Dirakit di sini, bukan di layar. `check_in` tersimpan sebagai UTC,
    dan frontend merender dengan jam **perangkat** — pegawai yang
    laptopnya diset WITA akan melihat jam masuknya sendiri bergeser satu
    jam, tanpa satu pun tanda bahwa yang bergeser adalah tampilannya.
    Jam kerja adalah jam kantor, dan kantornya punya satu zona.
    """
    if value is None:
        return None

    return timezone.localtime(value, WALL_CLOCK_TZ).strftime("%H:%M")


class SelfWorkspaceService:
    """Ringkasan hari kerja pegawai yang sedang login."""

    @classmethod
    def today(cls) -> date:
        return timezone.localdate(timezone=WALL_CLOCK_TZ)

    @classmethod
    def build(cls, *, employee, user, as_of: date | None = None) -> dict:
        day = as_of or cls.today()

        actions = ActionResolver(user)

        return {
            "as_of": day,
            "schedule": cls._schedule(employee, day, actions),
            "attendance": cls._attendance(employee, day, actions),
            "requests": cls._requests(user, actions),
            "leave": cls._leave(employee, day, actions),
            "permission": cls._permission(employee, actions),
            "overtime": cls._overtime(employee, day, actions),
            "payslip": cls._payslip(employee, actions),
            "quick_actions": [
                resolved
                for code in QUICK_ACTION_CODES
                if (resolved := actions.resolve(code)) is not None
            ],
        }

    # ------------------------------------------------------------------
    # Jadwal hari ini
    # ------------------------------------------------------------------

    @classmethod
    def _schedule(cls, employee, day: date, actions: ActionResolver) -> dict:
        """
        Satu sel kalender, dari mesin kalender yang sama dengan layar
        Shift Calendar.

        **Nol perhitungan roster di sini.** Yang menentukan shift mana
        yang berlaku hari ini — rotasi, penugasan, hari pemulihan, hari
        libur — seluruhnya `ShiftCalendarService`. Rentangnya satu hari,
        jadi yang dibayar cuma sel yang benar-benar ditampilkan.
        """
        from apps.hr.api.shift_calendar.services import ShiftCalendarService

        action = actions.resolve("schedule")

        empty = {
            "state": EMPTY,
            "rotation_state": None,
            "rotation_state_label": "",
            "shift_name": "",
            "time_label": "",
            "location": None,
            "action": action,
        }

        try:
            payload = ShiftCalendarService.build(
                employee=employee,
                start=day,
                end=day,
            )
        except DjangoValidationError:
            # Kalender menolak merakit (masa kerja belum mulai, konfigurasi
            # roster belum lengkap). Itu keadaan yang sah dan bukan galat
            # halaman — dashboard tetap berdiri, kartunya yang kosong.
            return empty

        days = payload.get("days") or []

        if not days:
            return empty

        cell = days[0]

        organization = getattr(employee, "organization", None)

        result = {
            # Keadaan hari ini selalu dikirim, termasuk saat tidak ada
            # shift: "Libur" dan "Belum dijadwalkan" adalah dua jawaban
            # yang sangat berbeda, dan keduanya jauh lebih berguna
            # daripada kartu kosong.
            "rotation_state": cell.get("rotation_state"),
            "rotation_state_label": cell.get("rotation_state_label") or "",
            "shift_name": cell.get("shift_name") or "",
            "time_label": cell.get("scheduled_label") or "",
            "location": _reference(
                getattr(organization, "location", None),
            ),
            "action": action,
        }

        result["state"] = READY if cell.get("is_scheduled") else EMPTY

        return result

    # ------------------------------------------------------------------
    # Kehadiran hari ini
    # ------------------------------------------------------------------

    @classmethod
    def _attendance(cls, employee, day: date, actions: ActionResolver) -> dict:
        """
        Baris presensi hari ini — **daftar putih**, bukan barisnya apa
        adanya.

        Yang sengaja tidak ikut: `notes`, `adjustment_reason`,
        `review_notes`, `review_decision`, `approved_by`, seluruh kolom
        `leave_required_*`, koordinat dan alamat check-in/out, `device_code`,
        `external_id`, `import_batch_id`, dan seluruh metadata audit.
        Sebagian catatan kerja HR, sebagian jejak perangkat — tidak satu
        pun jawaban atas "bagaimana kehadiran saya hari ini".

        `late_minutes` ikut karena ia **sudah dihitung domain**
        (`AttendancePolicyResolver`), bukan disimpulkan di sini.
        """
        from apps.hr.models import EmployeeAttendance

        action = actions.resolve("attendance")

        row = (
            EmployeeAttendance.objects
            .filter(
                employee=employee,
                work_date=day,
                is_deleted=False,
            )
            .order_by("-id")
            .first()
        )

        if row is None:
            return {
                "state": EMPTY,
                "status": None,
                "status_label": "",
                "check_in": None,
                "check_out": None,
                "late_minutes": 0,
                "early_leave_minutes": 0,
                "action": action,
            }

        return {
            "state": READY,
            "status": row.status,
            "status_label": row.get_status_display(),
            "check_in": _wall_clock(row.check_in),
            "check_out": _wall_clock(row.check_out),
            "late_minutes": row.late_minutes,
            "early_leave_minutes": row.early_leave_minutes,
            "action": action,
        }

    # ------------------------------------------------------------------
    # Tugas & permintaan
    # ------------------------------------------------------------------

    @classmethod
    def _requests(cls, user, actions: ActionResolver) -> dict:
        """
        Dua angka dari engine workflow, lewat selector yang sudah ada.

        `summary_for` mengembalikan empat kunci; dua di antaranya
        (`can_configure`, `can_monitor_all`) adalah **kemampuan role**
        dan sengaja tidak diteruskan. Dashboard pribadi tidak punya
        alasan mengabarkan apa yang boleh dilakukan pemiliknya di layar
        konfigurasi.
        """
        from apps.workflow import selectors

        summary = selectors.summary_for(user)

        waiting = int(summary.get("waiting_for_me") or 0)
        mine = int(summary.get("my_open_submissions") or 0)

        return {
            "state": READY if (waiting or mine) else EMPTY,
            "waiting_for_me": waiting,
            "my_open_submissions": mine,
            "approvals_action": actions.resolve("approvals"),
            "submissions_action": actions.resolve("submissions"),
        }

    # ------------------------------------------------------------------
    # Cuti
    # ------------------------------------------------------------------

    @classmethod
    def _leave(cls, employee, day: date, actions: ActionResolver) -> dict:
        """
        Saldo cuti tahun berjalan.

        `remaining` **properti model**, bukan pengurangan yang ditulis
        ulang di sini: jatah, bawaan tahun lalu, saldo awal migrasi, dan
        yang sudah hangus punya kantongnya masing-masing, dan menjumlah
        ulang keempatnya di lapisan presentasi berarti ada dua versi
        saldo yang harus tetap sepakat.
        """
        from apps.hr.models import LeaveBalance

        rows = (
            LeaveBalance.objects
            .filter(
                employee=employee,
                year=day.year,
                is_deleted=False,
            )
            .select_related("leave_type")
            .order_by("leave_type__name")
        )

        balances = [
            {
                "leave_type": _reference(row.leave_type),
                "remaining": float(row.remaining),
                "year": row.year,
            }
            for row in rows
        ]

        return {
            "state": READY if balances else EMPTY,
            "year": day.year,
            "balances": balances,
            "action": actions.resolve("leave_request"),
        }

    # ------------------------------------------------------------------
    # Izin
    # ------------------------------------------------------------------

    @classmethod
    def _permission(cls, employee, actions: ActionResolver) -> dict:
        """
        Pengajuan izin terakhir + berapa yang masih menunggu keputusan.

        Status "menunggu" memakai `PERMISSION_PENDING_STATUSES` milik
        domainnya — daftar yang sama yang dipakai layar presensi untuk
        memasang lencana "Permission Pending". Menulis daftarnya sendiri
        di sini berarti dua tempat harus tetap sepakat tentang apa
        artinya menunggu.
        """
        from apps.hr.models.attendance.permission import (
            PERMISSION_PENDING_STATUSES,
            AttendancePermission,
        )

        action = actions.resolve("permission_request")

        rows = AttendancePermission.objects.filter(
            employee=employee,
            is_deleted=False,
        )

        pending = rows.filter(status__in=PERMISSION_PENDING_STATUSES).count()

        latest = rows.order_by("-date", "-id").first()

        if latest is None:
            return {
                "state": EMPTY,
                "pending_count": pending,
                "latest": None,
                "action": action,
            }

        return {
            "state": READY,
            "pending_count": pending,
            "latest": {
                "date": latest.date,
                "permission_type": latest.permission_type,
                "permission_type_label": latest.get_permission_type_display(),
                "status": latest.status,
                "status_label": latest.get_status_display(),
            },
            "action": action,
        }

    # ------------------------------------------------------------------
    # Lembur
    # ------------------------------------------------------------------

    @classmethod
    def _overtime(cls, employee, day: date, actions: ActionResolver) -> dict:
        """
        Menit lembur bulan berjalan.

        **Aturan status dipinjam dari payroll**, bukan dikarang di sini:
        `PayrollSourceService._collect_overtime` menghitung yang
        `is_paid` dan berstatus RECORDED/APPROVED, dan itulah lembur yang
        benar-benar dibayarkan. Angka di dashboard pribadi harus sama
        dengan angka yang nanti muncul di slip — kalau tidak, yang
        pertama cuma melatih orang menagih selisih yang tidak ada.

        Yang dijumlah `duration_minutes`, kolom yang sudah **dihitung
        domain** (`EmployeeOvertimeService.apply_duration`) dari jam mulai
        dan jam selesai. Tidak ada satu pun jam yang diubah jadi menit di
        berkas ini.

        Diketahui: `HRDashboardService.overtime_total_hours` memakai
        aturan yang lebih sempit (RECORDED saja). Dua aturan itu sudah
        berbeda sebelum berkas ini ada dan tidak disatukan di sini —
        lihat FOLLOW-UP di `docs/claude/self-service.md`.
        """
        from apps.hr.models import EmployeeOvertime
        from apps.hr.models.overtime import OvertimeStatus

        start = day.replace(day=1)

        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)

        minutes = (
            EmployeeOvertime.objects
            .filter(
                employee=employee,
                is_deleted=False,
                is_paid=True,
                status__in=[
                    OvertimeStatus.RECORDED,
                    OvertimeStatus.APPROVED,
                ],
                work_date__gte=start,
                work_date__lt=end,
            )
            .aggregate(total=Sum("duration_minutes"))
            .get("total")
        ) or 0

        return {
            # Nol menit berarti "bulan ini belum ada lembur", dan itu
            # keadaan kosong yang sah — bukan angka yang layak dipajang
            # besar-besar. Layarnya yang memutuskan kalimatnya.
            "state": READY if minutes else EMPTY,
            "period": start,
            "total_minutes": int(minutes),
            "action": actions.resolve("overtime_request"),
        }

    # ------------------------------------------------------------------
    # Slip gaji
    # ------------------------------------------------------------------

    @classmethod
    def _payslip(cls, employee, actions: ActionResolver) -> dict:
        """
        **Metadata slip terakhir. Tidak satu angka rupiah pun.**

        Yang dikirim: periode, tanggal terbit, nomor dokumen. Yang
        sengaja tidak — dan tidak boleh ditambahkan tanpa keputusan
        tersendiri: `basic_salary`, `gross_earning`, `total_deduction`,
        `tax_amount`, `net_pay`, `employer_contribution`, `snapshot`,
        dan `notes`. Dashboard dibuka di ruang terbuka dan sering
        terlihat orang yang kebetulan lewat; nilai gaji layak jadi
        tindakan yang disadari, bukan sesuatu yang tercetak begitu
        halaman dimuat.

        Satu-satunya seksi yang bisa berstatus `restricted`, dan itu
        mengikuti keputusan domainnya sendiri: `PayslipViewSet` menyatakan
        `require_view_permission = True`, jadi slip gaji adalah jenis data
        yang **memang** dijaga izin model — tidak seperti presensi atau
        jadwal, yang bacanya terbuka dan barisnya disempitkan cakupan.
        Self Service menghormati deklarasi itu alih-alih membuat pintu
        kedua di sebelahnya.

        Hanya yang **PUBLISHED**. Slip berstatus draft belum diterbitkan
        kepada siapa pun, dan memperlihatkannya berarti pegawai membaca
        angka yang masih boleh berubah.
        """
        from apps.payroll.models import Payslip
        from apps.payroll.models.choices import PayslipStatus

        if not actions.has_permission("payroll.view_payslip"):
            return {
                "state": RESTRICTED,
                "latest": None,
                "action": None,
            }

        action = actions.resolve("payslip")

        latest = (
            Payslip.objects
            .filter(
                employee=employee,
                is_deleted=False,
                status=PayslipStatus.PUBLISHED,
            )
            .select_related("period")
            .order_by("-period__start_date", "-id")
            .first()
        )

        if latest is None:
            return {
                "state": EMPTY,
                "latest": None,
                "action": action,
            }

        period = getattr(latest, "period", None)

        return {
            "state": READY,
            "latest": {
                "period": _reference(period),
                "period_start": getattr(period, "start_date", None),
                "issue_date": latest.issue_date,
                "document_number": latest.document_number or "",
            },
            "action": action,
        }
