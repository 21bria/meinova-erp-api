from rest_framework import serializers

from apps.finance.models import AccountingPeriod, PeriodStatus


class AccountingPeriodSerializer(serializers.ModelSerializer):
    fiscal_year_name = serializers.CharField(
        source="fiscal_year.name", read_only=True, default=None,
    )

    fiscal_year_code = serializers.CharField(
        source="fiscal_year.code", read_only=True, default=None,
    )

    company = serializers.IntegerField(
        source="fiscal_year.company_id", read_only=True,
    )

    company_name = serializers.CharField(
        source="fiscal_year.company.name", read_only=True, default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    closed_by_name = serializers.CharField(
        source="closed_by.get_full_name", read_only=True, default=None,
    )

    reopened_by_name = serializers.CharField(
        source="reopened_by.get_full_name", read_only=True, default=None,
    )

    # Aksi mana yang berarti untuk baris ini. Dihitung dari peta
    # perpindahan di service — bukan dari daftar status yang disalin ke
    # frontend, yang akan tertinggal diam-diam begitu petanya berubah.
    allowed_transitions = serializers.SerializerMethodField()

    has_posted_journals = serializers.SerializerMethodField()

    class Meta:
        model = AccountingPeriod
        fields = "__all__"

        read_only_fields = [
            "fiscal_year_name",
            "fiscal_year_code",
            "company",
            "company_name",
            "status_label",
            "closed_at",
            "closed_by",
            "closed_by_name",
            "reopened_at",
            "reopened_by",
            "reopened_by_name",
            "reopen_reason",
            "allowed_transitions",
            "has_posted_journals",
        ]

    def get_allowed_transitions(self, obj) -> list[str]:
        from apps.finance.services import AccountingPeriodService

        return sorted(
            AccountingPeriodService.TRANSITIONS.get(obj.status, set())
        )

    def get_has_posted_journals(self, obj) -> bool:
        annotated = getattr(obj, "posted_journal_count", None)

        if annotated is not None:
            return annotated > 0

        from apps.finance.services import FiscalPeriodService

        return FiscalPeriodService.has_posted_journals(obj)


class PeriodStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=PeriodStatus.choices)

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Wajib saat membuka kembali periode yang sudah dikunci."
        ),
    )
