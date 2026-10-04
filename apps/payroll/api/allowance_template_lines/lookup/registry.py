from apps.framework.lookup import BaseLookup, register_lookup

from apps.payroll.models import AllowanceTemplateLine


@register_lookup
class AllowanceTemplateLineLookup(BaseLookup):
    name = "allowance-template-lines"
    model = AllowanceTemplateLine

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name", "template__code", "template__name"]
    filter_fields = ["template_id"]

    ordering = ["template__code", "sequence", "code"]

    @classmethod
    def serialize(cls, instance):
        # `code`, `name`, dan `is_taxable` ikut dikirim karena
        # `PayrollInput` meng-`autofill` ketiganya begitu komponen
        # dipilih. Kunci yang tidak diserialisasi di sini akan
        # dilewati form — dan field tujuannya tinggal kosong.
        return {
            "value": instance.pk,
            "label": f"{instance.template.code} · {instance.code} - {instance.name}",
            "code": instance.code,
            "name": instance.name,
            "is_taxable": instance.is_taxable,
            "amount": str(instance.amount),
        }
