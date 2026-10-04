from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.workflow.models import WorkflowDelegation
from apps.workflow.permissions import CanManageDelegation
from apps.workflow.services import WorkflowDelegationService

from .schema import DELEGATION_SCHEMA
from .serializers import WorkflowDelegationSerializer


class WorkflowDelegationViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = WorkflowDelegationSerializer
    service_class = WorkflowDelegationService

    permission_classes = [CanManageDelegation]

    # Kuasa adalah urusan pribadi: siapa pun boleh menyerahkan hak
    # tanda tangannya sendiri, dan `CanManageDelegation` sudah menjaga
    # supaya tidak ada yang membuatnya atas nama orang lain. Menambahkan
    # izin model di atasnya akan membuat atasan yang mau cuti harus
    # menunggu IT — persis hal yang dihindari desainnya.
    enforce_model_permissions = False

    framework_module = "workflow/delegations"
    schema = DELEGATION_SCHEMA

    # Base memberi default ["code", "name"] dan model ini tidak punya
    # keduanya — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "delegator__email",
        "delegator__first_name",
        "delegator__last_name",
        "delegate__email",
        "delegate__first_name",
        "delegate__last_name",
        "module",
        "document_type",
        "reason",
    ]

    filterset_fields = [
        "delegator",
        "delegate",
        "module",
        "document_type",
        "is_active",
    ]

    ordering_fields = [
        "starts_at",
        "ends_at",
        "created_at",
        "updated_at",
    ]

    ordering = ["-starts_at"]

    def get_queryset(self):
        return (
            WorkflowDelegation.objects
            .select_related("delegator", "delegate")
            .filter(is_deleted=False)
        )
