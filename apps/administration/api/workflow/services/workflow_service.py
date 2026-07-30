from apps.administration.models import (
    WorkflowDefinition,
    WorkflowStep,
    WorkflowInstance,
    WorkflowApproval,
    WorkflowDelegation,
)


class WorkflowDefinitionService:

    @staticmethod
    def list():
        return WorkflowDefinition.objects.select_related("company")


class WorkflowStepService:

    @staticmethod
    def list():
        return WorkflowStep.objects.select_related(
            "workflow"
        ).order_by("step_order")


class WorkflowInstanceService:

    @staticmethod
    def list():
        return WorkflowInstance.objects.select_related(
            "workflow",
            "company",
            "site",
            "requested_by",
        ).order_by("-created_at")


class WorkflowApprovalService:

    @staticmethod
    def list():
        return WorkflowApproval.objects.select_related(
            "instance",
            "step",
            "approver",
        )


class WorkflowDelegationService:

    @staticmethod
    def list():
        return WorkflowDelegation.objects.select_related(
        "company",
        "site",
        "workflow",
        "delegator",
        "delegate",
    )