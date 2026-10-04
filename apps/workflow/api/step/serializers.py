from rest_framework import serializers

from apps.workflow import conditions
from apps.workflow.labels import (
    APPROVAL_MODE_LABELS,
    APPROVER_SCOPE_LABELS,
    APPROVER_TYPE_LABELS,
    label_for,
)
from apps.workflow.models import ApproverType, WorkflowStep


class WorkflowStepSerializer(serializers.ModelSerializer):
    definition_name = serializers.CharField(
        source="definition.name",
        read_only=True,
        default=None,
    )

    # Diterjemahkan lewat peta di `apps/workflow/labels.py`, bukan lewat
    # `get_*_display()`. Label `TextChoices` ikut masuk state migration,
    # jadi menerjemahkannya di model menerbitkan `AlterField` yang tidak
    # menyentuh satu byte pun di database — dan nilai enum-nya sendiri
    # memang tidak boleh berubah.
    approver_type_label = serializers.SerializerMethodField()

    approval_mode_label = serializers.SerializerMethodField()

    approver_scope_label = serializers.SerializerMethodField()

    def get_approver_type_label(self, obj) -> str:
        return label_for(APPROVER_TYPE_LABELS, obj.approver_type)

    def get_approval_mode_label(self, obj) -> str:
        return label_for(APPROVAL_MODE_LABELS, obj.approval_mode)

    def get_approver_scope_label(self, obj) -> str:
        return label_for(APPROVER_SCOPE_LABELS, obj.approver_scope)

    approver_user_name = serializers.CharField(
        source="approver_user.email",
        read_only=True,
        default=None,
    )

    approver_role_name = serializers.CharField(
        source="approver_role.name",
        read_only=True,
        default=None,
    )

    approver_position_name = serializers.CharField(
        source="approver_position.name",
        read_only=True,
        default=None,
    )

    fallback_role_name = serializers.CharField(
        source="fallback_role.name",
        read_only=True,
        default=None,
    )

    # Dikosongkan berarti "nomor bebas berikutnya" (lihat
    # `WorkflowStepService.apply_sequence`). `required=False` saja tidak
    # cukup — `UniqueTogetherValidator` yang dibangkitkan DRF dari
    # constraint (definition, sequence) menuntut setiap anggotanya hadir
    # di payload dan membalas "This field is required" sebelum service
    # sempat jalan. Yang melewatinya `default=None`.
    sequence = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = WorkflowStep
        fields = "__all__"

        read_only_fields = [
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "definition_name",
            "approver_type_label",
            "approval_mode_label",
            "approver_scope_label",
            "approver_user_name",
            "approver_role_name",
            "approver_position_name",
            "fallback_role_name",
        ]

    def validate_condition(self, value):
        try:
            conditions.validate(value)
        except Exception as error:  # noqa: BLE001
            raise serializers.ValidationError(
                getattr(error, "messages", [str(error)]),
            ) from error

        return value

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        approver_type = resolved("approver_type")

        # Diperiksa di sini juga, bukan cuma di `Model.clean()`: pesan
        # per field dari serializer yang dipakai form untuk menyorot
        # kolom yang salah.
        if approver_type == ApproverType.USER and not resolved("approver_user"):
            errors["approver_user"] = (
                "Pilih penggunanya untuk step bertipe Specific User."
            )

        if approver_type == ApproverType.ROLE and not resolved("approver_role"):
            errors["approver_role"] = (
                "Pilih role-nya untuk step bertipe Role Holder."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
