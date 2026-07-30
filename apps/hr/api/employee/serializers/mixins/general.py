from rest_framework import serializers

class EmployeeGeneralFieldsMixin(serializers.Serializer):
    full_name = serializers.CharField(
        read_only=True,
    )
    display_name = serializers.CharField(
        read_only=True,
    )