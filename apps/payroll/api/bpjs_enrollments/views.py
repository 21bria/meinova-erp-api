from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE
from apps.payroll.services import BpjsEnrollmentService

from .schema import BPJS_ENROLLMENT_SCHEMA
from .serializers import BpjsEnrollmentSerializer


class BpjsEnrollmentViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Kepesertaan pegawai per program BPJS, bertanggal berlaku.

    **Barisnya per orang, dan isinya nomor kepesertaan BPJS** — nomor
    identitas nasional, bukan angka administratif. Sampai sebelum ini
    tabelnya tidak punya `data_scope` sama sekali, jadi siapa pun yang
    bisa login membaca nomor kepesertaan seluruh tenant lewat
    `GET /api/payroll/bpjs-enrollments/`. Cakupannya sekarang mengikuti
    Employee lewat relasi `employee`, sama seperti tabel anak kartu
    pegawai lainnya.
    """

    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    data_scope = EMPLOYEE_CHILD_SCOPE

    serializer_class = BpjsEnrollmentSerializer
    service_class = BpjsEnrollmentService

    framework_module = "payroll/bpjs-enrollments"
    schema = BPJS_ENROLLMENT_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "membership_number",
        "program__code",
    ]

    filterset_fields = ["employee", "program", "participates", "is_active"]

    ordering = ["employee", "program__sequence", "-enrolled_from"]

    ordering_fields = [
        "enrolled_from", "enrolled_to", "participates", "is_active",
        "created_at",
    ]

    def get_queryset(self):
        return BpjsEnrollmentService.get_queryset()
