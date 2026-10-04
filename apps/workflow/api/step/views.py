from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.workflow.models import WorkflowStep
from apps.workflow.permissions import CanConfigureWorkflow
from apps.workflow.services import WorkflowStepService

from .schema import STEP_SCHEMA
from .serializers import WorkflowStepSerializer


class WorkflowStepViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = WorkflowStepSerializer
    service_class = WorkflowStepService

    permission_classes = [CanConfigureWorkflow]

    framework_module = "workflow/steps"
    schema = STEP_SCHEMA

    # Base memberi default ["code", "name"], dan WorkflowStep tidak
    # punya `code` — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "name",
        "description",
        "definition__code",
        "definition__name",
    ]

    filterset_fields = [
        "definition",
        "approver_type",
        "approval_mode",
        "approver_role",
        "approver_user",
        "is_required",
        "is_active",
    ]

    ordering_fields = [
        "definition__code",
        "sequence",
        "name",
        "approver_type",
        "created_at",
        "updated_at",
    ]

    # Lewat `definition__code`, bukan `definition` — yang kedua
    # mengurutkan lewat id, jadi urutan alurnya ditentukan kebetulan
    # baris mana yang diseed duluan dan berubah begitu ada yang
    # menghapus lalu membuatnya lagi. Di layar yang isinya
    # berkelompok, urutan kelompok yang tidak bisa ditebak sama saja
    # dengan tidak berkelompok.
    ordering = ["definition__code", "sequence"]

    def get_queryset(self):
        return (
            WorkflowStep.objects
            .select_related(
                "definition",
                "approver_user",
                "approver_role",
                "approver_position",
                "fallback_role",
            )
            .filter(is_deleted=False)
        )
