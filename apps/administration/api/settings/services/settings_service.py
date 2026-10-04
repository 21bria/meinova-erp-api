"""
Layanan pengaturan.

**Satu baris per company, bukan satu baris per tenant.** `TenantSetting`
dan `PrintSetting` sama-sama `OneToOneField(company)` — jadi tenant
berisi dua belas perusahaan seharusnya punya dua belas baris masing-
masing. Layar lamanya `schema_type="setting"` yang hanya bisa menyunting
**satu** record, dan `get_settings()` mengambilnya lewat `.first()`:
perusahaan mana yang tersunting ditentukan urutan id, dan sebelas
sisanya tidak punya jalan masuk sama sekali.

Karena itu ditambahkan viewset CRUD di sampingnya. Endpoint tunggalnya
**tidak dihapus** — layar Settings yang sekarang masih memakainya, dan
mematikannya berarti halaman itu 404 sebelum penggantinya ada.
"""

from rest_framework.exceptions import ValidationError

from apps.core.services.master import BaseMasterService
from apps.framework.services.company_copy import CompanyCopyMixin

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

# ----------------------------------------------------------------------
# CRUD per company
# ----------------------------------------------------------------------
#
# Yang membuat sebelas perusahaan sisanya akhirnya punya jalan masuk.
# Keduanya `BaseMasterService` biasa — tidak ada logika khusus, yang
# berubah cuma bentuk layarnya: daftar + tombol Add, bukan satu form
# yang diam-diam menyunting baris pertama.


class TenantSettingCrudService(CompanyCopyMixin, BaseMasterService):
    model = TenantSetting

    # Tidak punya `code`/`name` — identitasnya company-nya sendiri.
    copy_code_field = None
    copy_name_field = None

    copy_scope_fields = ["company"]

    copy_rule_fields = [
        "currency",
        "timezone",
        "language",
        "date_format",
        "decimal_separator",
        "thousand_separator",
    ]

    # `BaseMasterViewSet` merakit querysetnya lewat `service_class.list()`,
    # bukan `get_queryset()` — menimpa yang salah menghasilkan 500 berbunyi
    # "must define `queryset`".
    @staticmethod
    def list():
        return (
            TenantSetting.objects
            .select_related("company", "currency")
            .filter(is_deleted=False)
            .order_by("company__name")
        )


class PrintSettingCrudService(CompanyCopyMixin, BaseMasterService):
    model = PrintSetting

    copy_code_field = None
    copy_name_field = None

    copy_scope_fields = ["company"]

    # `logo` sengaja **tidak** ikut. Dua baris yang menunjuk berkas yang
    # sama berarti mengganti logo satu perusahaan mengganti logo
    # perusahaan lain, dan menghapusnya menghapus logo yang satunya —
    # kegagalan yang muncul di dokumen tercetak, jauh dari layar tempat
    # tombolnya ditekan. Lagi pula logo memang berbeda per perusahaan;
    # yang layak disalin cuma tata letaknya.
    copy_rule_fields = [
        "header_text",
        "footer_text",
        "default_paper_size",
        "default_orientation",
        "show_logo",
        "show_footer",
    ]

    @staticmethod
    def list():
        return (
            PrintSetting.objects
            .select_related("company")
            .filter(is_deleted=False)
            .order_by("company__name")
        )
