from django.conf import settings
from django.db import models
from apps.core.models.base import BaseModel
from .organization import Company, Site


class WorkflowDefinition(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_definitions",
    )

    module = models.CharField(max_length=50)
    document_type = models.CharField(max_length=80)

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)


    class Meta:
        db_table = "master_workflow_definition"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "module", "document_type"],
                name="uniq_workflow_definition",
            )
        ]

    def __str__(self):
        return self.name


class WorkflowStep(BaseModel):
    APPROVER_TYPE_CHOICES = [
        ("ROLE", "Role"),
        ("USER", "User"),
        ("POSITION", "Position"),
        ("DEPARTMENT_HEAD", "Department Head"),
        ("DIVISION_HEAD", "Division Head"),
        ("SECTION_HEAD", "Section Head"),
    ]

    workflow = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.CASCADE,
        related_name="steps",
    )

    step_order = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)

    approver_type = models.CharField(
        max_length=30,
        choices=APPROVER_TYPE_CHOICES,
        default="ROLE",
    )

    approver_role = models.CharField(max_length=100, blank=True)
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_steps",
    )

    require_all = models.BooleanField(default=False)

    class Meta:
        db_table = "master_workflow_step"
        ordering = ["step_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "step_order"],
                name="uniq_workflow_step_order",
            )
        ]

    def __str__(self):
        return f"{self.workflow} - {self.name}"


class WorkflowInstance(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]

    workflow = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.PROTECT,
        related_name="instances",
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_instances",
    )

    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_instances",
    )

    current_step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_instances",
    )

    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    object_repr = models.CharField(max_length=255, blank=True)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="workflow_requests",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "master_workflow_instance"
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.object_repr or f"{self.object_type}:{self.object_id}"


class WorkflowApproval(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("SKIPPED", "Skipped"),
    ]

    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.CASCADE,
        related_name="approvals",
    )

    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.PROTECT,
        related_name="approvals",
    )

    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_approvals",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    notes = models.TextField(blank=True)

    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "master_workflow_approval"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["acted_at"]),
        ]


class WorkflowDelegation(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="workflow_delegations",
    )

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_delegations",
    )

    workflow = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="delegations",
    )

    delegator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workflow_delegations_from",
    )

    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workflow_delegations_to",
    )

    start_date = models.DateField()
    end_date = models.DateField()

    reason = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        db_table = "master_workflow_delegation"
        ordering = ["-start_date"]
        indexes = [
            models.Index(
                fields=[
                    "delegator",
                    "start_date",
                    "end_date",
                ],
            ),
            models.Index(fields=["company", "site"]),
            models.Index(fields=["workflow"]),
        ]

    def __str__(self):
        return f"{self.delegator} -> {self.delegate}"