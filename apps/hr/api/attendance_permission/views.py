"""
ViewSet Attendance Permission.

`ServiceWriteMixin` dipasang di depan — tanpa itu `service_class` hanya
dipakai untuk `get_queryset()` dan `soft_delete()`, jalur tulisnya tetap
`serializer.save()` bawaan DRF, dan seluruh isi `services.py`
(penomoran, pengisian cakupan, penolakan izin di luar shift, penjagaan
periode terkunci, perhitungan ulang presensi) tidak pernah jalan lewat
API. Gagalnya diam: dokumennya tersimpan, cuma tanpa nomor dan tanpa
satu pun pemeriksaan.
"""

from django.core.exceptions import ValidationError

from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.write_scope import EmployeeSubjectWriteGuardMixin

from apps.hr.models import AttendancePermission

from .schema import ATTENDANCE_PERMISSION_SCHEMA
from .serializers import AttendancePermissionSerializer
from .services import AttendancePermissionService


class AttendancePermissionViewSet(
    # `employee` di body dijaga cakupan tulis — create tidak pernah
    # melewati `filter_queryset()`. Lihat `employee/write_scope.py`.
    EmployeeSubjectWriteGuardMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Penyaringan data per baris (kewenangan `RoleAssignment`). Kolom
    # organisasinya sudah tersimpan langsung di dokumen ini; `division`,
    # `department`, dan `section` lewat penempatan pegawainya karena
    # dokumen ini tidak menyimpannya.
    #
    # `own` menunjuk akun pegawainya: Employee Self Service berdiri di
    # atas kunci ini — pegawai biasa melihat izinnya sendiri dan tidak
    # satu pun milik orang lain.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = AttendancePermissionSerializer
    service_class = AttendancePermissionService

    framework_module = "hr/attendance-permissions"
    schema = ATTENDANCE_PERMISSION_SCHEMA

    # Base memberi default ["code", "name"] dan model ini tidak punya
    # keduanya — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "company__name",
        "location__name",
        "reason",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "company",
        "branch",
        "location",
        "permission_type",
        "date",
        "status",
        "allow_outside_shift",
    ]

    ordering_fields = [
        "date",
        "document_number",
        "permission_type",
        "status",
        "employee__employee_number",
        "employee__first_name",
        "submitted_at",
        "approved_at",
        "created_at",
        "updated_at",
    ]

    ordering = ["-date", "employee__employee_number", "-id"]

    def get_queryset(self):
        return (
            AttendancePermission.objects
            .select_related(
                "employee",
                "employee__organization",
                "employee__organization__division",
                "employee__organization__department",
                "employee__organization__section",
                "employee__employment",
                "employee__employment__shift",
                "employee__employment__work_schedule",
                "company",
                "branch",
                "location",
                "supporting_document",
                "created_by",
                "updated_by",
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Kolom "Current Approver" di daftar
    # ------------------------------------------------------------------

    def list(self, request, *args, **kwargs):
        """
        Menyiapkan peta approver berjalan **sekali per halaman**.

        Tanpa ini kolomnya harus menanyakan workflow per baris, dan
        satu halaman 25 baris berarti 25 pencarian untuk satu kolom
        teks. Petanya dititipkan lewat `context` dan dibaca
        `AttendancePermissionSerializer.get_current_approver`.

        Yang dipakai halaman **setelah** paginasi, bukan seluruh
        queryset: menyiapkan peta untuk ribuan baris yang tidak
        dirender adalah pekerjaan yang lebih besar daripada yang
        dihindarinya.
        """
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        rows = page if page is not None else list(queryset)

        serializer = self.get_serializer(
            rows,
            many=True,
            context={
                **self.get_serializer_context(),
                "current_approvers": self._current_approvers(rows),
            },
        )

        if page is not None:
            return self.get_paginated_response(serializer.data)

        return success_response(data=serializer.data)

    @staticmethod
    def _current_approvers(rows) -> dict:
        """
        `{permission_id: nama approver}` untuk baris yang sedang
        menunggu keputusan.

        Dokumen ditunjuk engine lewat `module` + `document_type` +
        `object_id` **bertipe teks**, jadi tidak ada FK yang bisa
        di-`prefetch_related`. Yang bisa dilakukan satu query `IN`
        untuk seluruh halaman — dan itu yang dipakai di sini.
        """
        from apps.workflow.models import (
            ApprovalStatus,
            InstanceStatus,
            WorkflowInstance,
        )

        ids = [str(row.pk) for row in rows]

        if not ids:
            return {}

        instances = (
            WorkflowInstance.objects
            .filter(
                module="hr",
                document_type="attendance_permission",
                object_id__in=ids,
                status=InstanceStatus.PENDING,
            )
            .prefetch_related(
                "approvals__approver_employee",
                "approvals__approver",
            )
            .order_by("-id")
        )

        mapping: dict = {}

        for instance in instances:
            # Pengajuan terbaru yang menang. `order_by("-id")` plus
            # `setdefault` membuat pengajuan ulang tidak tertimpa yang
            # lama untuk dokumen yang sama.
            key = int(instance.object_id)

            if key in mapping:
                continue

            current = next(
                (
                    row
                    for row in sorted(
                        instance.approvals.all(),
                        key=lambda r: (r.sequence, r.pk),
                    )
                    if row.status == ApprovalStatus.PENDING
                    and row.step_id == instance.current_step_id
                ),
                None,
            )

            if current is None:
                continue

            if current.approver_employee_id:
                name = current.approver_employee.full_name
            elif current.approver_id:
                name = (
                    current.approver.get_full_name()
                    or current.approver.email
                )
            else:
                name = ""

            mapping[key] = name

        return mapping

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message, extra=None):
        # Dibaca ulang lewat queryset, bukan `refresh_from_db()`: yang
        # kedua tidak membersihkan cache select_related, jadi presensi
        # yang baru dihitung ulang tidak muncul di respons dan fiturnya
        # terbaca gagal padahal barisnya sudah berubah.
        fresh = self.get_queryset().get(pk=instance.pk)

        data = {
            "attendance_permission": AttendancePermissionSerializer(
                fresh,
                context=self.get_serializer_context(),
            ).data,
        }

        if extra:
            data.update(extra)

        return success_response(data=data, message=message)

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        instance = self.get_object()

        AttendancePermissionService.submit(
            permission=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Izin kehadiran diajukan.",
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._decide(request, approved=True)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._decide(request, approved=False)

    def _decide(self, request, *, approved: bool):
        instance = self.get_object()

        notes = request.data.get("notes", "")

        # Penolakan tanpa alasan tidak bisa ditindaklanjuti pengaju —
        # dia hanya tahu ditolak, tidak tahu apa yang harus dibetulkan.
        if not approved and not str(notes).strip():
            raise ValidationError(
                {"notes": "Alasan penolakan wajib diisi."},
            )

        AttendancePermissionService.decide(
            permission=instance,
            approved=approved,
            user=self._user(request),
            notes=notes,
        )

        instance.refresh_from_db()

        recalculated = AttendancePermissionService.recalculate_attendance(
            permission=instance,
        )

        return self._respond(
            instance=instance,
            message=(
                "Izin kehadiran disetujui."
                if approved
                else "Izin kehadiran ditolak."
            ),
            # Nol berarti barisnya belum ada — presensi tanggal itu
            # belum diimpor. Disebut apa adanya, supaya tidak ada yang
            # menunggu perubahan yang memang belum bisa terjadi.
            extra={"attendance_recalculated": recalculated},
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        instance = self.get_object()

        AttendancePermissionService.cancel(
            permission=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Izin kehadiran dibatalkan.",
        )

    @action(detail=True, methods=["get"], url_path="conflicts")
    def conflicts(self, request, pk=None):
        """
        Peringatan atas satu izin, tanpa menyimpan apa pun.

        Endpoint tersendiri di samping field `conflicts` di serializer:
        layar create memanggilnya **sebelum** dokumennya tersimpan
        supaya tabrakan dengan cuti terbaca saat form masih terbuka.
        """
        instance = self.get_object()

        return success_response(
            data={
                "conflicts": (
                    AttendancePermissionService.detect_conflicts(instance)
                ),
            },
        )
