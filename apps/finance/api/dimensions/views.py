from django.core.exceptions import ValidationError

from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.core.services.master import BaseMasterService
from apps.finance.models import AccountingDimension

from .schema import ACCOUNTING_DIMENSION_SCHEMA
from .serializers import AccountingDimensionSerializer


class AccountingDimensionService(BaseMasterService):
    model = AccountingDimension

    @staticmethod
    def list():
        return (
            AccountingDimension.objects
            .filter(is_deleted=False)
            .order_by("sort_order", "name")
        )

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        if instance.is_core:
            # Kodenya adalah nama kolom pada `JournalLine`. Mengganti
            # kode dimensi inti memutus setiap kebijakan akuntansi yang
            # menyebutnya, dan putusnya tidak menghasilkan error —
            # jurnalnya tetap terbit, cuma tanpa dimensi itu.
            data.pop("code", None)
            data.pop("is_core", None)

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        if instance.is_core:
            raise ValidationError({
                "code": (
                    f"'{instance.name}' adalah dimensi bawaan yang "
                    "tersimpan sebagai kolom pada baris jurnal dan tidak "
                    "bisa dihapus. Nonaktifkan saja kalau tidak dipakai."
                ),
            })


class AccountingDimensionViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = AccountingDimensionSerializer
    service_class = AccountingDimensionService

    framework_module = "finance/accounting-dimensions"
    schema = ACCOUNTING_DIMENSION_SCHEMA

    # Tidak ada cakupan data: daftar dimensi adalah konfigurasi
    # se-tenant, bukan data per perusahaan. Yang menjaganya izin model.
    data_scope = None

    search_fields = ["code", "name", "description"]
    filterset_fields = ["data_type", "is_required", "is_core", "is_active"]
    ordering_fields = ["code", "name", "sort_order"]
    ordering = ["sort_order", "name"]
