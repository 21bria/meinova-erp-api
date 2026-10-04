from rest_framework import serializers

from apps.finance.models import AccountMapping


class AccountMappingSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    account_code = serializers.CharField(
        source="account.code", read_only=True, default=None,
    )
    account_name = serializers.SerializerMethodField()
    location_name = serializers.CharField(
        source="location.name", read_only=True, default=None,
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None,
    )
    cost_center_name = serializers.CharField(
        source="cost_center.name", read_only=True, default=None,
    )

    class Meta:
        model = AccountMapping
        fields = "__all__"

        read_only_fields = [
            # Dihitung dari syaratnya, tidak pernah diketik — kalau bisa
            # diisi orang, aturan yang lebih umum bisa mengalahkan yang
            # lebih khusus tanpa ada yang bisa menjelaskan kenapa.
            "specificity",
            "company_name",
            "account_code",
            "account_name",
            "location_name",
            "department_name",
            "cost_center_name",
        ]

    def get_account_name(self, obj) -> str | None:
        if obj.account_id is None:
            return None

        return f"{obj.account.code} — {obj.account.name}"
