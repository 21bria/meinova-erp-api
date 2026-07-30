from rest_framework import serializers

from apps.hr.models import EmployeeCertificate


class EmployeeCertificateSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    certificate_type_name = serializers.CharField(
        source="certificate_type.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeCertificate
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

        issue_date = attrs.get(
            "issue_date",
            getattr(instance, "issue_date", None),
        )

        expiry_date = attrs.get(
            "expiry_date",
            getattr(instance, "expiry_date", None),
        )

        is_lifetime = attrs.get(
            "is_lifetime",
            getattr(instance, "is_lifetime", False),
        )

        errors = {}

        if (
            issue_date
            and expiry_date
            and expiry_date < issue_date
        ):
            errors["expiry_date"] = (
                "Expiry Date tidak boleh lebih awal "
                "dari Issue Date."
            )

        if is_lifetime and expiry_date:
            errors["expiry_date"] = (
                "Expiry Date harus kosong jika sertifikat "
                "berlaku seumur hidup."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs