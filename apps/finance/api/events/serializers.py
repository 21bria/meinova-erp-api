from rest_framework import serializers

from apps.finance.models import AccountingEvent


class AccountingEventSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    status_label = serializers.CharField(
        source="get_status_display", read_only=True,
    )
    journal_number = serializers.CharField(
        source="generated_journal.journal_number",
        read_only=True,
        default=None,
    )
    policy_code = serializers.CharField(
        source="applied_policy.code", read_only=True, default=None,
    )

    can_retry = serializers.SerializerMethodField()

    class Meta:
        model = AccountingEvent
        fields = "__all__"

        # **Seluruhnya read-only.** Kejadian akuntansi adalah catatan
        # apa yang dikirim modul lain; menyuntingnya dari layar berarti
        # mengarang ulang sejarah, dan jurnal yang sudah terbit darinya
        # tidak ikut berubah.
        read_only_fields = [
            field.name for field in AccountingEvent._meta.fields
        ] + [
            "company_name",
            "status_label",
            "journal_number",
            "policy_code",
            "can_retry",
        ]

    def get_can_retry(self, obj) -> bool:
        from apps.finance.models import AccountingEventStatus

        return obj.status != AccountingEventStatus.PROCESSED
