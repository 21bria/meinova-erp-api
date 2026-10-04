"""
Employee Action — pembuatan dokumen, pengajuan, dan penerapannya.

Pola persis `TravelRequestService`: dokumen dibuat, diajukan lewat
engine `apps/workflow` yang generik, dan modulnya sendiri yang
memindahkan status miliknya lewat callback. Tidak ada mesin persetujuan
kedua di sini.

Yang khas modul ini adalah `apply()` — satu-satunya tempat data pegawai
benar-benar berubah. Tiga hal yang menjaganya:

* **Idempotent.** `applied_at` yang jadi penjaga, bukan status. Action
  yang sudah diterapkan tidak pernah menyentuh pegawainya untuk kedua
  kalinya, walau tombolnya ditekan lagi atau alurnya diselesaikan ulang.
* **Atomic.** Perubahan employment, organisasi, dan payroll dalam satu
  `transaction.atomic` — pegawai yang jabatannya sudah naik tapi gajinya
  belum adalah keadaan yang tidak bisa dijelaskan siapa pun.
* **Ditolak berarti tidak berubah.** REJECTED/CANCELLED tidak pernah
  memanggil `apply()` sama sekali.
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
from apps.hr.api.employee.services.employment_service import (
    EmploymentService,
)
from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.models import (
    ACTION_OPEN_STATUSES,
    EmployeeAction,
    EmployeeActionStatus,
    EmployeeActionType,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.workflow.models import InstanceStatus
from apps.workflow.services import WorkflowService

from .policy import EmployeeActionPolicyResolver


logger = logging.getLogger(__name__)


class EmployeeActionService(
    OrganizationDenormalizationMixin,
    BaseMasterService,
):
    model = EmployeeAction

    WORKFLOW_MODULE = "hr"
    WORKFLOW_DOCUMENT_TYPE = "employee_action"

    # ------------------------------------------------------------------
    # Create / update
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_organization(data)
        data = cls.apply_document_number(data)

        cls.assert_no_open_duplicate(
            employee=data.get("employee"),
            action_type=data.get("action_type"),
        )

        # Diperiksa **sebelum** pengusul default diisikan.
        #
        # Terbalik, dan pesannya jadi menyesatkan: kolom yang kosong
        # telanjur diisi nama orang yang mengetik, jadi penolakannya
        # berbunyi "Hesti bukan Kepala Departemen" — benar, tapi tidak
        # memberi tahu bahwa yang perlu dilakukan adalah mengisi
        # Requested By dengan nama kepala departemennya.
        cls.assert_initiator_allowed(
            employee=data.get("employee"),
            action_type=data.get("action_type"),
            requested_by=data.get("requested_by"),
            user=user,
        )

        return cls.apply_requested_by(data, user=user)

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

        # Status dan jejak penerapan tidak pernah datang dari form —
        # kalau ikut diterima, satu PATCH cukup untuk menandai dokumen
        # sebagai sudah diterapkan tanpa satu pun data pegawai berubah.
        for field_name in (
            "status",
            "applied_at",
            "applied_by",
            "values_before",
            "values_after",
            "apply_error",
            "document_number",
        ):
            data.pop(field_name, None)

        data = cls.apply_organization(
            data,
            fallback_employee=instance.employee,
        )

        cls.assert_initiator_allowed(
            employee=data.get("employee", instance.employee),
            action_type=data.get("action_type", instance.action_type),
            requested_by=data.get("requested_by", instance.requested_by),
            user=user,
        )

        return data

    @staticmethod
    def apply_requested_by(data: dict[str, Any], *, user=None) -> dict:
        """
        Pengusul default = yang mengetik, kalau ia memang pegawai.

        Diisikan di sini dan bukan dibiarkan kosong supaya dokumen
        selalu bisa menjawab "siapa yang mengusulkan ini" — termasuk
        untuk jenis yang tidak diatur policy apa pun. `created_by`
        menjawab pertanyaan yang berbeda: siapa yang mengetik.
        """
        if data.get("requested_by") is not None:
            return data

        employee = getattr(user, "employee_profile", None) or getattr(
            user, "employee", None,
        )

        if employee is not None:
            data["requested_by"] = employee

        return data

    @staticmethod
    def actor_employee(user):
        """Pegawai milik akun ini, kalau akunnya memang pegawai."""
        if user is None:
            return None

        from apps.hr.models import Employee

        return (
            Employee.objects
            .filter(user=user, is_deleted=False)
            .select_related("organization", "employment")
            .first()
        )

    @classmethod
    def assert_initiator_allowed(
        cls,
        *,
        employee,
        action_type,
        requested_by=None,
        user=None,
    ) -> None:
        """
        Menegakkan `EmployeeActionPolicy`.

        Dipanggil saat dibuat **dan** saat diajukan. Menunggu sampai
        Submit saja berarti HR baru tahu usulannya tidak sah setelah
        seluruh isinya diketik; memeriksa saat create saja berarti
        jenis action yang diganti selagi draft lolos tanpa diperiksa
        ulang.

        Superuser dilewati — sama seperti di engine workflow, satu
        master yang belum diseed tidak boleh mengunci orang yang
        menyiapkan sistem.
        """
        if employee is None or not action_type:
            return

        if getattr(user, "is_superuser", False):
            return

        verdict = EmployeeActionPolicyResolver.check(
            employee=employee,
            action_type=str(action_type),
            actor_employee=cls.actor_employee(user),
            requested_by=requested_by,
            actor_user=user,
        )

        if verdict.allowed:
            return

        raise ValidationError(
            {
                (
                    "requested_by"
                    if verdict.requires_requested_by
                    else "action_type"
                ): verdict.reason,
            },
        )

    @staticmethod
    def assert_editable(instance: EmployeeAction) -> None:
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Dokumen berstatus "
                    f"{instance.get_status_display()} tidak bisa "
                    "disunting. Tarik dulu pengajuannya, atau buat "
                    "dokumen baru."
                ),
            },
        )

    @classmethod
    def assert_no_open_duplicate(
        cls,
        *,
        employee,
        action_type,
        exclude_pk=None,
    ) -> None:
        """
        Menolak dua dokumen terbuka untuk pegawai dan jenis yang sama.

        Dua perpanjangan kontrak yang berjalan bersamaan akan
        diterapkan dua kali berturut-turut, dan yang belakangan menimpa
        yang duluan tanpa ada yang menyadari — dua-duanya "disetujui"
        dan dua-duanya terlihat benar.
        """
        if employee is None or not action_type:
            return

        queryset = (
            EmployeeAction.objects
            .filter(
                employee=employee,
                action_type=action_type,
                status__in=ACTION_OPEN_STATUSES,
                is_deleted=False,
            )
        )

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        existing = queryset.first()

        if existing is None:
            return

        raise ValidationError(
            {
                "action_type": (
                    f"{existing.get_action_type_display()} untuk "
                    f"{employee.full_name} sudah ada dan belum selesai "
                    f"({existing.document_number or f'#{existing.pk}'}, "
                    f"{existing.get_status_display()}). Selesaikan atau "
                    "batalkan dokumen itu dulu."
                ),
            },
        )

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        """
        Nomor dokumen dari deret `hr/employee_action`.

        Deret yang belum diseed menghasilkan nomor kosong dan
        dokumennya tetap tersimpan — perubahan kepegawaian tidak boleh
        gagal dicatat gara-gara master penomoran belum diisi. Nomor
        hanya dialokasikan saat create dan tidak pernah dihitung ulang:
        yang sudah dirujuk di surat harus tetap menunjuk dokumen yang
        sama.
        """
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="employee_action",
            company=data.get("company"),
        ) or ""

        return data

    # ------------------------------------------------------------------
    # Pengajuan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        instance: EmployeeAction,
        user=None,
        notes: str = "",
    ):
        cls.assert_submittable(instance)

        # Diperiksa ulang di sini, bukan hanya saat dibuat: jenis
        # action dan pengusulnya boleh diubah selagi draft, dan yang
        # menentukan sah-tidaknya adalah isinya saat diajukan.
        cls.assert_initiator_allowed(
            employee=instance.employee,
            action_type=instance.action_type,
            requested_by=instance.requested_by,
            user=user,
        )

        workflow = WorkflowService.submit(
            document=instance,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
            employee=instance.employee,
            user=user,
            context=cls.workflow_context(instance),
            document_number=instance.document_number or "",
            document_label=cls.workflow_label(instance),
            notes=notes,
            # Pengusul tidak diminta menyetujui usulannya sendiri.
            # Barisnya tetap dicetak — kotak tanda tangan atasan wajib
            # ada di dokumen tercetak — cuma ditandai SKIPPED dengan
            # keterangan bahwa dialah yang mengajukan.
            initiator_employee=instance.requested_by,
            on_complete=lambda wf, status: cls.on_workflow_done(
                instance=instance,
                status=status,
                user=user,
            ),
        )

        if workflow.status == InstanceStatus.PENDING:
            cls.set_status(
                instance=instance,
                status=EmployeeActionStatus.SUBMITTED,
                user=user,
            )

        return workflow

    @classmethod
    def assert_submittable(cls, instance: EmployeeAction) -> None:
        """
        Memeriksa isinya terhadap keadaan pegawai **saat diajukan**.

        Sengaja di sini, bukan saat diterapkan di ujung alur: kalau
        menunggu sampai meja terakhir, kegagalannya membatalkan
        persetujuan yang sah dan muncul di layar orang yang tidak bisa
        memperbaikinya. Yang harus mengubah tanggalnya adalah pengaju,
        dan di titik itu dokumennya sudah tidak di tangannya lagi. Pola
        yang sama dengan `TravelRequestService.assert_no_leave_conflict`.
        """
        if instance.status not in {
            EmployeeActionStatus.DRAFT,
            EmployeeActionStatus.REJECTED,
        }:
            raise ValidationError(
                {
                    "status": (
                        "Hanya dokumen Draft atau Rejected yang bisa "
                        "diajukan."
                    ),
                },
            )

        employment = cls.employment_of(instance.employee)

        cls.assert_no_open_duplicate(
            employee=instance.employee,
            action_type=instance.action_type,
            exclude_pk=instance.pk,
        )

        errors = {}

        action_type = instance.action_type

        # ---------------------------------------------------------
        # Perpanjangan kontrak
        # ---------------------------------------------------------

        if action_type == EmployeeActionType.CONTRACT_EXTENSION:
            if employment is None or not employment.contract_end:
                errors["proposed_contract_end"] = (
                    "Pegawai ini tidak sedang berkontrak — tidak ada "
                    "masa kontrak yang bisa diperpanjang. Pakai "
                    "Contract Change kalau memang mau menerbitkan "
                    "kontrak baru."
                )

            elif (
                instance.proposed_contract_end
                and instance.proposed_contract_end <= employment.contract_end
            ):
                errors["proposed_contract_end"] = (
                    "Contract End usulan "
                    f"({instance.proposed_contract_end:%d/%m/%Y}) harus "
                    "lebih lambat dari kontrak berjalan "
                    f"({employment.contract_end:%d/%m/%Y}). Untuk "
                    "memperpendek masa kontrak, pakai Contract Change."
                )

        # ---------------------------------------------------------
        # Kontrak baru
        # ---------------------------------------------------------

        if action_type == EmployeeActionType.CONTRACT_CHANGE:
            employment_type = (
                instance.proposed_employment_type
                or getattr(employment, "employment_type", None)
            )

            if (
                employment_type is not None
                and not employment_type.requires_contract
            ):
                errors["proposed_contract_type"] = (
                    f"{employment_type.name} tidak memakai masa "
                    "kontrak. Ubah dulu jenis kepegawaiannya lewat "
                    "Employment Type Change."
                )

        # ---------------------------------------------------------
        # Perubahan jenis kepegawaian
        # ---------------------------------------------------------

        if action_type == EmployeeActionType.EMPLOYMENT_TYPE_CHANGE:
            current_type = getattr(employment, "employment_type", None)

            if (
                current_type is not None
                and instance.proposed_employment_type_id == current_type.pk
            ):
                errors["proposed_employment_type"] = (
                    f"Pegawai ini sudah {current_type.name}. Tidak ada "
                    "yang berubah."
                )

        # ---------------------------------------------------------
        # Perubahan status
        # ---------------------------------------------------------

        if action_type == EmployeeActionType.STATUS_CHANGE:
            current_status = getattr(employment, "employment_status", None)

            if (
                current_status is not None
                and instance.proposed_employment_status_id == current_status.pk
            ):
                errors["proposed_employment_status"] = (
                    f"Status pegawai ini sudah {current_status.name}."
                )

        # ---------------------------------------------------------
        # Perubahan jabatan
        # ---------------------------------------------------------

        if action_type in {
            EmployeeActionType.PROMOTION,
            EmployeeActionType.DEMOTION,
            EmployeeActionType.POSITION_CHANGE,
        }:
            organization = getattr(instance.employee, "organization", None)
            current_position = getattr(organization, "position", None)

            if (
                current_position is not None
                and instance.proposed_position_id == current_position.pk
            ):
                errors["proposed_position"] = (
                    f"Pegawai ini sudah menjabat {current_position.name}."
                )

        # ---------------------------------------------------------
        # Perubahan gaji
        # ---------------------------------------------------------

        if action_type == EmployeeActionType.SALARY_CHANGE:
            payroll = cls.payroll_of(instance.employee)

            if payroll is None and not instance.proposed_payroll_group_id:
                errors["proposed_payroll_group"] = (
                    "Pegawai ini belum punya Payroll Assignment, jadi "
                    "Payroll Group wajib diisi — baris payroll tidak "
                    "bisa dibuat tanpa grup."
                )

        if errors:
            raise ValidationError(errors)

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        instance: EmployeeAction,
        approved: bool,
        user=None,
        notes: str = "",
    ):
        workflow = cls.workflow_for(instance)

        if workflow is None:
            raise ValidationError(
                {
                    "status": (
                        "Dokumen ini tidak sedang menunggu persetujuan."
                    ),
                },
            )

        handler = (
            WorkflowService.approve
            if approved
            else WorkflowService.reject
        )

        return handler(
            instance=workflow,
            user=user,
            comment=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                instance=instance,
                status=status,
                user=user,
            ),
        )

    @classmethod
    @transaction.atomic
    def withdraw(
        cls,
        *,
        instance: EmployeeAction,
        user=None,
        notes: str = "",
    ):
        if instance.is_applied:
            raise ValidationError(
                {
                    "status": (
                        "Perubahannya sudah diterapkan ke data pegawai "
                        "dan tidak bisa ditarik. Buat action kebalikan "
                        "kalau memang harus dikembalikan."
                    ),
                },
            )

        workflow = cls.workflow_for(instance)

        if workflow is None:
            raise ValidationError(
                {"status": "Tidak ada pengajuan yang bisa ditarik."},
            )

        WorkflowService.cancel(
            instance=workflow,
            user=user,
            comment=notes,
        )

        cls.set_status(
            instance=instance,
            status=EmployeeActionStatus.DRAFT,
            user=user,
        )

        return workflow

    @classmethod
    def workflow_for(cls, instance: EmployeeAction):
        return WorkflowService.instance_for(
            document=instance,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

    @classmethod
    def on_workflow_done(cls, *, instance, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti.

        Juga dipakai handler di `apps/hr/workflow_handlers.py` — jalur
        yang dilewati kalau approver menekan tombolnya dari kotak masuk
        generik, bukan dari layar Employee Action.
        """
        mapping = {
            InstanceStatus.PENDING: EmployeeActionStatus.SUBMITTED,
            InstanceStatus.APPROVED: EmployeeActionStatus.APPROVED,
            InstanceStatus.REJECTED: EmployeeActionStatus.REJECTED,
            # Dikembalikan untuk diperbaiki: harus bisa disunting lagi.
            InstanceStatus.RETURNED: EmployeeActionStatus.DRAFT,
            InstanceStatus.CANCELLED: EmployeeActionStatus.DRAFT,
        }

        target = mapping.get(status)

        if target is not None:
            cls.set_status(
                instance=instance,
                status=target,
                user=user,
            )

        # Ditolak atau dibatalkan tidak pernah menyentuh data pegawai.
        if status != InstanceStatus.APPROVED:
            return instance

        try:
            cls.apply(instance=instance, user=user)

        except Exception as error:  # noqa: BLE001
            # Sengaja tidak dilempar ulang. Alurnya sudah selesai dan
            # keputusan approver-nya sah; menggagalkan transaksi di sini
            # membatalkan persetujuan itu dan menampilkan error pada
            # orang yang tidak bisa memperbaikinya. Kegagalannya
            # ditempelkan ke dokumennya sendiri supaya HR yang membuka
            # dokumen melihatnya, lalu bisa mengulang lewat
            # `POST .../apply/`.
            logger.exception(
                "Employee Action %s disetujui tapi gagal diterapkan.",
                instance.pk,
            )

            cls.record_apply_error(instance=instance, error=error)

        return instance

    @staticmethod
    def record_apply_error(*, instance: EmployeeAction, error) -> None:
        message = getattr(error, "message_dict", None) or str(error)

        EmployeeAction.objects.filter(pk=instance.pk).update(
            apply_error=str(message),
            updated_at=timezone.now(),
        )

        instance.apply_error = str(message)

    @staticmethod
    def set_status(*, instance: EmployeeAction, status, user=None):
        if instance.status == status:
            return instance

        instance.status = status
        instance.updated_by = user

        instance.save(
            update_fields=["status", "updated_by", "updated_at"],
        )

        return instance

    @staticmethod
    def workflow_context(instance: EmployeeAction) -> dict:
        """
        Nilai yang bisa dipakai `WorkflowStep.condition`.

        `action_type` yang paling penting: dari situ satu definisi alur
        bisa menambahkan meja HR Manager khusus untuk kenaikan gaji dan
        pengangkatan, tanpa membuat definisi terpisah per jenis.
        """
        return {
            "action_type": instance.action_type,
            "document_number": instance.document_number or "",
            "effective_date": (
                instance.effective_date.isoformat()
                if instance.effective_date
                else None
            ),
            "employee_number": instance.employee.employee_number,
            "location_code": getattr(instance.location, "code", None),
            "proposed_basic_salary": (
                float(instance.proposed_basic_salary)
                if instance.proposed_basic_salary is not None
                else None
            ),
        }

    @staticmethod
    def workflow_label(instance: EmployeeAction) -> str:
        return (
            f"{instance.get_action_type_display()} "
            f"{instance.document_number or ''} — "
            f"{instance.employee.full_name}"
        ).strip()

    # ------------------------------------------------------------------
    # Pembacaan keadaan sekarang
    # ------------------------------------------------------------------

    @staticmethod
    def employment_of(employee) -> EmploymentAssignment | None:
        return (
            EmploymentAssignment.objects
            .select_related(
                "employment_type",
                "employment_status",
                "employee_group",
                "contract_type",
                "probation_type",
            )
            .filter(employee=employee, is_deleted=False)
            .first()
        )

    @staticmethod
    def payroll_of(employee) -> PayrollAssignment | None:
        return (
            PayrollAssignment.objects
            .select_related("payroll_group", "salary_grade", "salary_level")
            .filter(
                employee=employee,
                is_current=True,
                is_deleted=False,
            )
            .first()
        )

    @classmethod
    def snapshot(cls, instance: EmployeeAction) -> dict:
        """
        Nilai yang tersentuh action ini, dibekukan apa adanya.

        Disimpan sebagai teks siap baca, bukan sebagai pk: riwayat harus
        tetap terbaca bertahun-tahun kemudian walau baris masternya
        sudah dihapus atau diganti nama. Itu justru gunanya membekukan.
        """
        employment = cls.employment_of(instance.employee)
        organization = getattr(instance.employee, "organization", None)
        payroll = cls.payroll_of(instance.employee)

        def name(source, field_name):
            value = getattr(source, field_name, None)

            return getattr(value, "name", None)

        def iso(source, field_name):
            value = getattr(source, field_name, None)

            return value.isoformat() if value else None

        return {
            "employment_type": name(employment, "employment_type"),
            "employment_status": name(employment, "employment_status"),
            "employee_group": name(employment, "employee_group"),
            "contract_type": name(employment, "contract_type"),
            "contract_start": iso(employment, "contract_start"),
            "contract_end": iso(employment, "contract_end"),
            "probation_type": name(employment, "probation_type"),
            "probation_start": iso(employment, "probation_start"),
            "probation_end": iso(employment, "probation_end"),
            "confirmation_date": iso(employment, "confirmation_date"),
            "termination_date": iso(employment, "termination_date"),
            "termination_reason": name(employment, "termination_reason"),

            "company": name(organization, "company"),
            "branch": name(organization, "branch"),
            "location": name(organization, "location"),
            "division": name(organization, "division"),
            "department": name(organization, "department"),
            "section": name(organization, "section"),
            "position": name(organization, "position"),
            "job_level": name(organization, "job_level"),
            "job_grade": name(organization, "job_grade"),
            "cost_center": name(organization, "cost_center"),
            "reports_to": (
                organization.reports_to.full_name
                if organization is not None
                and organization.reports_to_id
                else None
            ),

            "payroll_group": name(payroll, "payroll_group"),
            "salary_grade": name(payroll, "salary_grade"),
            "salary_level": name(payroll, "salary_level"),
            "basic_salary": (
                str(payroll.basic_salary)
                if payroll is not None
                and payroll.basic_salary is not None
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Penerapan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def apply(cls, *, instance: EmployeeAction, user=None) -> EmployeeAction:
        """
        Menulis perubahannya ke data pegawai. Sekali, dan hanya sekali.

        Dikunci `select_for_update` lalu diperiksa ulang dari database:
        dua permintaan yang datang bersamaan (approver menekan tombol
        dua kali, atau tombol Apply manual bersamaan dengan callback
        alur) akan sama-sama membaca `applied_at` kosong kalau
        pemeriksaannya memakai instance yang sudah di tangan.
        """
        locked = (
            EmployeeAction.objects
            .select_for_update()
            .select_related("employee")
            .get(pk=instance.pk)
        )

        if locked.is_applied:
            return locked

        if locked.status not in {
            EmployeeActionStatus.APPROVED,
            EmployeeActionStatus.APPLIED,
        }:
            raise ValidationError(
                {
                    "status": (
                        "Hanya dokumen yang sudah disetujui yang bisa "
                        "diterapkan."
                    ),
                },
            )

        before = cls.snapshot(locked)

        # Dipetakan ke **nama method**, bukan ke fungsinya langsung:
        # di dalam badan class, `_apply_x` masih berupa objek
        # `classmethod` yang tidak bisa dipanggil, dan kegagalannya baru
        # muncul saat action pertama diterapkan.
        handler_name = cls.HANDLERS.get(locked.action_type)

        if handler_name is None:
            raise ValidationError(
                {
                    "action_type": (
                        f"Belum ada penerapan untuk "
                        f"{locked.get_action_type_display()}."
                    ),
                },
            )

        getattr(cls, handler_name)(locked, user)

        after = cls.snapshot(locked)

        locked.values_before = before
        locked.values_after = after
        locked.applied_at = timezone.now()
        locked.applied_by = user
        locked.status = EmployeeActionStatus.APPLIED
        locked.apply_error = ""
        locked.updated_by = user

        locked.save(
            update_fields=[
                "values_before",
                "values_after",
                "applied_at",
                "applied_by",
                "status",
                "apply_error",
                "updated_by",
                "updated_at",
            ],
        )

        return locked

    # ------------------------------------------------------------------
    # Penerapan per jenis
    # ------------------------------------------------------------------

    @classmethod
    def _write_employment(cls, action: EmployeeAction, user, changes: dict):
        """
        Menulis ke `EmploymentAssignment` lewat service-nya sendiri.

        `via_action=True` melewati penjagaan kolom terkunci — dan ini
        satu-satunya pemanggil yang boleh memakainya. Nilai lamanya
        sudah dibekukan di `values_before` dan persetujuannya sudah ada,
        jadi tidak ada yang hilang tanpa jejak.
        """
        EmploymentService.save(
            employee=action.employee,
            data={
                **changes,
                "employment_effective_date": action.effective_date,
            },
            user=user,
            via_action=True,
        )

    @classmethod
    def _apply_contract_extension(cls, action: EmployeeAction, user):
        employment = cls.employment_of(action.employee)

        changes = {
            "contract_end": action.proposed_contract_end,
        }

        # Perpanjangan mempertahankan tanggal mulai kontrak berjalan
        # kalau usulannya tidak menyebutkan yang lain — yang berubah
        # memang cuma ujungnya.
        if action.proposed_contract_start:
            changes["contract_start"] = action.proposed_contract_start

        elif employment is not None and employment.contract_start:
            changes["contract_start"] = employment.contract_start

        if action.proposed_contract_type_id:
            changes["contract_type"] = action.proposed_contract_type

        cls._write_employment(action, user, changes)

    @classmethod
    def _apply_contract_change(cls, action: EmployeeAction, user):
        cls._write_employment(
            action,
            user,
            {
                "contract_type": action.proposed_contract_type,
                "contract_start": action.proposed_contract_start,
                "contract_end": action.proposed_contract_end,
            },
        )

    @classmethod
    def _apply_employment_type_change(cls, action: EmployeeAction, user):
        changes = {
            "employment_type": action.proposed_employment_type,
        }

        if action.proposed_employee_group_id:
            changes["employee_group"] = action.proposed_employee_group

        if action.confirmation_date:
            changes["confirmation_date"] = action.confirmation_date

        # Jenis yang tidak berkontrak tidak boleh mewarisi masa kontrak
        # dari jenis sebelumnya. Ini inti dari "Contract → Permanent":
        # kontrak PKWT-nya berpindah ke riwayat (`values_before` dokumen
        # ini), dan kolom keadaan sekarang dibersihkan. Tanpa
        # pembersihan ini, pegawai permanen tetap terlihat punya kontrak
        # berjalan yang akan habis — dan `EmploymentAssignment.clean()`
        # menolak menyimpannya.
        if (
            action.proposed_employment_type_id
            and not action.proposed_employment_type.requires_contract
        ):
            changes["contract_type"] = None
            changes["contract_start"] = None
            changes["contract_end"] = None

        cls._write_employment(action, user, changes)

    @classmethod
    def _apply_probation_change(cls, action: EmployeeAction, user):
        cls._write_employment(
            action,
            user,
            {
                "probation_type": action.proposed_probation_type,
                # Mengakhiri masa percobaan berarti tanggalnya ikut
                # dibersihkan — `EmploymentAssignment.clean()` menolak
                # tanggal probation tanpa jenisnya.
                "probation_start": (
                    action.proposed_probation_start
                    if action.proposed_probation_type_id
                    else None
                ),
                "probation_end": (
                    action.proposed_probation_end
                    if action.proposed_probation_type_id
                    else None
                ),
            },
        )

    @classmethod
    def _apply_status_change(cls, action: EmployeeAction, user):
        cls._write_employment(
            action,
            user,
            {"employment_status": action.proposed_employment_status},
        )

    @classmethod
    def _apply_organization(cls, action: EmployeeAction, user):
        """
        Menulis penempatan baru ke `OrganizationAssignment`.

        Kolom yang tidak diusulkan **tidak** ikut dikosongkan: promosi
        yang cuma menyebut jabatan tidak boleh menghapus department dan
        cost center pegawainya. Nilai lamanya sudah dibekukan di
        `values_before`, jadi jejak "dari mana ke mana"-nya tetap ada
        walau assignment-nya sendiri cuma menyimpan keadaan sekarang.
        """
        assignment = (
            OrganizationAssignment.objects
            .select_for_update()
            .filter(employee=action.employee)
            .first()
        )

        if assignment is None:
            raise ValidationError(
                {
                    "employee": (
                        "Pegawai ini belum punya penempatan organisasi, "
                        "jadi tidak ada yang bisa dipindahkan. Isi dulu "
                        "tab Organization."
                    ),
                },
            )

        fields = [
            "company",
            "branch",
            "location",
            "division",
            "department",
            "section",
            "position",
            "job_level",
            "job_grade",
            "cost_center",
            "reports_to",
        ]

        for field_name in fields:
            proposed = getattr(action, f"proposed_{field_name}_id", None)

            if proposed is None:
                continue

            setattr(
                assignment,
                f"{field_name}_id",
                proposed,
            )

        assignment.organization_effective_date = action.effective_date
        assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

    @classmethod
    def _apply_salary_change(cls, action: EmployeeAction, user):
        """
        Menerbitkan baris payroll baru, bukan menimpa yang lama.

        `PayrollAssignment` memang sudah effective-dated (`is_current` +
        `effective_from`), jadi riwayat gaji sudah punya tempatnya
        sendiri — menimpa baris berjalan akan membuang satu-satunya
        catatan berapa gaji orang ini sebelum naik.
        """
        current = cls.payroll_of(action.employee)

        payroll_group = (
            action.proposed_payroll_group
            or getattr(current, "payroll_group", None)
        )

        if payroll_group is None:
            raise ValidationError(
                {
                    "proposed_payroll_group": (
                        "Payroll Group wajib diisi — baris payroll "
                        "tidak bisa dibuat tanpa grup."
                    ),
                },
            )

        currency = getattr(current, "currency", None)

        if currency is None:
            from apps.administration.models import Currency

            currency = (
                Currency.objects
                .filter(is_base_currency=True, is_deleted=False)
                .first()
            )

        if currency is None:
            raise ValidationError(
                {
                    "proposed_basic_salary": (
                        "Belum ada mata uang dasar di master Currency, "
                        "jadi baris payroll tidak bisa dibuat."
                    ),
                },
            )

        new_row = PayrollAssignment(
            employee=action.employee,
            payroll_group=payroll_group,
            salary_grade=(
                action.proposed_salary_grade
                or getattr(current, "salary_grade", None)
            ),
            salary_level=(
                action.proposed_salary_level
                or getattr(current, "salary_level", None)
            ),
            currency=currency,
            basic_salary=(
                action.proposed_basic_salary
                if action.proposed_basic_salary is not None
                else getattr(current, "basic_salary", None)
            ),
            effective_from=action.effective_date,
            is_current=True,
        )

        # Sisa kolom disalin dari baris berjalan: perubahan gaji tidak
        # boleh diam-diam mengosongkan nomor BPJS atau metode
        # pembayarannya.
        #
        # **Daftar ini harus ikut bertambah setiap kali
        # `PayrollAssignment` dapat kolom baru.** Kolom yang lupa
        # ditambahkan tidak menghasilkan error — ia menghasilkan baris
        # payroll baru yang kolomnya kosong, dan pegawainya dibayar
        # dengan konfigurasi yang tidak pernah dipilih siapa pun.
        # `payroll_policy` dan `daily_rate` sempat terlewat begitu:
        # satu kenaikan gaji membuat pegawai harian kehilangan
        # kebijakannya dan diam-diam dihitung bulanan.
        #
        # Tidak ada `proposed_payroll_policy` maupun
        # `proposed_daily_rate` di `EmployeeAction`, jadi kedua kolom
        # ini memang tidak pernah diganti oleh action — menyalinnya
        # apa adanya sudah benar. Kalau kelak ada action yang memang
        # memindahkan kebijakan, ia harus ditulis seperti
        # `salary_grade` di atas: usulan dulu, baris berjalan sebagai
        # cadangan.
        if current is not None:
            for field_name in (
                "payment_method",
                "tax_status",
                "tax_number_payroll",
                "bpjs_kesehatan_number",
                "bpjs_ketenagakerjaan_number",
                "overtime_eligible",
                "overtime_group",
                "payroll_policy",
                "daily_rate",
                "allowance_template",
                "deduction_template",
                "payroll_notes",
            ):
                setattr(
                    new_row,
                    field_name,
                    getattr(current, field_name),
                )

        if user is not None:
            new_row.created_by = user
            new_row.updated_by = user

        # Baris lama ditutup **lebih dulu**, baru barisnya yang baru
        # terbit. Urutannya bukan selera:
        # `uniq_current_employee_payroll_assignment` melarang dua baris
        # berjalan untuk satu pegawai, jadi menyimpan yang baru selagi
        # yang lama masih `is_current` ditolak database — dan
        # `full_clean()` sudah menolaknya lebih dulu. Seluruhnya di
        # dalam satu transaksi, jadi tidak ada saat pegawai ini tidak
        # punya baris berjalan sama sekali.
        #
        # Tanggal penutupnya tidak diubah: tetap `effective_date`,
        # semantik yang sudah dipakai sejak method ini ada.
        if current is not None:
            current.is_current = False
            current.effective_to = action.effective_date
            current.updated_by = user

            current.save(
                update_fields=[
                    "is_current",
                    "effective_to",
                    "updated_by",
                    "updated_at",
                ],
            )

        new_row.full_clean()
        new_row.save()

    @classmethod
    def _apply_separation(cls, action: EmployeeAction, user):
        changes = {
            "termination_date": action.last_working_date,
        }

        if action.termination_reason_id:
            changes["termination_reason"] = action.termination_reason

        if action.proposed_employment_status_id:
            changes["employment_status"] = action.proposed_employment_status

        cls._write_employment(action, user, changes)

        # Akun dan daftar pegawai aktif ikut menyesuaikan. Bukan soft
        # delete: orangnya pernah bekerja di sini dan datanya tetap
        # dibutuhkan untuk arsip, pajak, dan surat keterangan.
        employee = action.employee

        if employee.is_active:
            employee.is_active = False
            employee.updated_by = user

            employee.save(
                update_fields=["is_active", "updated_by", "updated_at"],
            )

    # Empat jenis perubahan organisasi memakai penerapan yang sama, dan
    # itu disengaja: yang membedakan promosi dari mutasi adalah
    # alasannya dan meja yang menyetujuinya, bukan kolom yang ditulis.
    HANDLERS = {
        EmployeeActionType.CONTRACT_EXTENSION: (
            "_apply_contract_extension"
        ),
        EmployeeActionType.CONTRACT_CHANGE: "_apply_contract_change",
        EmployeeActionType.EMPLOYMENT_TYPE_CHANGE: (
            "_apply_employment_type_change"
        ),
        EmployeeActionType.PROBATION_CHANGE: "_apply_probation_change",
        EmployeeActionType.STATUS_CHANGE: "_apply_status_change",
        EmployeeActionType.TRANSFER: "_apply_organization",
        EmployeeActionType.PROMOTION: "_apply_organization",
        EmployeeActionType.DEMOTION: "_apply_organization",
        EmployeeActionType.POSITION_CHANGE: "_apply_organization",
        EmployeeActionType.SALARY_CHANGE: "_apply_salary_change",
        EmployeeActionType.RESIGNATION: "_apply_separation",
        EmployeeActionType.TERMINATION: "_apply_separation",
    }
