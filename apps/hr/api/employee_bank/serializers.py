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
    currency_code = serializers.CharField(
        source="currency.code",
        read_only=True,
        default=None,
        allow_null=True,
    )
    currency_name = serializers.CharField(
        source="currency.name",
        read_only=True,
        default=None,
        allow_null=True,
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
        
    def validate(self, attrs):
        instance = self.instance

        employee = attrs.get(
            "employee",
            getattr(instance, "employee", None),
        )

        bank = attrs.get(
            "bank",
            getattr(instance, "bank", None),
        )

        account_number = attrs.get(
            "account_number",
            getattr(instance, "account_number", None),
        )

        account_number = str(
            account_number or "",
        ).strip()

        if not employee or not bank or not account_number:
            return attrs

        queryset = EmployeeBankAccount.objects.filter(
            employee=employee,
            bank=bank,
            account_number=account_number,
            is_deleted=False,
        )

        if instance:
            queryset = queryset.exclude(
                pk=instance.pk,
            )

        if queryset.exists():
            raise serializers.ValidationError({
                "account_number": (
                    "This account number already exists "
                    "for this employee and bank."
                ),
            })

        attrs["account_number"] = account_number

        return attrs