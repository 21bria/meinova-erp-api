from rest_framework import serializers

from apps.finance.models import FiscalYear


class FiscalYearSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    period_count = serializers.SerializerMethodField()

    can_generate_periods = serializers.SerializerMethodField()

    class Meta:
        model = FiscalYear
        fields = "__all__"

        read_only_fields = [
            "company_name",
            "status_label",
            "period_count",
            "can_generate_periods",
            "closed_at",
            "closed_by",
        ]

    def get_period_count(self, obj) -> int:
        annotated = getattr(obj, "period_total", None)

        if annotated is not None:
            return annotated

        return obj.periods.filter(is_deleted=False).count()

    def get_can_generate_periods(self, obj) -> bool:
        """
        Tombol Generate Periods hanya berarti selama belum ada
        periodenya — menjalankannya dua kali ditolak service.

        Dijawab server, bukan disimpulkan layar dari `period_count == 0`:
        aturannya tinggal di `FiscalYearService.generate_periods`, dan
        salinannya di frontend akan tertinggal begitu syaratnya
        bertambah.
        """
        return self.get_period_count(obj) == 0


class GeneratePeriodsSerializer(serializers.Serializer):
    count = serializers.IntegerField(
        min_value=1,
        max_value=24,
        default=12,
        help_text=(
            "Jumlah periode. Dua belas cuma bawaan — kuartalan kirim 4, "
            "empat mingguan kirim 13."
        ),
    )
