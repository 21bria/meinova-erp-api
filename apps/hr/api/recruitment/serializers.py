from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import Candidate, CandidateInterview, JobVacancy
from apps.uploads.api.serializers import UploadedFileSerializer
from apps.uploads.models import UploadedFile


class JobVacancySerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
    )

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    division_name = serializers.CharField(
        source="division.name",
        read_only=True,
        default=None,
    )

    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        default=None,
    )

    position_name = serializers.CharField(
        source="position.name",
        read_only=True,
        default=None,
    )

    employment_type_name = serializers.CharField(
        source="employment_type.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # Dua sumber, satu kunci: anotasi `candidate_total` untuk daftar,
    # property model untuk respons simpan yang datang dari service dan
    # tidak beranotasi.
    candidate_count = serializers.SerializerMethodField()

    class Meta:
        model = JobVacancy
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "company_name",
            "branch_name",
            "location_name",
            "division_name",
            "department_name",
            "position_name",
            "employment_type_name",
            "status_label",
            "candidate_count",
        ]

    def get_candidate_count(self, obj) -> int:
        total = getattr(obj, "candidate_total", None)

        if total is not None:
            return total

        return obj.candidate_count

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        open_date = resolved("open_date")
        close_date = resolved("close_date")
        quota = resolved("quota")

        errors = {}

        if open_date and close_date and close_date < open_date:
            errors["close_date"] = (
                "Close Date cannot be earlier than Open Date."
            )

        if quota is not None and quota <= 0:
            errors["quota"] = "Quota must be greater than zero."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class CandidateSerializer(serializers.ModelSerializer):
    vacancy_code = serializers.CharField(
        source="vacancy.code",
        read_only=True,
        default=None,
    )

    vacancy_title = serializers.CharField(
        source="vacancy.title",
        read_only=True,
        default=None,
    )

    gender_name = serializers.CharField(
        source="gender.name",
        read_only=True,
        default=None,
    )

    education_name = serializers.CharField(
        source="education.name",
        read_only=True,
        default=None,
    )

    source_name = serializers.CharField(
        source="source.name",
        read_only=True,
        default=None,
    )

    status_name = serializers.CharField(
        source="status.name",
        read_only=True,
        default=None,
    )

    currency_code = serializers.CharField(
        source="currency.code",
        read_only=True,
        default=None,
    )

    rejection_reason_name = serializers.CharField(
        source="rejection_reason.name",
        read_only=True,
        default=None,
    )

    hired_employee_name = serializers.CharField(
        source="hired_employee.full_name",
        read_only=True,
        default=None,
    )

    resume_file = serializers.PrimaryKeyRelatedField(
        queryset=UploadedFile.objects.active(),
        required=False,
        allow_null=True,
    )

    resume_file_detail = UploadedFileSerializer(
        source="resume_file",
        read_only=True,
    )

    class Meta:
        model = Candidate
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "vacancy_code",
            "vacancy_title",
            "gender_name",
            "education_name",
            "source_name",
            "status_name",
            "currency_code",
            "rejection_reason_name",
            "hired_employee_name",
            "resume_file_detail",
        ]

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        applied_date = resolved("applied_date")
        hired_date = resolved("hired_date")
        expected_salary = resolved("expected_salary")
        currency = resolved("currency")

        errors = {}

        if applied_date and hired_date and hired_date < applied_date:
            errors["hired_date"] = (
                "Hired Date cannot be earlier than Applied Date."
            )

        if expected_salary is not None and expected_salary < 0:
            errors["expected_salary"] = (
                "Expected Salary cannot be negative."
            )

        if (
            expected_salary is not None
            and expected_salary > 0
            and currency is None
        ):
            errors["currency"] = (
                "Currency is required when Expected Salary is set."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class CandidateInterviewSerializer(serializers.ModelSerializer):
    candidate_number = serializers.CharField(
        source="candidate.candidate_number",
        read_only=True,
    )

    candidate_name = serializers.CharField(
        source="candidate.full_name",
        read_only=True,
    )

    interview_type_name = serializers.CharField(
        source="interview_type.name",
        read_only=True,
        default=None,
    )

    interviewer_name = serializers.CharField(
        source="interviewer.full_name",
        read_only=True,
        default=None,
    )

    result_label = serializers.CharField(
        source="get_result_display",
        read_only=True,
    )

    class Meta:
        model = CandidateInterview
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "candidate_number",
            "candidate_name",
            "interview_type_name",
            "interviewer_name",
            "result_label",
        ]

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        stage = resolved("stage")
        score = resolved("score")

        errors = {}

        if stage is not None and stage <= 0:
            errors["stage"] = "Stage must be greater than zero."

        if score is not None and score < 0:
            errors["score"] = "Score cannot be negative."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
