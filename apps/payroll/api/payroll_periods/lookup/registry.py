from apps.framework.lookup import BaseLookup, register_lookup

from apps.payroll.models import PayrollPeriod


@register_lookup
class PayrollPeriodLookup(BaseLookup):
    name = "payroll-periods"
    model = PayrollPeriod

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name"]
    filter_fields = ["company_id", "payroll_group_id", "status"]

    ordering = ["-start_date", "code"]

    # Periode membawa nama perusahaan dan total gajinya di layar lain,
    # jadi dropdown-nya ikut disaring cakupan data. Dropdown adalah
    # jalur bocor yang paling gampang terlewat.
    data_scope = {"company": "company"}

    # Sama dengan dropdown run: cakupannya dihitung per izin, dan
    # izinnya `payroll.view_payrollperiod`. Seed Stage 3B memberikannya
    # ke role yang sudah memegang `payroll.view_payrollrun` — periode
    # tidak bisa dibaca tanpa run-nya, dan sebaliknya.
    require_view_permission = True

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": f"{instance.code} - {instance.name}",
            "code": instance.code,
            "company": instance.company_id,
            "start_date": str(instance.start_date),
            "end_date": str(instance.end_date),
            "status": instance.status,
        }
