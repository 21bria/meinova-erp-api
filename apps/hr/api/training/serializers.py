from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import TrainingParticipant, TrainingProgram


class TrainingProgramSerializer(serializers.ModelSerializer):
    training_category_name = serializers.CharField(
        source="training_category.name",
        read_only=True,
        default=None,
    )

    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True,
        default=None,
    )

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    currency_code = serializers.CharField(
        source="currency.code",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # Dua sumber, satu kunci. Daftar memakai anotasi `participant_total`
    # (satu query untuk seluruh halaman); respons simpan datang dari
    # service dan **tidak** beranotasi, jadi jatuh ke property model.
    # Menunjuk anotasinya lewat `source=` saja akan menjatuhkan respons
    # POST/PATCH dengan AttributeError — dan itu muncul tepat setelah
    # penggunanya menekan Simpan, di layar yang datanya sebenarnya
    # sudah tersimpan.
    participant_count = serializers.SerializerMethodField()

    class Meta:
        model = TrainingProgram
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "training_category_name",
            "provider_name",
            "company_name",
            "currency_code",
            "status_label",
            "participant_count",
        ]

    def get_participant_count(self, obj) -> int:
        total = getattr(obj, "participant_total", None)

        if total is not None:
            return total

        return obj.participant_count

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        start_date = resolved("start_date")
        end_date = resolved("end_date")
        quota = resolved("quota")
        cost = resolved("cost")
        currency = resolved("currency")

        errors = {}

        if start_date and end_date and end_date < start_date:
            errors["end_date"] = (
                "End Date cannot be earlier than Start Date."
            )

        if quota is not None and quota <= 0:
            errors["quota"] = "Quota must be greater than zero."

        if cost is not None and cost < 0:
            errors["cost"] = "Cost cannot be negative."

        if cost is not None and cost > 0 and currency is None:
            errors["currency"] = "Currency is required when Cost is set."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class TrainingParticipantSerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(
        source="program.code",
        read_only=True,
    )

    program_name = serializers.CharField(
        source="program.name",
        read_only=True,
    )

    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = TrainingParticipant
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "program_code",
            "program_name",
            "employee_name",
            "employee_number",
            "status_label",
        ]

    def validate(self, attrs):
        instance = self.instance

        score = (
            attrs["score"]
            if "score" in attrs
            else getattr(instance, "score", None)
        )

        if score is not None and score < 0:
            raise serializers.ValidationError(
                {
                    "score": "Score cannot be negative.",
                }
            )

        return attrs
