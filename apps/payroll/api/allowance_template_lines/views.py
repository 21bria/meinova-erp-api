from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import AllowanceTemplateLineService

from .schema import ALLOWANCE_TEMPLATE_LINE_SCHEMA
from .serializers import AllowanceTemplateLineSerializer


class AllowanceTemplateLineViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Komponen di dalam Allowance Template.

    Layar tersendiri, **bukan** tab di dalam halaman Allowance Template:
    halaman master itu memakai editor dialog, dan mengubahnya jadi
    workspace bertab berarti merombak layar master yang sudah berjalan.
    Kolom Template di daftar ini yang menggantikan pengelompokannya.
    """

    serializer_class = AllowanceTemplateLineSerializer
    service_class = AllowanceTemplateLineService

    framework_module = "payroll/allowance-template-lines"
    schema = ALLOWANCE_TEMPLATE_LINE_SCHEMA

    search_fields = ["code", "name", "template__code", "template__name"]

    filterset_fields = ["template", "basis", "is_taxable", "is_active"]

    ordering = ["template__code", "sequence", "code"]

    ordering_fields = [
        "template__code", "sequence", "code", "name",
        "basis", "amount", "rate", "is_active", "created_at",
    ]

    # Base mencari `service_class.list()`; service payroll memakai
    # `get_queryset()` seperti `BaseMasterService` lain. Tanpa jembatan
    # ini daftarnya melempar AssertionError, bukan 500 yang menjelaskan
    # apa pun.
    def get_queryset(self):
        return AllowanceTemplateLineService.get_queryset()
