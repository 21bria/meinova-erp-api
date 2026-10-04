"""
Service Business Trip (BT-2).

Kontraknya `docs/claude/hr/business-trip.md`. Yang dipegang berkas ini:
penomoran, salinan organisasi, kelayakan pegawai, penjagaan tumpang-
tindih, alur persetujuan lewat engine yang ada, dan siklus sesudah
disetujui (berangkat, selesai, batal, pengganti, perpanjangan).

Yang **tidak** ada di sini, dan sengaja: presensi, payroll, pos jaga,
dan Visitor Request. BT-2 hanya melahirkan dokumennya.

Pembagian validasi mengikuti Attendance Permission / Visitor: yang
menyangkut satu record di `Model.clean()`, yang menyangkut baris lain
atau keadaan dokumen di sini.

**Satu jalur keputusan alur.** Pengajuan, keputusan dari layar, dan
keputusan dari kotak masuk generik sama-sama memakai handler terdaftar
(`completion_handler("hr", "business_trip")`) — pola Cuti. Temuan BT-1:
`WorkflowService.approve/reject` hanya memanggil callback yang dioper,
tanpa mencari handler sendiri; kotak masuk mengoper handler terdaftar.
Karena dokumen ini juga tidak punya status antara, kedua jalur
menghasilkan keadaan yang sama persis.
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
from apps.workflow.registry import completion_handler
from apps.workflow.services import WorkflowService

from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.models import (
    BUSINESS_TRIP_CLAIMING_STATUSES,
    BusinessTrip,
    BusinessTripDestinationType,
    BusinessTripLeg,
    BusinessTripLinkType,
    BusinessTripStatus,
    OrganizationAssignment,
)

from .overlap import (
    assert_trip_has_no_overlap,
    day_start,
    trip_dates,
    wall_date,
    wall_today,
)
from .reconcile import reconcile_attendance


logger = logging.getLogger(__name__)


CANCEL_PERMISSION = "hr.cancel_businesstrip"

# Kolom organisasi yang disalin dari `OrganizationAssignment`.
SNAPSHOT_FIELDS = (
    "company",
    "branch",
    "location",
    "division",
    "department",
    "section",
    "position",
    "cost_center",
)

# Status yang boleh dipindahkan hasil alur. Dokumen yang sudah berjalan
# lebih jauh (berangkat, selesai, batal) tidak boleh ditarik mundur oleh
# callback yang terulang — misalnya persetujuan yang diputar ulang.
_WORKFLOW_SOURCE_STATUSES = {
    BusinessTripStatus.DRAFT,
    BusinessTripStatus.REJECTED,
    BusinessTripStatus.SUBMITTED,
}


class BusinessTripService(BaseMasterService):
    model = BusinessTrip

    WORKFLOW_MODULE = "hr"
    WORKFLOW_DOCUMENT_TYPE = "business_trip"

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
        data = cls.apply_requester(data, user=user)

        cls.assert_eligible(data.get("employee"))

        data = cls.apply_snapshot(data, employee=data.get("employee"))
        data = cls.apply_destination_defaults(data)
        data.setdefault("request_date", wall_today())

        if data.get("origin_location") is None:
            data["origin_location"] = data.get("location")

        cls.assert_link(data)

        # Paling akhir: nomor yang sudah diambil tidak dikembalikan kalau
        # validasi sesudahnya gagal.
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

        employee = data.get("employee", instance.employee)

        if "employee" in data and employee.pk != instance.employee_id:
            cls.assert_eligible(employee)

        # Selama masih draf salinannya selalu mengikuti penempatan terkini;
        # yang dibekukan hanya yang sudah diajukan.
        data = cls.apply_snapshot(data, employee=employee)
        data = cls.apply_destination_defaults(data, instance=instance)

        cls.assert_link(data, instance=instance)

        return data

    @staticmethod
    def apply_employee(data: dict[str, Any], *, user=None) -> dict[str, Any]:
        """
        Pegawai dari akun yang mengetik kalau tidak disebut — jalur
        pegawai mengajukan untuk dirinya sendiri. HR yang mengetik untuk
        orang lain menyebutnya eksplisit, dan itu dijaga
        `EmployeeSubjectWriteGuardMixin` di viewset.
        """
        if data.get("employee") is not None:
            return data

        employee = getattr(user, "employee_profile", None)

        if employee is not None:
            data["employee"] = employee

        return data

    @staticmethod
    def apply_requester(data: dict[str, Any], *, user=None) -> dict[str, Any]:
        if data.get("requester") is not None:
            return data

        data["requester"] = getattr(user, "employee_profile", None)

        return data

    @staticmethod
    def current_assignment(employee):
        if employee is None:
            return None

        return (
            OrganizationAssignment.objects
            .filter(employee=employee, is_active=True, is_deleted=False)
            .order_by("-organization_effective_date", "-id")
            .first()
        )

    @classmethod
    def apply_snapshot(cls, data: dict[str, Any], *, employee) -> dict[str, Any]:
        """
        Salinan organisasi dari penempatan terkini pegawainya.

        Pola `OrganizationDenormalizationMixin`, diperluas ke delapan
        kolom. Bedanya satu dan disengaja: mixin itu hanya **mengisi yang
        kosong**, sedangkan salinan ini **selalu ditulis ulang** selama
        dokumen masih draf — kolomnya read-only di serializer, jadi tidak
        ada isian klien yang bisa tertimpa, dan draf yang disunting
        sesudah mutasi harus menunjuk unit barunya. Sesudah diajukan
        dokumen tidak bisa disunting, jadi salinannya beku.
        """
        assignment = cls.current_assignment(employee)

        for field in SNAPSHOT_FIELDS:
            data[field] = getattr(assignment, field, None)

        return data

    @staticmethod
    def apply_destination_defaults(
        data: dict[str, Any],
        *,
        instance: BusinessTrip | None = None,
    ) -> dict[str, Any]:
        """
        Mengosongkan kolom tujuan yang tidak dipakai jenisnya.

        Tanpa ini mengganti tujuan eksternal → lokasi perusahaan
        meninggalkan kota lama menempel, dan `clean()` menolak dengan
        pesan tentang kolom yang sudah disembunyikan form.
        """
        kind = data.get(
            "destination_type",
            getattr(instance, "destination_type", None),
        )

        if kind == BusinessTripDestinationType.INTERNAL_LOCATION:
            data["destination_city"] = None
            data["destination_country"] = None
        elif kind in (
            BusinessTripDestinationType.EXTERNAL_DOMESTIC,
            BusinessTripDestinationType.EXTERNAL_INTERNATIONAL,
        ):
            data["destination_location"] = None

        return data

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="business_trip",
            company=data.get("company"),
        )

        return data

    # ------------------------------------------------------------------
    # Penjagaan
    # ------------------------------------------------------------------

    @staticmethod
    def assert_eligible(employee) -> None:
        """
        Kelayakan dari Employee Group (`business_trip_applicable`).

        Diperiksa saat dibuat dan saat diajukan — **tidak** di `clean()`:
        dokumen yang sudah disetujui tetap bisa dirawat sampai selesai
        walau kebijakan group-nya berubah di tengah jalan (pola Travel
        Request / `field_break`).
        """
        if employee is None:
            return

        if is_applicable(employee, HRFeature.BUSINESS_TRIP):
            return

        group = getattr(
            getattr(employee, "employment", None),
            "employee_group",
            None,
        )

        raise ValidationError(
            {
                "employee": (
                    f"Employee Group \"{getattr(group, 'name', '-')}\" "
                    "tidak memakai Business Trip. Nyalakan Business Trip "
                    "pada master Employee Group kalau kebijakannya "
                    "berubah."
                ),
            },
        )

    @staticmethod
    def assert_editable(instance: BusinessTrip) -> None:
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Business Trip berstatus "
                    f"{instance.get_status_display()} tidak bisa "
                    "disunting. Perubahan sesudah disetujui dilakukan "
                    "lewat pembatalan + dokumen pengganti, atau dokumen "
                    "perpanjangan."
                ),
            },
        )

    @staticmethod
    def assert_link(
        data: dict[str, Any],
        *,
        instance: BusinessTrip | None = None,
    ) -> None:
        """
        Aturan `supersedes` — keterlacakan perubahan sesudah disetujui.

        * **replacement**: dokumen lamanya sudah CANCELLED (batalkan
          dulu, baru ganti) dan belum punya pengganti lain yang hidup.
        * **extension**: dokumen lamanya masih berlaku (APPROVED /
          ON_TRIP / COMPLETED) dan belum punya perpanjangan lain yang
          hidup. Tanggalnya dijaga penjagaan tumpang-tindih saat diajukan
          — perpanjangan harus mulai sesudah hari terakhir dokumen lama.
        * Keduanya milik pegawai yang sama.
        """
        original = data.get("supersedes", getattr(instance, "supersedes", None))

        if original is None:
            return

        link_type = data.get(
            "supersede_type",
            getattr(instance, "supersede_type", ""),
        )

        employee = data.get("employee", getattr(instance, "employee", None))

        errors = {}

        if employee is not None and original.employee_id != employee.pk:
            errors["supersedes"] = (
                "Dokumen yang diganti/diperpanjang harus milik pegawai "
                "yang sama."
            )

        if link_type == BusinessTripLinkType.REPLACEMENT:
            if original.status != BusinessTripStatus.CANCELLED:
                errors["supersedes"] = (
                    f"{original.document_number or original.pk} masih "
                    f"{original.get_status_display()}. Batalkan dulu "
                    "sebelum membuat penggantinya."
                )
        elif link_type == BusinessTripLinkType.EXTENSION:
            if original.status not in (
                BusinessTripStatus.APPROVED,
                BusinessTripStatus.ON_TRIP,
                BusinessTripStatus.COMPLETED,
            ):
                errors["supersedes"] = (
                    "Perpanjangan hanya untuk perjalanan yang sudah "
                    "disetujui."
                )

        if link_type and not errors:
            siblings = (
                BusinessTrip.objects
                .filter(
                    supersedes=original,
                    supersede_type=link_type,
                    is_deleted=False,
                )
                .exclude(
                    status__in=[
                        BusinessTripStatus.CANCELLED,
                        BusinessTripStatus.REJECTED,
                    ],
                )
                .exclude(pk=getattr(instance, "pk", None))
                .first()
            )

            if siblings is not None:
                errors["supersedes"] = (
                    f"{original.document_number or original.pk} sudah "
                    f"punya {BusinessTripLinkType(link_type).label.lower()} "
                    f"{siblings.document_number or siblings.pk}."
                )

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _locked(trip: BusinessTrip) -> BusinessTrip:
        """
        Baris dikunci dan keadaannya dibaca ulang.

        Dua tombol yang ditekan bersamaan sama-sama memegang instance yang
        masih berbunyi keadaan lama; tanpa ini keduanya lolos.
        """
        return (
            BusinessTrip.objects
            .select_for_update()
            .get(pk=trip.pk, is_deleted=False)
        )

    @staticmethod
    def _sync(target: BusinessTrip, source: BusinessTrip) -> BusinessTrip:
        """
        Instance milik pemanggil ikut membaca keadaan terbaru.

        Aksi bekerja pada baris terkunci (`source`); tanpa ini pemanggil
        yang memegang instance lama melihat status sebelum aksinya.
        """
        if target is not source:
            target.refresh_from_db()

        return target

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------

    @classmethod
    def handler(cls):
        return completion_handler(
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

    @classmethod
    @transaction.atomic
    def submit(cls, *, trip: BusinessTrip, user=None, notes: str = ""):
        locked = cls._locked(trip)

        if not locked.is_editable:
            raise ValidationError(
                {
                    "status": (
                        f"Business Trip berstatus "
                        f"{locked.get_status_display()} tidak bisa "
                        "diajukan."
                    ),
                },
            )

        cls.assert_eligible(locked.employee)

        # Salinan terakhir sebelum dibekukan.
        for field, value in cls.apply_snapshot(
            {},
            employee=locked.employee,
        ).items():
            setattr(locked, field, value)

        locked.full_clean()

        # Tautan diperiksa ulang: dokumen asalnya bisa saja berubah sejak
        # draf ini dibuat.
        cls.assert_link({}, instance=locked)

        assert_trip_has_no_overlap(locked)

        locked.updated_by = user
        locked.save(
            update_fields=[*SNAPSHOT_FIELDS, "updated_by", "updated_at"],
        )

        workflow = WorkflowService.submit(
            document=locked,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
            employee=locked.employee,
            user=user,
            context=cls.workflow_context(locked),
            document_number=locked.document_number or "",
            document_label=cls.workflow_label(locked),
            notes=notes,
            on_complete=cls.handler(),
        )

        locked.refresh_from_db()

        # Alur yang seluruh mejanya terlewat sudah menutup dirinya dan
        # handler menulis APPROVED. Selain itu dokumennya menunggu.
        if workflow.status == InstanceStatus.PENDING:
            cls._set_status(
                trip=locked,
                status=BusinessTripStatus.SUBMITTED,
                user=user,
            )

        cls._sync(trip, locked)

        return workflow

    @classmethod
    def workflow_for(cls, trip: BusinessTrip):
        return WorkflowService.instance_for(
            document=trip,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        trip: BusinessTrip,
        decision: str,
        user=None,
        notes: str = "",
    ):
        """
        Keputusan dari layar Business Trip: `approve`, `reject`, atau
        `return`. Hak memutuskan dijaga engine
        (`WorkflowApprovalService`), bukan di sini.
        """
        handlers = {
            "approve": WorkflowService.approve,
            "reject": WorkflowService.reject,
            "return": WorkflowService.send_back,
        }

        if decision not in handlers:
            raise ValidationError({"decision": "Keputusan tidak dikenal."})

        locked = cls._locked(trip)

        workflow = cls.workflow_for(locked)

        if workflow is None or locked.status != BusinessTripStatus.SUBMITTED:
            raise ValidationError(
                {
                    "status": (
                        "Business Trip ini tidak sedang menunggu "
                        "persetujuan."
                    ),
                },
            )

        result = handlers[decision](
            instance=workflow,
            user=user,
            comment=notes,
            on_complete=cls.handler(),
        )

        cls._sync(trip, locked)

        return result

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, trip: BusinessTrip, user=None, notes: str = ""):
        """Menarik pengajuan yang belum diputuskan, kembali ke DRAFT."""
        locked = cls._locked(trip)

        workflow = cls.workflow_for(locked)

        if workflow is None or locked.status != BusinessTripStatus.SUBMITTED:
            raise ValidationError(
                {"status": "Tidak ada pengajuan berjalan yang bisa ditarik."},
            )

        WorkflowService.cancel(
            instance=workflow,
            user=user,
            comment=notes,
        )

        cls._set_status(
            trip=locked,
            status=BusinessTripStatus.DRAFT,
            user=user,
        )

        cls._sync(trip, locked)

        return workflow

    @classmethod
    def on_workflow_done(cls, *, trip: BusinessTrip, status, user=None):
        """
        Dipanggil handler terdaftar saat alurnya berhenti — dari layar
        ini maupun dari kotak masuk generik.

        Idempoten: status yang sama tidak ditulis ulang, dan dokumen yang
        sudah melangkah lebih jauh (berangkat, selesai, batal) tidak
        ditarik mundur oleh callback yang terulang.
        """
        mapping = {
            InstanceStatus.APPROVED: BusinessTripStatus.APPROVED,
            InstanceStatus.REJECTED: BusinessTripStatus.REJECTED,
            # Dikembalikan untuk diperbaiki: harus bisa disunting lagi.
            InstanceStatus.RETURNED: BusinessTripStatus.DRAFT,
            InstanceStatus.CANCELLED: BusinessTripStatus.DRAFT,
        }

        target = mapping.get(status)

        if target is None:
            return trip

        if trip.status not in _WORKFLOW_SOURCE_STATUSES:
            logger.warning(
                "Business Trip %s berstatus %s mengabaikan hasil alur %s.",
                trip.pk,
                trip.status,
                status,
            )

            return trip

        return cls._set_status(trip=trip, status=target, user=user)

    _STAMPS = {
        BusinessTripStatus.SUBMITTED: "submitted_at",
        BusinessTripStatus.APPROVED: "approved_at",
        BusinessTripStatus.REJECTED: "rejected_at",
        BusinessTripStatus.ON_TRIP: "departed_at",
        BusinessTripStatus.COMPLETED: "completed_at",
        BusinessTripStatus.CANCELLED: "cancelled_at",
    }

    @classmethod
    def _set_status(cls, *, trip, status, user=None, extra=None):
        if trip.status == status and not extra:
            return trip

        fields = ["status", "updated_by", "updated_at"]

        trip.status = status
        trip.updated_by = user

        stamp = cls._STAMPS.get(status)

        if stamp is not None:
            setattr(trip, stamp, timezone.now())
            fields.append(stamp)

        for field, value in (extra or {}).items():
            setattr(trip, field, value)
            fields.append(field)

        trip.save(update_fields=fields)

        return trip

    @staticmethod
    def workflow_context(trip: BusinessTrip) -> dict:
        """Nilai yang bisa dipakai `WorkflowStep.condition`."""
        start, end = trip_dates(trip)

        employment = getattr(trip.employee, "employment", None)
        group = getattr(employment, "employee_group", None)

        return {
            "destination_type": trip.destination_type,
            "destination_location_id": trip.destination_location_id,
            "is_international": (
                trip.destination_type
                == BusinessTripDestinationType.EXTERNAL_INTERNATIONAL
            ),
            "duration_days": (end - start).days + 1,
            "purpose_category": trip.purpose_category,
            "employee_group_code": getattr(group, "code", None),
            "company_code": getattr(trip.company, "code", None),
            "location_code": getattr(trip.location, "code", None),
        }

    @staticmethod
    def workflow_label(trip: BusinessTrip) -> str:
        start, end = trip_dates(trip)

        return (
            f"Business Trip {trip.document_number or ''} — "
            f"{trip.employee.full_name} {start} s/d {end}"
        ).strip()

    # ------------------------------------------------------------------
    # Sesudah disetujui
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def depart(cls, *, trip: BusinessTrip, user=None, actual_departure=None):
        """
        APPROVED → ON_TRIP. Tidak sebelum tanggal berangkat — berangkat
        lebih awal adalah perubahan material, jalannya dokumen pengganti.
        """
        locked = cls._locked(trip)

        if locked.status != BusinessTripStatus.APPROVED:
            raise ValidationError(
                {
                    "status": (
                        "Hanya perjalanan yang sudah disetujui yang bisa "
                        "ditandai berangkat."
                    ),
                },
            )

        if wall_today() < wall_date(locked.departure_datetime):
            raise ValidationError(
                {
                    "status": (
                        "Tanggal berangkatnya belum tiba. Kalau jadwalnya "
                        "maju, batalkan dan buat dokumen pengganti."
                    ),
                },
            )

        cls._set_status(
            trip=locked,
            status=BusinessTripStatus.ON_TRIP,
            user=user,
            extra={
                "actual_departure_datetime": (
                    actual_departure or locked.departure_datetime
                ),
            },
        )

        return cls._sync(trip, locked)

    @classmethod
    @transaction.atomic
    def complete(cls, *, trip: BusinessTrip, user=None, actual_return=None):
        """
        ON_TRIP (atau APPROVED yang sudah lewat tanggal berangkat) →
        COMPLETED.

        `actual_return` lebih awal dari rencana = pulang lebih awal;
        rencana aslinya tetap tersimpan. Lebih lambat dari rencana
        ditolak — itu perpanjangan, dokumennya sendiri.
        """
        locked = cls._locked(trip)

        if locked.status not in (
            BusinessTripStatus.APPROVED,
            BusinessTripStatus.ON_TRIP,
        ):
            raise ValidationError(
                {
                    "status": (
                        f"Business Trip berstatus "
                        f"{locked.get_status_display()} tidak bisa "
                        "diselesaikan."
                    ),
                },
            )

        if wall_today() < wall_date(locked.departure_datetime):
            raise ValidationError(
                {"status": "Perjalanan ini belum berangkat."},
            )

        if actual_return is None:
            raise ValidationError(
                {"actual_return_datetime": "Waktu kembali wajib diisi."},
            )

        departed = locked.actual_departure_datetime or locked.departure_datetime

        if actual_return < departed:
            raise ValidationError(
                {
                    "actual_return_datetime": (
                        "Waktu kembali tidak boleh sebelum waktu berangkat."
                    ),
                },
            )

        if actual_return > locked.return_datetime:
            raise ValidationError(
                {
                    "actual_return_datetime": (
                        "Lebih lambat dari rencana. Perpanjangan dibuat "
                        "sebagai Business Trip lanjutan yang disetujui "
                        "tersendiri."
                    ),
                },
            )

        extra = {"actual_return_datetime": actual_return}

        if locked.departed_at is None:
            extra["departed_at"] = timezone.now()

        if locked.actual_departure_datetime is None:
            extra["actual_departure_datetime"] = locked.departure_datetime

        cls._set_status(
            trip=locked,
            status=BusinessTripStatus.COMPLETED,
            user=user,
            extra=extra,
        )

        # BT-3: pulang lebih awal memendekkan izinnya; baris dinas yang
        # ditulis penutup hari untuk tanggal sesudahnya dicabut.
        reconcile_attendance(locked, user=user)

        return cls._sync(trip, locked)

    @classmethod
    def may_cancel(cls, *, trip: BusinessTrip, user) -> bool:
        """
        Pegawainya sendiri (atau yang mengetikkannya) boleh membatalkan
        perjalanan yang disetujui **sebelum tanggal berangkat**. Selebihnya
        — perjalanan orang lain, atau yang sudah berangkat — menuntut
        `hr.cancel_businesstrip`.
        """
        if user is None:
            return False

        if getattr(user, "is_superuser", False) or user.has_perm(
            CANCEL_PERMISSION,
        ):
            return True

        if trip.status != BusinessTripStatus.APPROVED:
            return False

        if wall_today() >= wall_date(trip.departure_datetime):
            return False

        mine = getattr(user, "employee_profile", None)

        return mine is not None and mine.pk in (
            trip.employee_id,
            trip.requester_id,
        )

    @classmethod
    @transaction.atomic
    def cancel(cls, *, trip: BusinessTrip, user=None, reason: str = ""):
        locked = cls._locked(trip)

        if locked.status == BusinessTripStatus.CANCELLED:
            raise ValidationError(
                {"status": "Business Trip ini sudah dibatalkan."},
            )

        if locked.status not in (
            BusinessTripStatus.APPROVED,
            BusinessTripStatus.ON_TRIP,
        ):
            raise ValidationError(
                {
                    "status": (
                        f"Business Trip berstatus "
                        f"{locked.get_status_display()} tidak dibatalkan — "
                        "draf dihapus, pengajuan yang berjalan ditarik "
                        "(Withdraw)."
                    ),
                },
            )

        if not (reason or "").strip():
            raise ValidationError(
                {"cancellation_reason": "Alasan pembatalan wajib diisi."},
            )

        if not cls.may_cancel(trip=locked, user=user):
            raise ValidationError(
                {
                    "status": (
                        "Perjalanan yang sudah berangkat, atau milik "
                        "pegawai lain, hanya bisa dibatalkan pemegang "
                        "kewenangan pembatalan Business Trip."
                    ),
                },
            )

        cls._set_status(
            trip=locked,
            status=BusinessTripStatus.CANCELLED,
            user=user,
            extra={
                "cancelled_by": user,
                "cancellation_reason": reason.strip(),
            },
        )

        # BT-3: hari sesudah tanggal pembatalan tidak lagi diizinkan.
        # Ditolak (dan pembatalannya ikut batal) kalau menyentuh periode
        # payroll yang sudah dikunci.
        reconcile_attendance(locked, user=user)

        return cls._sync(trip, locked)

    @classmethod
    @transaction.atomic
    def advance_departed(cls, *, today=None) -> int:
        """
        APPROVED yang tanggal berangkatnya sudah tiba → ON_TRIP.

        Kosmetik untuk layar daftar; cakupan presensi (BT-3) tidak
        menunggu status ini. Satu UPDATE bersyarat, jadi aman diulang.
        """
        from datetime import timedelta

        today = today or wall_today()
        now = timezone.now()

        rows = (
            BusinessTrip.objects
            .filter(
                is_deleted=False,
                status=BusinessTripStatus.APPROVED,
                departure_datetime__lt=day_start(today + timedelta(days=1)),
            )
        )

        count = 0

        for trip in rows.select_for_update(skip_locked=True):
            trip.status = BusinessTripStatus.ON_TRIP
            trip.departed_at = now

            if trip.actual_departure_datetime is None:
                trip.actual_departure_datetime = trip.departure_datetime

            trip.save(
                update_fields=[
                    "status",
                    "departed_at",
                    "actual_departure_datetime",
                    "updated_at",
                ],
            )

            count += 1

        return count

    # ------------------------------------------------------------------
    # Penghapusan
    # ------------------------------------------------------------------

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        """
        Hanya draf yang boleh dihapus. Dokumen yang pernah diajukan
        adalah jejak — yang disetujui dibatalkan, bukan dihapus.
        """
        super().before_soft_delete(instance=instance, user=user, **kwargs)

        if instance.status != BusinessTripStatus.DRAFT:
            raise ValidationError(
                {
                    "status": (
                        f"Business Trip berstatus "
                        f"{instance.get_status_display()} tidak bisa "
                        "dihapus."
                    ),
                },
            )


class BusinessTripLegService(BaseMasterService):
    """
    Ruas perjalanan. Hanya selama dokumen induknya masih bisa disunting —
    ruas tidak boleh menjadi pintu belakang untuk mengubah dokumen yang
    sudah disetujui.
    """

    model = BusinessTripLeg

    @staticmethod
    def assert_trip_editable(trip) -> None:
        if trip is None or trip.is_editable:
            return

        raise ValidationError(
            {
                "trip": (
                    f"Business Trip {trip.document_number or trip.pk} "
                    f"berstatus {trip.get_status_display()}; ruasnya "
                    "tidak bisa diubah lagi."
                ),
            },
        )

    @classmethod
    def prepare_create_data(cls, *, data, user=None, **kwargs):
        cls.assert_trip_editable(data.get("trip"))

        return data

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        cls.assert_trip_editable(instance.trip)

        if "trip" in data and data["trip"].pk != instance.trip_id:
            raise ValidationError(
                {"trip": "Ruas tidak bisa dipindah ke dokumen lain."},
            )

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        super().before_soft_delete(instance=instance, user=user, **kwargs)

        cls.assert_trip_editable(instance.trip)


__all__ = [
    "BusinessTripService",
    "BusinessTripLegService",
    "BUSINESS_TRIP_CLAIMING_STATUSES",
]
