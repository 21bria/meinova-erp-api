from rest_framework import serializers

from apps.administration.models import (
    WorkflowDefinition,
    WorkflowStep,
    WorkflowInstance,
    WorkflowApproval,
    WorkflowDelegation,
)


class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowDefinition
        fields = "__all__"
        read_only_fields = [
            "status",
            "started_at",
            "completed_at",
            "current_step",
            "created_at",
            "updated_at",
        ]


class WorkflowStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowStep
        fields = "__all__"


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowInstance
        fields = "__all__"
        read_only_fields = [
            "status",
            "started_at",
            "completed_at",
            "current_step",
            "created_at",
            "updated_at",
        ]

class WorkflowApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowApproval
        fields = "__all__"
        read_only_fields = [
            "status",
            "acted_at"
        ]


class WorkflowDelegationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowDelegation
        fields = "__all__"