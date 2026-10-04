from rest_framework import serializers


class LedgerFilterSerializer(serializers.Serializer):
    """
    Penyaring bersama Trial Balance dan Account Ledger.

    Satu serializer untuk dua laporan: tombol filter yang sama di dua
    layar harus berarti hal yang sama, dan dua penafsir yang terpisah
    adalah cara membuat drill-down dari Trial Balance ke Account Ledger
    mendarat pada angka yang berbeda.
    """

    company_id = serializers.IntegerField()

    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)

    fiscal_year_id = serializers.IntegerField(required=False, allow_null=True)
    period_id = serializers.IntegerField(required=False, allow_null=True)

    account_id = serializers.IntegerField(required=False, allow_null=True)
    account_root_id = serializers.IntegerField(required=False, allow_null=True)
    account_type = serializers.CharField(required=False, allow_blank=True)

    branch_id = serializers.IntegerField(required=False, allow_null=True)
    location_id = serializers.IntegerField(required=False, allow_null=True)
    division_id = serializers.IntegerField(required=False, allow_null=True)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    section_id = serializers.IntegerField(required=False, allow_null=True)
    cost_center_id = serializers.IntegerField(required=False, allow_null=True)

    include_zero = serializers.BooleanField(required=False, default=False)

    def to_filters(self, extra_params=None):
        from apps.finance.services import LedgerFilters

        data = dict(self.validated_data)

        # Dimensi tambahan dikirim sebagai `dim.<kode>=<nilai>`.
        # Awalannya wajib: tanpa itu, parameter yang salah ketik akan
        # terbaca sebagai nama dimensi dan laporannya diam-diam
        # menyaring ke nol baris.
        dimensions = tuple(
            (key[4:], value)
            for key, value in (extra_params or {}).items()
            if key.startswith("dim.") and value
        )

        return LedgerFilters(
            company_id=data["company_id"],
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            fiscal_year_id=data.get("fiscal_year_id"),
            period_id=data.get("period_id"),
            account_id=data.get("account_id"),
            account_root_id=data.get("account_root_id"),
            account_type=data.get("account_type") or None,
            branch_id=data.get("branch_id"),
            location_id=data.get("location_id"),
            division_id=data.get("division_id"),
            department_id=data.get("department_id"),
            section_id=data.get("section_id"),
            cost_center_id=data.get("cost_center_id"),
            dimensions=dimensions,
            include_zero=data.get("include_zero", False),
        )
