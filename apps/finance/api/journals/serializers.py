from rest_framework import serializers

from apps.finance.models import (
    EDITABLE_JOURNAL_STATUSES,
    IMMUTABLE_JOURNAL_STATUSES,
    Journal,
    JournalLine,
    JournalLineDimension,
)


class JournalLineDimensionSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalLineDimension
        fields = [
            "id",
            "dimension",
            "dimension_code",
            "value_id",
            "value_text",
            "value_label",
        ]
        read_only_fields = ["dimension_code", "value_label"]


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(
        source="account.code", read_only=True, default=None,
    )
    account_name = serializers.CharField(
        source="account.name", read_only=True, default=None,
    )
    cost_center_name = serializers.CharField(
        source="cost_center.name", read_only=True, default=None,
    )
    location_name = serializers.CharField(
        source="location.name", read_only=True, default=None,
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None,
    )

    dimension_values = JournalLineDimensionSerializer(
        many=True, read_only=True,
    )

    # Dimensi tambahan saat menulis: `{kode: nilai}`. Write-only karena
    # bentuk bacanya berbeda (`dimension_values`, lengkap dengan
    # labelnya) — satu field untuk dua bentuk membuat form mengirim
    # kembali apa yang baru saja dibacanya dan gagal validasi.
    dimensions = serializers.DictField(
        required=False, write_only=True, allow_null=True,
    )

    class Meta:
        model = JournalLine
        fields = "__all__"

        read_only_fields = [
            "journal",
            "company",
            "posting_date",
            "accounting_period",
            "is_posted",
            "base_debit",
            "base_credit",
            "account_code",
            "account_name",
            "cost_center_name",
            "location_name",
            "department_name",
            "dimension_values",
        ]


class JournalSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    currency_code = serializers.CharField(
        source="currency.code", read_only=True, default=None,
    )
    base_currency_code = serializers.CharField(
        source="base_currency.code", read_only=True, default=None,
    )
    fiscal_year_code = serializers.CharField(
        source="fiscal_year.code", read_only=True, default=None,
    )
    accounting_period_code = serializers.CharField(
        source="accounting_period.code", read_only=True, default=None,
    )
    period_status = serializers.CharField(
        source="accounting_period.status", read_only=True, default=None,
    )
    status_label = serializers.CharField(
        source="get_status_display", read_only=True,
    )
    journal_type_label = serializers.CharField(
        source="get_journal_type_display", read_only=True,
    )
    posted_by_name = serializers.CharField(
        source="posted_by.get_full_name", read_only=True, default=None,
    )
    reversal_of_number = serializers.CharField(
        source="reversal_of.journal_number", read_only=True, default=None,
    )
    reversed_by_number = serializers.CharField(
        source="reversed_by.journal_number", read_only=True, default=None,
    )

    lines = JournalLineSerializer(many=True, read_only=True)

    # Baris dikirim utuh saat menyimpan — jurnal adalah satu ayat, dan
    # menyunting barisnya satu per satu membuat dokumen melewati
    # keadaan-keadaan tidak seimbang yang masing-masing harus diputuskan
    # sah atau tidak.
    line_items = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
    )

    is_balanced = serializers.BooleanField(read_only=True)
    difference = serializers.SerializerMethodField()

    # Tiga jawaban yang berbeda, dan memang harus terpisah — lihat
    # `docs/claude/generator-schema.md`. `can_edit` membuka layarnya,
    # `can_save` menyimpan isinya, `can_delete` menghapusnya. Jurnal
    # yang menunggu persetujuan boleh dibuka (di situ tombol Withdraw
    # tinggal) tapi tidak boleh disimpan.
    can_edit = serializers.SerializerMethodField()
    can_save = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    can_post = serializers.SerializerMethodField()
    can_reverse = serializers.SerializerMethodField()

    class Meta:
        model = Journal
        fields = "__all__"

        read_only_fields = [
            "journal_number",
            "fiscal_year",
            "accounting_period",
            "base_currency",
            "status",
            "total_debit",
            "total_credit",
            "base_total_debit",
            "base_total_credit",
            "reversal_of",
            "reversed_by",
            "submitted_at", "submitted_by",
            "approved_at", "approved_by",
            "posted_at", "posted_by",
            "reversed_at", "reversed_by_user",
            "cancelled_at", "cancelled_by",
            "status_reason",
        ]

        extra_kwargs = {
            # Wajib `required=False` supaya pengisian otomatisnya di
            # service sempat jalan. Dibiarkan `required` bawaan model,
            # DRF menolak request lebih dulu dan jalur itu tidak pernah
            # kepakai — jebakan yang sama dengan `location` di Roster
            # Setup.
            "currency": {"required": False},
            "exchange_rate": {"required": False},
        }

    def get_difference(self, obj):
        return obj.total_debit - obj.total_credit

    def get_can_edit(self, obj) -> bool:
        return obj.status not in IMMUTABLE_JOURNAL_STATUSES

    def get_can_save(self, obj) -> bool:
        return obj.status in EDITABLE_JOURNAL_STATUSES

    def get_can_delete(self, obj) -> bool:
        return obj.status in EDITABLE_JOURNAL_STATUSES

    def get_can_post(self, obj) -> bool:
        from apps.finance.services import FinancePostingService

        return obj.status in FinancePostingService.POSTABLE_STATUSES

    def get_can_reverse(self, obj) -> bool:
        from apps.finance.models import JournalStatus

        return (
            obj.status == JournalStatus.POSTED
            and obj.reversed_by_id is None
        )


class JournalSubmitSerializer(serializers.Serializer):
    notes = serializers.CharField(
        required=False, allow_blank=True, default="",
    )


class JournalReverseSerializer(serializers.Serializer):
    posting_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text=(
            "Kosong = tanggal jurnal aslinya. Diisi kalau periode "
            "lamanya sudah ditutup."
        ),
    )

    reason = serializers.CharField(
        help_text=(
            "Wajib. Jurnal pembalik tanpa alasan menghasilkan dua ayat "
            "yang saling meniadakan dan tidak seorang pun tahu kenapa."
        ),
    )


class JournalCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False, allow_blank=True, default="",
    )


class JournalPostAllSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text=(
            "Kosong = seluruh baris yang lolos penyaring aktif. Kunci "
            "ini tidak dikirim sama sekali kalau tidak ada yang "
            "dicentang — array kosong berarti hal yang berbeda."
        ),
    )
