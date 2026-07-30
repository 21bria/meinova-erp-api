from rest_framework.exceptions import ValidationError

from apps.administration.models import (
    Company,
    TenantSetting,
    SystemSetting,
    PrintSetting,
)


class TenantSettingService:

    @staticmethod
    def list():
        return TenantSetting.objects.select_related(
            "company",
            "currency",
        )

    @staticmethod
    def get_settings():
        setting = (
            TenantSetting.objects
            .select_related("company", "currency")
            .first()
        )

        if setting:
            return setting

        company = Company.objects.first()

        if company is None:
            raise ValidationError({
                "detail": "No company found. Please create a company first.",
            })

        return TenantSetting.objects.create(
            company=company,
            timezone="Asia/Jakarta",
            language="id",
            date_format="DD/MM/YYYY",
            decimal_separator=",",
            thousand_separator=".",
        )


class SystemSettingService:

    @staticmethod
    def list():
        return SystemSetting.objects.order_by("key")

    @staticmethod
    def get_settings():
        setting = (
            SystemSetting.objects
            .order_by("key")
            .first()
        )

        if setting:
            return setting

        return SystemSetting.objects.create(
            key="system",
            value={},
            description="Default System Settings",
        )


class PrintSettingService:

    @staticmethod
    def list():
        return PrintSetting.objects.select_related("company")

    @staticmethod
    def get_settings():
        setting = (
            PrintSetting.objects
            .select_related("company")
            .first()
        )

        if setting:
            return setting

        company = Company.objects.first()

        if company is None:
            raise ValidationError({
                "detail": "No company found. Please create a company first.",
            })

        return PrintSetting.objects.create(
            company=company,
        )