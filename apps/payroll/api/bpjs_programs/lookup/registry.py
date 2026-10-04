from apps.framework.lookup import BaseLookup, register_lookup
from apps.payroll.models import BpjsProgram


@register_lookup
class BpjsProgramLookup(BaseLookup):
    name = "bpjs-programs"
    model = BpjsProgram

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name"]

    ordering = ["code"]
