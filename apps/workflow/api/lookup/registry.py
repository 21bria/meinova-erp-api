from apps.framework.lookup import BaseLookup, register_lookup

from apps.workflow.models import WorkflowDefinition


@register_lookup
class WorkflowDefinitionLookup(BaseLookup):
    """
    Dropdown alur, dipakai form Workflow Step.

    Disaring per modul/jenis dokumen supaya layar setting yang sedang
    mengurus cuti tidak menampilkan seluruh alur tenant — **dan
    parameter yang tidak terdaftar di `filter_fields` diabaikan
    diam-diam**, itu penyebab klasik dropdown yang "tidak mau
    tersaring".
    """

    name = "workflow-definitions"
    model = WorkflowDefinition

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
        "module",
        "document_type",
    ]

    filter_fields = [
        "module",
        "document_type",
        "status",
        "company_id",
    ]

    ordering = [
        "module",
        "document_type",
        "code",
    ]
