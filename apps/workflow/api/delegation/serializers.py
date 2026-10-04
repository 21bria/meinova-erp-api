from rest_framework import serializers

from apps.workflow.models import WorkflowDelegation


class WorkflowDelegationSerializer(serializers.ModelSerializer):
    delegator_name = serializers.SerializerMethodField()

    delegate_name = serializers.SerializerMethodField()

    scope_label = serializers.SerializerMethodField()

    is_running = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowDelegation
        fields = "__all__"

        read_only_fields = [
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "delegator_name",
            "delegate_name",
            "scope_label",
            "is_running",
        ]

    def _name(self, user):
        if user is None:
            return None

        return user.get_full_name() or user.email

    def get_delegator_name(self, obj) -> str | None:
        return self._name(obj.delegator)

    def get_delegate_name(self, obj) -> str | None:
        return self._name(obj.delegate)

    def get_scope_label(self, obj) -> str:
        if not obj.module and not obj.document_type:
            return "Semua dokumen"

        if obj.module and not obj.document_type:
            return f"Semua dokumen {obj.module}"

        return f"{obj.module}/{obj.document_type}"

    def get_is_running(self, obj) -> bool:
        """Sedang berlaku sekarang — bukan sekadar aktif."""
        from django.utils import timezone

        if not obj.is_active or obj.is_deleted:
            return False

        now = timezone.now()

        return obj.starts_at <= now <= obj.ends_at

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        delegator = resolved("delegator")
        delegate = resolved("delegate")

        if delegator and delegate and delegator == delegate:
            errors["delegate"] = (
                "Tidak bisa memberi kuasa kepada diri sendiri."
            )

        starts_at = resolved("starts_at")
        ends_at = resolved("ends_at")

        if starts_at and ends_at and ends_at <= starts_at:
            errors["ends_at"] = "Berakhir harus setelah mulai."

        if resolved("document_type") and not resolved("module"):
            errors["module"] = (
                "Isi modulnya juga kalau cakupannya dibatasi ke satu "
                "jenis dokumen."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
