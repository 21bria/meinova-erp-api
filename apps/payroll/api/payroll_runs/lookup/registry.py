from apps.framework.lookup import BaseLookup, register_lookup

from apps.payroll.models import PayrollRun


@register_lookup
class PayrollRunLookup(BaseLookup):
    name = "payroll-runs"
    model = PayrollRun

    value_field = "id"
    label_field = "document_number"

    search_fields = ["document_number", "name", "period__code"]
    filter_fields = ["period_id", "company_id", "status"]

    ordering = ["-created_at"]

    data_scope = {"company": "company"}

    # Tabelnya menuntut `payroll.view_payrollrun`
    # (`PayrollRunViewSet.require_view_permission`), jadi dropdown-nya
    # menuntut yang sama. Tanpa ini run yang tidak muncul di daftar
    # tetap bisa dipilih di filter dashboard — dan nomor dokumennya
    # sendiri sudah memberi tahu ada berapa run di perusahaan itu.
    require_view_permission = True

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": (
                f"{instance.document_number or instance.pk} - "
                f"{instance.period.name}"
            ),
            "period": instance.period_id,
            "status": instance.status,
        }
