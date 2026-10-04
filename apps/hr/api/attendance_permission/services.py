"""
Service Attendance Permission.

Empat tanggung jawab yang tidak boleh bocor ke serializer atau view:
penomoran dokumen, alur persetujuan, penjagaan terhadap jadwal &
periode terkunci, dan pemicu perhitungan ulang presensi.

Pembagian validasi mengikuti pola yang sudah dipakai Visitor: yang
menyangkut **satu record** (kolom jam yang tidak sesuai tipenya, alasan
kosong) di `Model.clean()`; yang menyangkut **baris lain atau keadaan
dokumen** (tumpang tindih, di luar shift, periode payroll terkunci) di
sini. `clean()` tidak boleh menolak berdasarkan status — kalau tidak,
setiap perpindahan status resmi ikut terjegal validasinya sendiri.
"""

from __future__ import annotations

import logging

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService
from apps.workflow.models import InstanceStatus
from apps.workflow.services import WorkflowService

from apps.hr.api.attendance.permission_effect import (
    AttendancePermissionEffectService,
    shift_window,
)
from apps.hr.api.attendance.permission_resolver import build_window
from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.models import (
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
    OrganizationAssignment,
    PERMISSION_ACTIVE_STATUSES,
)


logger = logging.getLogger(__name__)


