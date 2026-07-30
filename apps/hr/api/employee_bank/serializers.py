from rest_framework import serializers

from apps.hr.models import EmployeeBankAccount


class EmployeeBankAccountSerializer(
    serializers.ModelSerializer,
):
    bank_name = serializers.CharField(
        source="bank.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeBankAccount
        fields = "__all__"

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
        ]