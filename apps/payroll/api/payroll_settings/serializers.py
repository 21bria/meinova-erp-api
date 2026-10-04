from rest_framework import serializers

from apps.payroll.models import PayrollSetting


class PayrollSettingSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )

    proration_method_label = serializers.CharField(
        source="get_proration_method_display", read_only=True, default="",
    )

    # Kosong bukan nilai yang hilang, melainkan keadaan: perusahaan
    # belum memilih. Kolom tabel harus mengatakannya, bukan menampilkan
    # sel kosong yang terbaca seperti data gagal termuat.
    attendance_deduction_method_label = serializers.SerializerMethodField()

    def get_attendance_deduction_method_label(self, instance) -> str:
        if not instance.attendance_deduction_method:
            return "Belum ditentukan"

        return instance.get_attendance_deduction_method_display()

    class Meta:
        model = PayrollSetting
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
