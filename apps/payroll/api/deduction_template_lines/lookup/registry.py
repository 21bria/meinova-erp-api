from apps.framework.lookup import BaseLookup, register_lookup

from apps.payroll.models import DeductionTemplateLine


@register_lookup
class DeductionTemplateLineLookup(BaseLookup):
    name = "deduction-template-lines"
    model = DeductionTemplateLine

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name", "template__code", "template__name"]
    filter_fields = ["template_id"]

    ordering = ["template__code", "sequence", "code"]

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": f"{instance.template.code} · {instance.code} - {instance.name}",
            "code": instance.code,
            "name": instance.name,
            "amount": str(instance.amount),
        }