class AttendancePermissionService(
    OrganizationDenormalizationMixin,
    BaseMasterService,
):
    model = AttendancePermission

    WORKFLOW_MODULE = "hr"
    WORKFLOW_DOCUMENT_TYPE = "attendance_permission"

    # ------------------------------------------------------------------
    # Penyiapan data
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_employee(data, user=user)
        data = cls.apply_organization(data)

        cls.assert_period_open(
            employee=data.get("employee"),
            work_date=data.get("date"),
        )

        cls.assert_within_shift(data)
        cls.assert_no_overlap(data)

        return cls.apply_document_number(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_editable(instance)

        data = cls.apply_organization(
            data,
            fallback_employee=instance.employee,
        )

        data = cls.rederive_organization(instance=instance, data=data)

        merged = cls._merged(instance, data)

        cls.assert_period_open(
            employee=merged["employee"],
            work_date=merged["date"],
        )

        cls.assert_within_shift(merged)
        cls.assert_no_overlap(merged, exclude_pk=instance.pk)

        return data

    @staticmethod
    def _merged(instance, data: dict[str, Any]) -> dict[str, Any]:
        """
        Nilai sesudah perubahan, untuk validasi yang butuh melihat
        record utuh.

        Form mengirim seluruh isi tab apa adanya, tapi jalur lain
        (aksi, importir) mengirim sebagian — dan validasi tumpang
        tindih yang membaca payload parsial akan membandingkan tanggal
        baru dengan jam lama.
        """
        keys = (
            "employee",
            "date",
            "permission_type",
            "start_time",
            "end_time",
            "allow_outside_shift",
        )

        return {
            key: data[key] if key in data else getattr(instance, key)
            for key in keys
        }

    @staticmethod
    def apply_employee(data: dict[str, Any], *, user=None) -> dict[str, Any]:
        """
        Mengisi pegawai dari akun yang mengetik, kalau tidak disebut.

        Jalur Employee Self Service: pegawai mengajukan izin untuk
        dirinya sendiri dan formnya memang tidak punya kolom pegawai.
        HR yang mengetikkan izin orang lain menyebutkannya eksplisit,
        dan itu tetap dijaga cakupan data di viewset.

        `employee_profile`, bukan `employee` — accessor-nya berasal
        dari `related_name` pada OneToOne, dan `getattr` untuk nama
        yang salah mengembalikan None tanpa error.
        """
        if data.get("employee") is not None:
            return data

        employee = getattr(user, "employee_profile", None)

        if employee is not None:
            data["employee"] = employee

        return data

    @staticmethod
    def rederive_organization(*, instance, data: dict[str, Any]) -> dict[str, Any]:
        """
        Pegawai berganti -> organisasinya ikut, bukan tertinggal.

        `apply_organization` hanya **mengisi yang kosong**, jadi
        memindahkan dokumen ke pegawai unit lain akan meninggalkan
        company/branch/location milik pegawai lama — dokumen yang
        menurut datanya berada di dua unit sekaligus, dan yang
        menentukan siapa boleh membacanya justru kolom yang basi itu.
        """
        if "employee" not in data:
            return data

        employee = data.get("employee")

        if employee is None or employee.pk == instance.employee_id:
            return data

        assignment = (
            OrganizationAssignment.objects
            .filter(employee=employee, is_active=True, is_deleted=False)
            .select_related("company", "branch", "location")
            .order_by("-organization_effective_date", "-id")
            .first()
        )

        if assignment is None:
            return data

        data["company"] = assignment.company
        data["branch"] = assignment.branch
        data["location"] = assignment.location

        return data

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="attendance_permission",
            company=data.get("company"),
        )

        return data

    # ------------------------------------------------------------------
    # Penjagaan
    # ------------------------------------------------------------------

    @staticmethod
    def assert_editable(instance: AttendancePermission) -> None:
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Izin berstatus {instance.get_status_display()} "
                    "tidak bisa disunting. Tarik kembali pengajuannya "
                    "dulu (Cancel), atau buat izin baru."
                ),
            },
        )

    @staticmethod
    def assert_period_open(*, employee, work_date) -> None:
        """
        Menolak perubahan pada tanggal yang periode payroll-nya sudah
        dikunci.

        **Tanpa model periode presensi baru.** Yang mengunci di sistem
        ini `PayrollPeriod` berstatus FINALIZED — dan itu memang kunci
        yang benar: yang tidak boleh berubah adalah tanggal yang
        angkanya sudah dipakai membayar orang. Menambah tabel periode
        kedua berarti dua jawaban untuk satu pertanyaan, dan yang satu
        akan menyimpang.

        Pesannya menyebut jalan keluarnya, bukan cuma penolakannya.
        "Periode terkunci" tanpa kelanjutan membuat orang mengetik
        ulang dokumen yang sama sampai menyerah.
        """
        if employee is None or work_date is None:
            return

        from apps.payroll.models import PayrollPeriod
        from apps.payroll.models.choices import PayrollPeriodStatus

        organization = getattr(employee, "organization", None)
        company_id = getattr(organization, "company_id", None)

        locked = (
            PayrollPeriod.objects
            .filter(
                is_deleted=False,
                status=PayrollPeriodStatus.FINALIZED,
                start_date__lte=work_date,
                end_date__gte=work_date,
            )
        )

        if company_id is not None:
            locked = locked.filter(company_id=company_id)

        period = locked.first()

        if period is None:
            return

        raise ValidationError(
            {
                "date": (
                    f"Periode {period.code} ({period.start_date} — "
                    f"{period.end_date}) sudah dikunci payroll. Izin "
                    "pada tanggal ini tidak bisa diubah langsung — "
                    "buat Attendance Adjustment atau run koreksi."
                ),
            },
        )

    @classmethod
    def assert_within_shift(cls, data: dict[str, Any]) -> None:
        """
        Izin harus jatuh di dalam jendela shift pegawainya.

        Yang ditolak izin 18:00–20:00 untuk orang bershift 08:00–17:00:
        hampir selalu salah ketik tanggal, dan menerimanya diam-diam
        menghasilkan dokumen yang tidak memaafkan apa pun lalu jadi
        keluhan sebulan kemudian.

        **Shift malam lolos**, dan itu inti pemeriksaannya: jendelanya
        dibentuk `shift_span()` yang sudah tahu 20:00–05:00 berakhir di
        tanggal berikutnya, lalu jam izinnya ditambatkan ke jendela itu
        oleh `build_window()`. Tidak ada satu pun perbandingan yang
        memakai tanggal kalender saja.

        Pegawai yang jadwalnya belum tersusun **dilewati** — tidak
        ditolak. Menolak berarti izin tidak bisa diajukan sampai master
        shift-nya lengkap, dan itu justru keadaan yang paling butuh
        pencatatan.
        """
        if data.get("allow_outside_shift"):
            # Override tanpa alasan tidak bisa dinilai siapa pun
            # sesudahnya — jejaknya cuma sebuah kotak tercentang.
            # Diperiksa di sini, bukan cuma di serializer, supaya jalur
            # mana pun yang menyalakan override membawa alasannya.
            if not (data.get("outside_shift_reason") or "").strip():
                raise ValidationError(
                    {
                        "outside_shift_reason": (
                            "Alasan override wajib diisi."
                        ),
                    },
                )

            return

        employee = data.get("employee")
        work_date = data.get("date")

        if employee is None or work_date is None:
            return

        shift_start, shift_end = shift_window(employee, work_date)

        if shift_start is None or shift_end is None:
            return

        window = build_window(
            _Draft(data),
            shift_start=shift_start,
            shift_end=shift_end,
        )

        if window.start is None or window.end is None:
            return

        if window.start >= shift_start and window.end <= shift_end:
            return

        raise ValidationError(
            {
                "start_time": (
                    f"Izin {window.start:%H:%M}–{window.end:%H:%M} "
                    f"berada di luar jam kerja "
                    f"{shift_start:%H:%M}–{shift_end:%H:%M} pada "
                    f"{work_date}. Periksa tanggalnya, atau nyalakan "
                    "override HR beserta alasannya."
                ),
            },
        )

    @classmethod
    def assert_no_overlap(
        cls,
        data: dict[str, Any],
        *,
        exclude_pk=None,
    ) -> None:
        """
        Dua izin yang jendelanya bertabrakan di tanggal yang sama
        ditolak.

        **Ini satu-satunya konflik yang menghentikan penyimpanan.**
        Konflik dengan cuti, perjalanan dinas, atau hari libur hanya
        jadi peringatan (`detect_conflicts`) — keputusan bisnisnya
        belum final, dan menolaknya lebih dulu berarti HR tidak bisa
        mencatat keadaan yang memang terjadi. Yang di sini berbeda:
        satu orang tidak bisa punya dua izin untuk jam yang sama, dan
        kalau dibiarkan, `permission_minutes` menjumlahkan waktu yang
        sama dua kali dan payroll memotongnya dua kali.
        """
        employee = data.get("employee")
        work_date = data.get("date")

        if employee is None or work_date is None:
            return

        shift_start, shift_end = shift_window(employee, work_date)

        candidate = build_window(
            _Draft(data),
            shift_start=shift_start,
            shift_end=shift_end,
        )

        existing = (
            AttendancePermission.objects
            .filter(
                employee=employee,
                date=work_date,
                is_deleted=False,
                status__in=PERMISSION_ACTIVE_STATUSES,
            )
            .exclude(pk=exclude_pk)
        )

        for other in existing:
            window = build_window(
                other,
                shift_start=shift_start,
                shift_end=shift_end,
            )

            if not _overlaps(candidate, window):
                continue

            raise ValidationError(
                {
                    "start_time": (
                        f"Bertabrakan dengan izin "
                        f"{other.document_number or other.pk} "
                        f"({other.get_permission_type_display()}"
                        f"{_window_label(window)}) yang masih "
                        f"{other.get_status_display().lower()}."
                    ),
                },
            )

    # ------------------------------------------------------------------
    # Konflik yang jadi peringatan, bukan penolakan
    # ------------------------------------------------------------------

    @classmethod
    def detect_conflicts(cls, permission: AttendancePermission) -> list[dict]:
        """
        Hal-hal yang membuat izin ini patut ditanyakan HR.

        Peringatan, **bukan penolakan** — dan itu keputusan tahap
        pertama yang ditulis di spesifikasinya: aturan bisnisnya belum
        final, dan menolak lebih dulu berarti keadaan yang memang
        terjadi tidak bisa dicatat. Yang dikembalikan daftar berisi
        `{code, message}`; layar menampilkannya, approver yang
        memutuskan.
        """
        from apps.administration.services.calendar_resolver import (
            CalendarResolver,
        )
        from apps.hr.api.attendance.schedule import scheduled_work_days
        from apps.hr.models import (
            EmployeeLeave,
            TravelRequest,
            TRAVEL_REQUEST_ACTIVE_STATUSES,
        )
        from apps.hr.models.leave import LEAVE_DEDUCTING_STATUSES

        employee = permission.employee
        work_date = permission.date

        conflicts: list[dict] = []

        leave = (
            EmployeeLeave.objects
            .filter(
                employee=employee,
                is_deleted=False,
                status__in=LEAVE_DEDUCTING_STATUSES,
                start_date__lte=work_date,
                end_date__gte=work_date,
            )
            .select_related("leave_type")
            .first()
        )

        if leave is not None:
            conflicts.append({
                "code": "leave",
                "message": (
                    f"Tanggal ini sudah tertutup cuti "
                    f"{leave.document_number or leave.pk} "
                    f"({getattr(leave.leave_type, 'name', '')}). "
                    "Izin kehadiran tidak diperlukan untuk hari cuti."
                ),
            })

        travel = (
            TravelRequest.objects
            .filter(
                employee=employee,
                is_deleted=False,
                status__in=TRAVEL_REQUEST_ACTIVE_STATUSES,
                start_date__lte=work_date,
                end_date__gte=work_date,
            )
            .first()
        )

        if travel is not None:
            conflicts.append({
                "code": "travel",
                "message": (
                    f"Tanggal ini masuk Travel Request "
                    f"{travel.document_number or travel.pk}."
                ),
            })

        # Hari yang memang bukan hari kerja pegawainya. Dijawab
        # `scheduled_work_days()` — resolver yang sama yang dipakai
        # penutup hari presensi, jadi libur nasional, blok off roster,
        # dan hari off kalender kerja terjawab sekaligus tanpa tiga
        # pemeriksaan terpisah yang pasti berbeda pendapat.
        if work_date not in scheduled_work_days(employee, work_date, work_date):
            is_holiday = work_date in CalendarResolver.resolve_holidays_for_employee(
                employee,
                work_date,
                work_date,
            )

            conflicts.append({
                "code": "holiday" if is_holiday else "non_working_day",
                "message": (
                    f"{work_date} "
                    + (
                        "adalah hari libur"
                        if is_holiday
                        else "bukan hari kerja pegawai ini"
                    )
                    + ". Izin pada hari libur atau blok off tidak "
                    "memaafkan apa pun — presensi hari itu memang "
                    "tidak menghasilkan pengecualian."
                ),
            })

        return conflicts

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        permission: AttendancePermission,
        user=None,
        notes: str = "",
    ):
        if permission.status in (
            AttendancePermissionStatus.SUBMITTED,
            AttendancePermissionStatus.IN_REVIEW,
        ):
            raise ValidationError(
                {"status": "Izin ini sudah diajukan."},
            )

        if permission.status == AttendancePermissionStatus.APPROVED:
            raise ValidationError(
                {"status": "Izin ini sudah disetujui."},
            )

        cls.assert_period_open(
            employee=permission.employee,
            work_date=permission.date,
        )

        workflow = WorkflowService.submit(
            document=permission,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
            employee=permission.employee,
            user=user,
            context=cls.workflow_context(permission),
            document_number=permission.document_number or "",
            document_label=cls.workflow_label(permission),
            notes=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                permission=permission,
                status=status,
                user=user,
            ),
        )

        if workflow.status == InstanceStatus.PENDING:
            cls._set_status(
                permission=permission,
                status=AttendancePermissionStatus.SUBMITTED,
                user=user,
            )

        return workflow

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        permission: AttendancePermission,
        approved: bool,
        user=None,
        notes: str = "",
    ):
        workflow = cls.workflow_for(permission)

        if workflow is None:
            raise ValidationError(
                {"status": "Izin ini tidak sedang menunggu persetujuan."},
            )

        handler = (
            WorkflowService.approve
            if approved
            else WorkflowService.reject
        )

        result = handler(
            instance=workflow,
            user=user,
            comment=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                permission=permission,
                status=status,
                user=user,
            ),
        )

        # Masih ada meja di depan = sedang ditinjau. Engine sengaja
        # tidak punya hook per-step, jadi keputusan yang diambil dari
        # kotak masuk generik membiarkan statusnya SUBMITTED sampai
        # meja terakhir — yang berbeda cuma keterbacaannya di layar.
        workflow.refresh_from_db()

        if workflow.status == InstanceStatus.PENDING:
            cls._set_status(
                permission=permission,
                status=AttendancePermissionStatus.IN_REVIEW,
                user=user,
            )

        return result

    @classmethod
    @transaction.atomic
    def cancel(
        cls,
        *,
        permission: AttendancePermission,
        user=None,
        notes: str = "",
    ):
        """
        Menarik izin, baik yang masih berjalan maupun yang sudah
        disetujui.

        Yang sudah disetujui **tidak** dikembalikan ke DRAFT: ia sudah
        pernah memaafkan sesuatu, dan mengembalikannya ke draft membuat
        dokumen yang pernah berlaku terbaca seolah tidak pernah ada.
        Yang belum disetujui kembali ke DRAFT supaya bisa diperbaiki
        dan diajukan ulang — pola yang sama dengan `withdraw` Visitor.
        """
        if permission.status == AttendancePermissionStatus.CANCELLED:
            raise ValidationError(
                {"status": "Izin ini sudah dibatalkan."},
            )

        cls.assert_period_open(
            employee=permission.employee,
            work_date=permission.date,
        )

        was_approved = (
            permission.status == AttendancePermissionStatus.APPROVED
        )

        workflow = cls.workflow_for(permission)

        if workflow is not None:
            WorkflowService.cancel(
                instance=workflow,
                user=user,
                comment=notes,
            )

        cls._set_status(
            permission=permission,
            status=(
                AttendancePermissionStatus.CANCELLED
                if was_approved
                else AttendancePermissionStatus.DRAFT
            ),
            user=user,
            notes=notes,
        )

        # Pembatalan izin yang sudah disetujui **wajib** menghitung
        # ulang presensinya. Tanpa ini barisnya tetap "dimaafkan" oleh
        # dokumen yang sudah tidak berlaku, dan tidak ada satu layar
        # pun yang menunjukkannya.
        cls.recalculate_attendance(permission=permission)

        return permission

    @classmethod
    def workflow_for(cls, permission: AttendancePermission):
        return WorkflowService.instance_for(
            document=permission,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

    @classmethod
    def on_workflow_done(cls, *, permission, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti.

        Juga dipakai handler di `apps/hr/workflow_handlers.py` — jalur
        yang dilewati kalau approver menekan tombolnya dari kotak masuk
        generik, bukan dari layar Attendance Permission.
        """
        mapping = {
            InstanceStatus.PENDING: AttendancePermissionStatus.SUBMITTED,
            InstanceStatus.APPROVED: AttendancePermissionStatus.APPROVED,
            InstanceStatus.REJECTED: AttendancePermissionStatus.REJECTED,
            # Dikembalikan untuk diperbaiki: dokumennya harus bisa
            # disunting lagi, jadi turun ke DRAFT — bukan status baru
            # yang harus dikenali seluruh layar.
            InstanceStatus.RETURNED: AttendancePermissionStatus.DRAFT,
            InstanceStatus.CANCELLED: AttendancePermissionStatus.DRAFT,
        }

        target = mapping.get(status)

        if target is None:
            return permission

        cls._set_status(permission=permission, status=target, user=user)

        # Setiap perpindahan menghitung ulang, bukan hanya APPROVED.
        # Penolakan harus **mencabut** pembebasan yang sempat terbaca
        # saat dokumennya masih berjalan, dan badge "menunggu izin"
        # harus hilang begitu keputusannya diambil.
        cls.recalculate_attendance(permission=permission)

        return permission

    @staticmethod
    def _set_status(*, permission, status, user=None, notes: str = ""):
        if permission.status == status:
            return permission

        now = timezone.now()

        stamps = {
            AttendancePermissionStatus.SUBMITTED: "submitted_at",
            AttendancePermissionStatus.APPROVED: "approved_at",
            AttendancePermissionStatus.REJECTED: "rejected_at",
            AttendancePermissionStatus.CANCELLED: "cancelled_at",
        }

        fields = ["status", "updated_by", "updated_at"]

        permission.status = status
        permission.updated_by = user

        stamp = stamps.get(status)

        if stamp is not None:
            setattr(permission, stamp, now)
            fields.append(stamp)

        if notes:
            permission.notes = (
                f"{permission.notes}\n{notes}".strip()
                if permission.notes
                else notes
            )
            fields.append("notes")

        permission.save(update_fields=fields)

        return permission

    @classmethod
    def recalculate_attendance(cls, *, permission) -> int:
        return AttendancePermissionEffectService.recalculate_for_permission(
            permission=permission,
        )

    @staticmethod
    def workflow_context(permission: AttendancePermission) -> dict:
        """Nilai yang bisa dipakai `WorkflowStep.condition`."""
        return {
            "permission_type": permission.permission_type,
            "date": permission.date.isoformat() if permission.date else None,
            "duration_minutes": permission.duration_minutes,
            "location_code": getattr(permission.location, "code", None),
            "company_code": getattr(permission.company, "code", None),
            "allow_outside_shift": permission.allow_outside_shift,
            "has_attachment": permission.supporting_document_id is not None,
        }

    @staticmethod
    def workflow_label(permission: AttendancePermission) -> str:
        return (
            f"Attendance Permission {permission.document_number or ''} — "
            f"{permission.get_permission_type_display()} "
            f"{permission.date}"
        ).strip()

    # ------------------------------------------------------------------
    # Perhitungan ulang setelah dokumen berubah lewat jalur CRUD biasa
    # ------------------------------------------------------------------

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        instance = super().after_create(instance=instance, user=user, **kwargs)

        cls.recalculate_attendance(permission=instance)

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        instance = super().after_update(instance=instance, user=user, **kwargs)

        cls.recalculate_attendance(permission=instance)

        return instance

    @classmethod
    def after_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        super().after_soft_delete(instance=instance, user=user, **kwargs)

        # Izin yang dihapus berhenti memaafkan. Tanpa baris ini,
        # baris presensinya tetap membawa `excused_late_minutes` dari
        # dokumen yang sudah tidak bisa dibuka siapa pun.
        cls.recalculate_attendance(permission=instance)


class _Draft:
    """
    Payload yang berperilaku seperti record, supaya `build_window()`
    bisa dipakai untuk dokumen yang **belum** tersimpan.

    Alternatifnya menyalin logika penambatan jam ke shift ke dalam
    validasi — dan dua salinan aturan "shift malam berakhir besok"
    adalah cara paling pelan membuat validasi dan perhitungan berbeda
    pendapat.
    """

    __slots__ = (
        "pk",
        "date",
        "permission_type",
        "start_time",
        "end_time",
        "status",
        "document_number",
    )

    def __init__(self, data: dict[str, Any]):
        self.pk = None
        self.date = data.get("date")
        self.permission_type = data.get("permission_type")
        self.start_time = data.get("start_time")
        self.end_time = data.get("end_time")
        self.status = AttendancePermissionStatus.DRAFT
        self.document_number = ""


def _overlaps(left, right) -> bool:
    """
    Dua jendela bertabrakan.

    Jendela yang salah satu ujungnya tidak diketahui **dianggap
    bertabrakan** kalau tanggalnya sama — izin sehari penuh untuk
    pegawai yang jadwalnya belum tersusun tidak punya jam, dan
    membiarkannya lolos berarti dua izin sehari penuh bisa berdiri di
    tanggal yang sama.
    """
    if left.permission_type == AttendancePermissionType.FULL_DAY:
        return True

    if right.permission_type == AttendancePermissionType.FULL_DAY:
        return True

    if None in (left.start, left.end, right.start, right.end):
        return True

    return left.start < right.end and right.start < left.end


def _window_label(window) -> str:
    if window.start is None or window.end is None:
        return ""

    return f" {window.start:%H:%M}–{window.end:%H:%M}"
