from rest_framework.permissions import IsAuthenticated

from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.workflow.serializers.workflow import *
from apps.administration.api.workflow.services.workflow_service import *


class WorkflowDefinitionViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowDefinitionSerializer
    service_class = WorkflowDefinitionService

    framework_module = "administration/workflow/definitions"
    schema_type = "crud"

    schema = {
        "title": "Workflow Definition",
        "description": "Manage workflow definitions and approval flows.",
        "endpoint": "/api/administration/workflow/definitions/",
    }

    ordering = ["-created_at"]

    search_fields = [
        "name",
        "code",
        "description",
    ]

    filterset_fields = [
        "is_active",
        "company",
    ]


class WorkflowStepViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowStepSerializer
    service_class = WorkflowStepService

    framework_module = "administration/workflow/steps"
    schema_type = "crud"

    schema = {
        "title": "Workflow Step",
        "description": "Manage workflow steps and routing.",
        "endpoint": "/api/administration/workflow/steps/",
    }

    ordering = ["-created_at"]

    search_fields = [
        "name",
        "description",
        "workflow__name",
    ]

    filterset_fields = [
        "workflow",
        "is_active",
    ]


class WorkflowInstanceViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowInstanceSerializer
    service_class = WorkflowInstanceService

    framework_module = "administration/workflow/instances"
    schema_type = "crud"

    schema = {
        "title": "Workflow Instance",
        "description": "Manage workflow execution instances.",
        "endpoint": "/api/administration/workflow/instances/",
    }

    ordering = ["-created_at"]

    search_fields = [
        "object_id",
        "object_repr",
        "object_type",
        "status",
        "workflow__name",
        "requested_by__username",
    ]

    filterset_fields = [
        "status",
        "workflow",
        "current_step",
        "requested_by",
        "company",
        "site",
    ]


class WorkflowApprovalViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowApprovalSerializer
    service_class = WorkflowApprovalService

    framework_module = "administration/workflow/approvals"
    schema_type = "crud"

    schema = {
        "title": "Workflow Approval",
        "description": "Manage workflow approvals and decisions.",
        "endpoint": "/api/administration/workflow/approvals/",
    }

    ordering = ["-acted_at"]

    search_fields = [
        "status",
        "notes",
        "approver__username",
    ]

    filterset_fields = [
        "status",
        "approver",
        "instance",
        "step",
    ]

class WorkflowDelegationViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowDelegationSerializer
    service_class = WorkflowDelegationService

    framework_module = "administration/workflow/delegations"
    schema_type = "crud"

    schema = {
        "title": "Workflow Delegation",
        "description": "Manage workflow delegation rules.",
        "endpoint": "/api/administration/workflow/delegations/",
    }

    ordering = ["-id"]
    search_fields = []
    filterset_fields = []