from rest_framework import serializers

from apps.payroll.models import PayrollPolicy, PayrollPolicyToggle


class PayrollPolicySerializer(serializers.ModelSerializer):
    """
    Kolom tabel membaca **kalimat**, bukan nilai enumnya.

    Kosong juga bukan nilai yang hilang melainkan keadaan — "ikut
    kebijakan perusahaan" — dan sel kosong terbaca seperti data yang
    gagal termuat.
    """

    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )

    pay_basis_label = serializers.SerializerMethodField()
    proration_method_label = serializers.SerializerMethodField()
    attendance_deduction_method_label = serializers.SerializerMethodField()
    daily_rate_method_label = serializers.SerializerMethodField()
    pay_paid_leave_label = serializers.SerializerMethodField()
    rules_summary = serializers.SerializerMethodField()

    INHERITED = "Ikut perusahaan"

    def get_pay_basis_label(self, instance) -> str:
        return instance.get_pay_basis_display()

    def get_proration_method_label(self, instance) -> str:
        if instance.is_daily:
            return "-"

        if not instance.proration_method:
            return self.INHERITED

        return instance.get_proration_method_display()

    def get_attendance_deduction_method_label(self, instance) -> str:
        if instance.is_daily:
            return "-"

        if not instance.attendance_deduction_method:
            return self.INHERITED

        return instance.get_attendance_deduction_method_display()

    def get_daily_rate_method_label(self, instance) -> str:
        if not instance.is_daily:
            return "-"

        if not instance.daily_rate_method:
            return "Belum ditentukan"

        return instance.get_daily_rate_method_display()

    def get_pay_paid_leave_label(self, instance) -> str:
        if not instance.is_daily:
            return "-"

        if instance.pays_paid_leave is None:
            return "Belum ditentukan"

        return "Dibayar" if instance.pays_paid_leave else "Tidak dibayar"

    def get_rules_summary(self, instance) -> str:
        """
        Isi kebijakan ini sebagai beberapa baris kalimat.

        Ada supaya "apa bedanya kebijakan ini dengan default
        perusahaan" bisa dijawab dari daftarnya, tanpa membuka form dan
        membandingkan tujuh kolom satu per satu.
        """
        if instance.is_daily:
            rows = [
                f"Upah sehari: {self.get_daily_rate_method_label(instance)}",
            ]

            if instance.daily_rate_divisor:
                rows.append(f"Pembagi: {instance.daily_rate_divisor}")

            rows.append(
                f"Hari cuti dibayar: "
                f"{self.get_pay_paid_leave_label(instance)}",
            )
            rows.append(
                "Tidak ada prorata dan tidak ada potongan "
                "ketidakhadiran — hari yang tidak dibayar memang tidak "
                "membentuk upah.",
            )

            return "\n".join(rows)

        def toggle(value: str) -> str:
            if value == PayrollPolicyToggle.ON:
                return "Ya"

            if value == PayrollPolicyToggle.OFF:
                return "Tidak"

            return self.INHERITED

        return "\n".join(
            [
                f"Prorata gaji: {self.get_proration_method_label(instance)}",
                f"Prorata saat masuk: {toggle(instance.prorate_on_join)}",
                f"Prorata saat berhenti: "
                f"{toggle(instance.prorate_on_termination)}",
                f"Pembagi potongan: "
                f"{self.get_attendance_deduction_method_label(instance)}",
                f"Potong alpa: {toggle(instance.deduct_absence)}",
                f"Potong cuti tidak dibayar: "
                f"{toggle(instance.deduct_unpaid_leave)}",
            ],
        )

    class Meta:
        model = PayrollPolicy
        fields = "__all__"
