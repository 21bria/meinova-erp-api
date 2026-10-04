from django.core.exceptions import ValidationError

from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.services.company_copy import CompanyCopyViewSetMixin
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.workflow import selectors
from apps.workflow.permissions import CanConfigureWorkflow
from apps.workflow.services import WorkflowDefinitionService

from .schema import WORKFLOW_DEFINITION_SCHEMA
from .serializers import WorkflowDefinitionSerializer


class WorkflowDefinitionViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = WorkflowDefinitionSerializer
    service_class = WorkflowDefinitionService

    # Mengubah alur = menentukan siapa menyetujui dokumen siapa.
    # Menyembunyikan menunya di frontend tidak cukup — endpoint-nya
    # tetap bisa ditembak langsung.
    permission_classes = [CanConfigureWorkflow]

    framework_module = "workflow/definitions"
    schema = WORKFLOW_DEFINITION_SCHEMA

    search_fields = [
        "code",
        "name",
        "module",
        "document_type",
        "description",
    ]

    filterset_fields = [
        "module",
        "document_type",
        "status",
        "company",
        "branch",
        "location",
        "employee_group",
        "is_active",
    ]

    ordering_fields = [
        "code",
        "name",
        "module",
        "document_type",
        "status",
        "version",
        "created_at",
        "updated_at",
    ]

    ordering = ["module", "document_type", "code"]

    def get_queryset(self):
        return selectors.definitions()

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """
        Menyalakan alur setelah memastikan ia punya step.

        Alur aktif tanpa step akan menerima pengajuan lalu gagal saat
        menyusun kotak tanda tangannya — dan pesan gagalnya muncul di
        layar pengaju, bukan di layar yang mengonfigurasinya.
        """
        definition = WorkflowDefinitionService.activate(
            instance=self.get_object(),
            user=request.user,
        )

        return success_response(
            data=self.get_serializer(definition).data,
            message=f"Alur {definition.code} diaktifkan.",
        )

    @action(detail=True, methods=["post"])
    def preview_approvers(self, request, pk=None):
        """
        Mencoba menyusun kotak tanda tangan untuk satu pegawai, tanpa
        membuat dokumen apa pun.

        Ini jawaban untuk "kenapa pengajuan saya gagal": hasilnya
        menyebut per step siapa yang ketemu, atau kolom mana yang masih
        kosong. Tanpa layar ini, satu-satunya cara mengetahuinya adalah
        menekan Submit di dokumen sungguhan dan membaca pesan errornya.
        """
        from apps.hr.models import Employee
        from apps.workflow.resolver import resolve_approvers

        definition = self.get_object()

        employee_id = request.data.get("employee")

        if not employee_id:
            raise ValidationError({"employee": "Pilih pegawainya dulu."})

        employee = (
            Employee.objects
            .filter(pk=employee_id, is_deleted=False)
            .select_related("organization", "organization__company")
            .first()
        )

        if employee is None:
            raise ValidationError({"employee": "Pegawai tidak ditemukan."})

        company = getattr(
            getattr(employee, "organization", None),
            "company",
            None,
        )

        rows = []

        for step in definition.steps.filter(
            is_deleted=False,
            is_active=True,
        ).order_by("sequence"):
            resolved = resolve_approvers(
                employee=employee,
                step=step,
                company=company,
            )

            rows.append(
                {
                    "sequence": step.sequence,
                    "name": step.name,
                    "approver_type": step.approver_type,
                    "is_required": step.is_required,
                    "found": resolved.found,
                    "reason": resolved.reason,
                    "approvers": [
                        {
                            "user_id": candidate.user.pk,
                            "name": (
                                candidate.employee.full_name
                                if candidate.employee
                                else candidate.user.email
                            ),
                        }
                        for candidate in resolved.candidates
                    ],
                },
            )

        blocking = [
            row
            for row in rows
            if not row["found"] and row["is_required"]
        ]

        return success_response(
            data={
                "employee": employee.full_name,
                "steps": rows,
                "can_submit": not blocking,
            },
            message=(
                "Semua approver ketemu."
                if not blocking
                else f"{len(blocking)} step belum punya approver."
            ),
        )
