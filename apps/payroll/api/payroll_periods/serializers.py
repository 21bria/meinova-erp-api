from rest_framework import serializers

from apps.payroll.models import PayrollPeriod


class PayrollPeriodSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    payroll_group_name = serializers.CharField(
        source="payroll_group.name", read_only=True, default=None,
    )

    is_locked = serializers.BooleanField(read_only=True)

    run_count = serializers.SerializerMethodField()

    # Kebalikan `is_locked`, dan sengaja dikirim sebagai field
    # tersendiri: nama yang sama dipakai seluruh resource payroll,
    # jadi layar tidak perlu tahu tiap resource menamai kuncinya apa.
    can_edit = serializers.SerializerMethodField()
    can_save = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = PayrollPeriod
        fields = "__all__"
        read_only_fields = [
            "id", "status", "locked_at", "locked_by",
            "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]

    def get_can_edit(self, instance) -> bool:
        return not instance.is_locked

    def get_can_save(self, instance) -> bool:
        return self.get_can_edit(instance)

    def get_can_delete(self, instance) -> bool:
        # Periode yang sudah punya run tidak bisa dihapus — sama
        # persis dengan yang ditegakkan `before_soft_delete`.
        return not instance.is_locked and self.get_run_count(instance) == 0

    def get_run_count(self, instance) -> int:
        # `runs` sudah di-prefetch viewset-nya; menghitungnya lewat
        # `.count()` di sini akan menerbitkan satu query per baris.
        return len(
            [run for run in instance.runs.all() if not run.is_deleted],
        )
