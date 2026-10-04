from rest_framework import serializers

from apps.hr.models import EmployeeReminderPolicy


class EmployeeReminderPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeReminderPolicy
        fields = "__all__"

    def validate(self, attrs):
        # `Model.clean()` yang memegang aturannya (ambang nol pada
        # pengingat yang menyala), dan dijalankan di sini supaya
        # pesannya sampai ke form sebagai error per field — bukan 500.
        instance = self.instance

        for name, value in attrs.items():
            setattr(instance, name, value)

        instance.clean()

        return attrs
