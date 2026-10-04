from rest_framework.permissions import IsAuthenticated

from apps.framework.builders import action
from apps.framework.services.company_copy import CompanyCopyViewSetMixin
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.framework.views.setting import BaseSettingAPIView

from apps.administration.api.settings.serializers.settings import (
    TenantSettingSerializer,
    SystemSettingSerializer,
    PrintSettingSerializer,
)

from apps.administration.api.settings.services.settings_service import (
    TenantSettingService,
    SystemSettingService,
    PrintSettingService,
    TenantSettingCrudService,
    PrintSettingCrudService,
)


class TenantSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TenantSettingSerializer
    service_class = TenantSettingService

    framework_module = "administration/settings/tenant-setting"
    schema_type = "setting"

    schema = {
        "title": "Tenant Settings",
        "description": "Configure tenant-specific application settings.",
        "endpoint": "/api/administration/settings/tenant/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings()


class SystemSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SystemSettingSerializer
    service_class = SystemSettingService
    
    framework_module = "administration/settings/system-setting"
    schema_type = "setting"
    schema = {
        "title": "System Settings",
        "description": "Configure global system settings.",
        "endpoint": "/api/administration/settings/system/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings()


class PrintSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PrintSettingSerializer
    service_class = PrintSettingService
    framework_module = "administration/settings/print-setting"
    schema_type = "setting"
    schema = {
        "title": "Print Settings",
        "description": "Configure document and printing settings.",
        "endpoint": "/api/administration/settings/print/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings()

# ----------------------------------------------------------------------
# CRUD per company
# ----------------------------------------------------------------------
#
# `TenantSetting` dan `PrintSetting` sama-sama `OneToOneField(company)`,
# jadi tenant berisi dua belas perusahaan seharusnya punya dua belas
# baris. Layar `setting` di atas hanya bisa menyunting **satu** —
# diambil `.first()`, jadi perusahaan mana yang tersunting ditentukan
# urutan id dan sebelas sisanya tidak punya jalan masuk sama sekali.
#
# Endpoint tunggalnya sengaja dibiarkan hidup sebagai jalur transisi:
# layar Settings yang sekarang masih memakainya.


COMPANY_FIELD = {
    "lookup_endpoint": "/api/administration/organization/lookup/companies/",
    "display_key": "company_name",
    "required": True,
    "filter": {"group": "quick", "order": 10},
    "order": 10,
}


class TenantSettingViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = TenantSettingSerializer
    service_class = TenantSettingCrudService

    framework_module = "administration/settings/tenant-settings"
    schema_type = "crud"

    ordering = ["company__name"]
    search_fields = ["company__name", "timezone", "language"]
    filterset_fields = ["company", "is_active"]

    schema = {
        "title": "Tenant Settings",
        "description": (
            "Zona waktu, bahasa, dan format angka — satu baris per "
            "perusahaan."
        ),
        "endpoint": "/api/administration/settings/tenant-settings/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
            "columns": 2,
        },
        "actions": [
            action.copy_to_companies(
                endpoint="/api/administration/settings/tenant-settings/",
            ),
        ],
        "fields": {
            "company": COMPANY_FIELD,
            "currency": {
                "lookup_endpoint": (
                    "/api/administration/currency/lookup/currencies/"
                ),
                "display_key": "currency_name",
                "order": 20,
            },
        },
    }


class PrintSettingViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = PrintSettingSerializer
    service_class = PrintSettingCrudService

    framework_module = "administration/settings/print-settings"
    schema_type = "crud"

    ordering = ["company__name"]
    search_fields = ["company__name", "header_text", "footer_text"]
    filterset_fields = ["company", "is_active"]

    schema = {
        "title": "Print Settings",
        "description": (
            "Kop, logo, dan ukuran kertas dokumen cetak — satu baris "
            "per perusahaan."
        ),
        "endpoint": "/api/administration/settings/print-settings/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
            "columns": 2,
        },
        "actions": [
            action.copy_to_companies(
                endpoint="/api/administration/settings/print-settings/",
                help_text=(
                    "Logo tidak ikut disalin — tata letaknya saja. Dua "
                    "perusahaan yang menunjuk berkas logo yang sama "
                    "berarti mengganti satu mengganti keduanya."
                ),
            ),
        ],
        "fields": {
            "company": COMPANY_FIELD,
            "default_paper_size": {
                "type": "select",
                "options": [
                    {"label": "A4", "value": "A4"},
                    {"label": "A5", "value": "A5"},
                    {"label": "Letter", "value": "LETTER"},
                    {"label": "Legal", "value": "LEGAL"},
                ],
                "order": 20,
            },
            "default_orientation": {
                "type": "select",
                "options": [
                    {"label": "Portrait", "value": "PORTRAIT"},
                    {"label": "Landscape", "value": "LANDSCAPE"},
                ],
                "order": 30,
            },
        },
    }
