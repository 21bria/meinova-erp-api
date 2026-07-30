from rest_framework import serializers

from apps.payroll.models import SalaryGrade

class SalaryGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalaryGrade
        fields = "__all__"