from django.core.exceptions import ValidationError

from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import EmployeeAction

from .schema import EMPLOYEE_ACTION_SCHEMA
from .serializers import EmployeeActionSerializer
from .services import EmployeeActionService


class EmployeeActionViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Dokumen perubahan data kepegawaian.

    Penyaringan barisnya mengikuti aturan HR biasa (kewenangan `RoleAssignment`
    lewat `data_scope`) — bukan aturan keterlibatan milik workflow. Dua
    hal yang berbeda dan sengaja dibiarkan berbeda: daftar dokumen di
    sini adalah data HR, sedangkan dokumen yang mendarat di kotak masuk
    approver tetap dilayani `WorkflowApprovalViewSet` dengan aturannya
    sendiri, supaya approver lintas lokasi tetap bisa membuka dokumen
    yang memang ditugaskan kepadanya.
    """

    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = EmployeeActionSerializer
    service_class = EmployeeActionService

    framework_module = "hr/employee-actions"
    schema = EMPLOYEE_ACTION_SCHEMA

    # Base memberi default ["code", "name"], dan model ini tidak punya
    # dua kolom itu — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "reason",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "action_type",
        "status",
        "company",
        "branch",
        "location",
        "effective_date",
    ]

    ordering_fields = [
        "document_number",
        "effective_date",
        "action_type",
        "status",
        "applied_at",
        "created_at",
    ]

    ordering = [
        "-effective_date",
        "-created_at",
    ]

    def get_queryset(self):
        return (
            EmployeeAction.objects
            .select_related(
                "employee",
                "employee__employment",
                "employee__employment__employment_type",
                "employee__employment__employment_status",
                "employee__employment__employee_group",
                "employee__employment__contract_type",
                "employee__employment__probation_type",
                "employee__organization",
                "employee__organization__position",
                "employee__organization__department",
                "employee__organization__section",
                "employee__organization__location",
                "company",
                "branch",
                "location",
                "proposed_employment_type",
                "proposed_employment_status",
                "proposed_contract_type",
                "proposed_probation_type",
                "proposed_position",
                "proposed_reports_to",
            )
            .prefetch_related("employee__payroll_assignments")
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message):
        instance.refresh_from_db()

        return success_response(
            data={
                "employee_action": EmployeeActionSerializer(
                    instance,
                    context=self.get_serializer_context(),
                ).data,
            },
            message=message,
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        instance = self.get_object()

        EmployeeActionService.submit(
            instance=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Employee Action diajukan.",
        )

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        instance = self.get_object()

        EmployeeActionService.withdraw(
            instance=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan ditarik kembali.",
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, approved=True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, approved=False)

    def _decide(self, request, *, approved: bool):
        instance = self.get_object()

        notes = request.data.get("notes", "")

        # Penolakan tanpa alasan tidak bisa ditindaklanjuti pengaju — ia
        # hanya tahu ditolak, tidak tahu apa yang harus dibetulkan.
        if not approved and not str(notes).strip():
            raise ValidationError(
                {"notes": "Alasan penolakan wajib diisi."},
            )

        EmployeeActionService.decide(
            instance=instance,
            approved=approved,
            user=self._user(request),
            notes=notes,
        )

        return self._respond(
            instance=instance,
            message=(
                "Employee Action disetujui."
                if approved
                else "Employee Action ditolak."
            ),
        )

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """
        Mengulang penerapan yang gagal.

        Bukan jalan pintas melewati persetujuan: `EmployeeActionService.
        apply()` menolak dokumen yang belum APPROVED, dan yang sudah
        diterapkan dikembalikan apa adanya tanpa menyentuh data pegawai
        untuk kedua kalinya. Ini untuk kasus alur sudah selesai tapi
        penulisannya gagal — mis. master yang belum lengkap — dan
        seseorang harus bisa menjalankannya lagi setelah datanya
        dibetulkan, tanpa mengulang seluruh rantai tanda tangan.
        """
        instance = self.get_object()

        EmployeeActionService.apply(
            instance=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message="Perubahan diterapkan ke data pegawai.",
        )
