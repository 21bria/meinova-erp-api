from rest_framework import serializers

from apps.payroll.models import PayrollInput


class PayrollInputSerializer(serializers.ModelSerializer):
    period_name = serializers.CharField(
        source="period.name", read_only=True, default=None,
    )
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True, default=None,
    )
    employee_number = serializers.CharField(
        source="employee.employee_number", read_only=True, default=None,
    )
    allowance_line_name = serializers.CharField(
        source="allowance_line.name", read_only=True, default=None,
    )
    deduction_line_name = serializers.CharField(
        source="deduction_line.name", read_only=True, default=None,
    )

    effective_side = serializers.CharField(read_only=True)
    effective_code = serializers.CharField(read_only=True)
    effective_name = serializers.CharField(read_only=True)
    effective_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True,
    )

    # Periode yang sudah Finalized menolak seluruh penyuntingan
    # input-nya — sama seperti `PayrollInputService.assert_period_open`.
    # Tanpa ini tombol Edit/Delete tetap tampil di daftar dan tiap
    # penekanan berakhir di penolakan API.
    can_edit = serializers.SerializerMethodField()
    can_save = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = PayrollInput
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]

    def get_can_edit(self, instance) -> bool:
        period = instance.period

        return period is None or not period.is_locked

    def get_can_save(self, instance) -> bool:
        return self.get_can_edit(instance)

    def get_can_delete(self, instance) -> bool:
        return self.get_can_edit(instance)
