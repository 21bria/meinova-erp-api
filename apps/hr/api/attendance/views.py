from django.core.exceptions import PermissionDenied

from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import PeriodScopedListMixin
from apps.hr.models import EmployeeAttendance

from .obligation import AttendanceObligationService
from .serializers import EmployeeAttendanceSerializer
from .services import EmployeeAttendanceService

from .schema import ATTENDANCE_SCHEMA

class EmployeeAttendanceViewSet(
    PeriodScopedListMixin,
    BaseMasterViewSet,
):
    # Presensi dibaca **per periode**, bukan per sejarah.
    #
    # Tanpa `date_from`/`date_to` daftarnya jatuh ke bulan berjalan
    # sampai hari ini. Yang dibatasi cuma aksi daftar dan export —
    # `retrieve`/`update`/`destroy` tetap menjangkau tanggal mana pun,
    # karena baris yang sudah ditemukan orang harus tetap bisa dibuka.
    #
    # Rentangnya berlaku **sebelum** filter lain, jadi Status = Present
    # berarti "yang Present di dalam periode terpilih", bukan yang
    # Present sepanjang masa lalu dipotong belakangan. Lihat
    # `apps.framework.list_period`.
    period_field = "work_date"

    # Penyaringan data per baris (kewenangan `RoleAssignment`). Kolom
    # organisasinya sudah tersimpan langsung di record ini; `section`
    # lewat penempatan pegawainya karena baris ini tidak menyimpannya.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = EmployeeAttendanceSerializer
    service_class = EmployeeAttendanceService

    framework_module = "hr/attendance"
    schema = ATTENDANCE_SCHEMA


    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "company__name",
        "branch__name",
        "location__name",
        "shift__name",
        "external_id",
        "device_code",
        "import_batch_id",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "company",
        "branch",
        "location",
        "shift",
        "work_date",
        "status",
        "source",
        "approval_status",
        "is_manual_adjustment",
        "is_geofence_valid",
        # Daftar kerja HR: baris mana yang kewajiban cutinya belum
        # diselesaikan. Tanpa filternya, penandanya cuma bisa ditemukan
        # dengan menggulir seluruh bulan.
        "leave_required_reason",
        "leave_required_waived",
        "review_decision",
        # Daftar kerja pengecualian: mana yang ada izinnya, mana
        # yang tidak, dan mana yang izinnya belum diputuskan.
        "permission_state",
        "is_excused_absence",
    ]

    ordering_fields = [
        "work_date",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "company__name",
        "branch__name",
        "location__name",
        "shift__name",
        "status",
        "source",
        "approval_status",
        "scheduled_check_in",
        "scheduled_check_out",
        "check_in",
        "check_out",
        "worked_minutes",
        "break_minutes",
        "late_minutes",
        "early_leave_minutes",
        "overtime_minutes",
        "excused_late_minutes",
        "excused_early_leave_minutes",
        "permission_minutes",
        "permission_state",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-work_date",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            EmployeeAttendance.objects
            .select_related(
                "employee",
                "company",
                "branch",
                "location",
                "shift",
                "approved_by",
                "created_by",
                "updated_by",
                "deleted_by",
                # Status kewajiban diturunkan dari dokumen cutinya, jadi
                # tanpa ini setiap baris menambah satu query saat
                # daftarnya dirender.
                "leave",
                "reviewed_by",
            )
            .filter(
                is_deleted=False,
            )
        )

    # ------------------------------------------------------------------
    # Kewajiban cuti dari presensi
    # ------------------------------------------------------------------
    #
    # Tiga tombol, bukan otomatis — alasannya di
    # `AttendanceObligationService`. Yang menolak tetap service; aksi di
    # sini cuma menerjemahkan payload dan membungkus responsnya.

    def _user(self, request):
        user = getattr(request, "user", None)

        if user is not None and user.is_authenticated:
            return user

        return None

    def _respond(self, *, instance, message):
        instance.refresh_from_db()

        return success_response(
            data=self.get_serializer(instance).data,
            message=message,
        )

    def _guard(self, handler):
        """
        `PermissionDenied` milik Django jadi 403 DRF.

        Tanpa terjemahan ini, penolakan wewenang jatuh sebagai 500 —
        `meinova_exception_handler` mengenali `ValidationError` Django,
        tapi tidak yang satu ini.
        """
        try:
            return handler()
        except PermissionDenied as exc:
            raise DRFPermissionDenied(str(exc)) from exc

    @action(detail=True, methods=["post"])
    def waive(self, request, pk=None):
        instance = self.get_object()

        result = self._guard(
            lambda: AttendanceObligationService.waive(
                instance=instance,
                reason=request.data.get("reason", ""),
                user=self._user(request),
            ),
        )

        return self._respond(
            instance=result,
            message="Kewajiban cuti dibebaskan.",
        )

    @action(detail=True, methods=["post"], url_path="require-leave")
    def require_leave(self, request, pk=None):
        instance = self.get_object()

        days = request.data.get("days")

        result = self._guard(
            lambda: AttendanceObligationService.require_leave(
                instance=instance,
                notes=request.data.get("notes", ""),
                days=days if days not in (None, "") else None,
                user=self._user(request),
            ),
        )

        return self._respond(
            instance=result,
            message=(
                "Pegawai diberi tahu untuk mengajukan cuti."
            ),
        )

    @action(detail=True, methods=["post"], url_path="issue-leave")
    def issue_leave(self, request, pk=None):
        instance = self.get_object()

        leave = self._guard(
            lambda: AttendanceObligationService.issue_leave(
                instance=instance,
                user=self._user(request),
            ),
        )

        return self._respond(
            instance=instance,
            message=(
                f"Dokumen cuti {leave.document_number or leave.pk} "
                f"dibuat sebagai draft."
            ),
        )