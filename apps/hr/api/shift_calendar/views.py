"""
Endpoint Shift Calendar.

Dua resource, dan pembagiannya mengikuti dua keputusan berbeda:

* ``shift-assignments``  — menetapkan shift untuk sebuah rentang tanggal
* ``shift-calendar``     — membaca hasil efektifnya per tanggal

Yang kedua **read-only dengan sengaja**. Kalender adalah tampilan dari
tiga sumber yang sudah ada (rotation, penugasan shift, master Shift);
memberinya jalur tulis berarti ada tempat keempat yang bisa mengubah
jadwal tanpa lewat salah satu dari ketiganya.
"""

from __future__ import annotations

from datetime import date, datetime

from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE
from apps.hr.models import EmployeeShiftAssignment

from .schema import SHIFT_ASSIGNMENT_SCHEMA
from .scope import can_adjust_shift, viewable_employees
from .serializers import (
    EmployeeShiftAssignmentSerializer,
    ShiftCalendarSerializer,
)
from .services import (
    EmployeeShiftAssignmentService,
    ShiftCalendarService,
)


# Cakupan baris. **Dipinjam**, bukan disalin: dua layar yang menampilkan
# orang yang sama tidak boleh menampilkan jumlah yang berbeda, dan dua
# salinan peta yang harus dijaga tetap sama adalah persis cara selisih
# semacam itu lahir di salah satunya saja. Keduanya dulu ditulis ulang
# di sini, huruf per huruf sama dengan milik `apps.hr.api.employee.scope`.
SHIFT_ASSIGNMENT_SCOPE = EMPLOYEE_CHILD_SCOPE


class EmployeeShiftAssignmentViewSet(ServiceWriteMixin, BaseMasterViewSet):
    framework_module = "hr/shift-assignments"
    schema = SHIFT_ASSIGNMENT_SCHEMA

    service_class = EmployeeShiftAssignmentService
    serializer_class = EmployeeShiftAssignmentSerializer

    data_scope = SHIFT_ASSIGNMENT_SCOPE

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "shift__code",
        "shift__name",
        "reason",
    ]

    filterset_fields = [
        "employee",
        "shift",
        "layer",
        "kind",
        "is_active",
    ]

    ordering = ["employee", "start_date", "layer"]

    def get_queryset(self):
        return (
            EmployeeShiftAssignment.objects
            .select_related(
                "employee",
                "employee__organization",
                "shift",
            )
            .filter(is_deleted=False)
        )


# ----------------------------------------------------------------------
# Kalender
# ----------------------------------------------------------------------


def _parse_date(value, label):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise drf_serializers.ValidationError(
            {label: "Format tanggal harus YYYY-MM-DD."},
        )


def resolve_calendar_range(params, *, today: date | None = None):
    """
    Rentang kalender dari query string: `month=YYYY-MM`, atau
    `start`/`end`, atau bulan berjalan.

    Dipakai bersama `ShiftCalendarView` dan `GET /api/me/schedule/`.
    Hanya membaca parameter rentang — tidak ada satu pun yang menyebut
    pegawai, jadi pemanggil Self Service tidak mewarisi jalur identitas
    apa pun dari sini.

    `today` bawaannya `date.today()`, persis perilaku lama endpoint HR;
    Self Service mengirim hari menurut jam dinding kantor.
    """
    month = params.get("month")

    if month:
        try:
            year_text, month_text = month.split("-")

            return ShiftCalendarService.month_range(
                int(year_text),
                int(month_text),
            )
        except (ValueError, TypeError):
            raise drf_serializers.ValidationError(
                {"month": "Format bulan harus YYYY-MM."},
            )

    if params.get("start"):
        start = _parse_date(params.get("start"), "start")
        end = _parse_date(params.get("end") or params.get("start"), "end")

        return start, end

    today = today or date.today()

    return ShiftCalendarService.month_range(today.year, today.month)


def build_calendar_payload(employee, start: date, end: date) -> dict:
    """
    Kalender satu pegawai yang sudah **diputuskan boleh dibaca**, dalam
    bentuk balasan API. Penjagaan barisnya tanggung jawab pemanggil.
    """
    try:
        payload = ShiftCalendarService.build(
            employee=employee,
            start=start,
            end=end,
        )
    except DjangoValidationError as error:
        raise drf_serializers.ValidationError(
            getattr(error, "message_dict", None) or {"detail": str(error)},
        )

    return ShiftCalendarSerializer(payload).data


class ShiftCalendarView(APIView):
    """
    `GET /api/hr/shift-calendar/?employee=<id>&month=YYYY-MM`

    Atau `?start=YYYY-MM-DD&end=YYYY-MM-DD`. Tanpa keduanya: bulan
    berjalan — layar kalender yang dibuka tanpa parameter harus tetap
    menampilkan sesuatu, dan bulan ini adalah satu-satunya bawaan yang
    tidak perlu dijelaskan.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee_id = request.query_params.get("employee")

        if not employee_id:
            raise drf_serializers.ValidationError(
                {"employee": "Parameter employee wajib diisi."},
            )

        # Cakupan baris ditegakkan di sini, bukan di serializer:
        # kalender orang lain adalah data pegawai, dan menyaringnya
        # setelah dirakit berarti query-nya sudah jalan lebih dulu.
        #
        # **Ini satu-satunya penjagaan pada endpoint ini**, dan ia
        # menjaga id yang diketik tangan sama seperti id yang dipilih
        # dari dropdown — `?employee=` boleh berisi apa saja. Aturannya
        # sendiri ada di `scope.viewable_employees`, dipakai bersama
        # endpoint `access/` dan penjagaan jalur tulis; satu salinan
        # lagi di sini adalah cara dua jalur mulai menjawab berbeda.
        queryset = viewable_employees(request.user)

        # `?employee=me` — pegawai biasa membuka kalendernya sendiri
        # tanpa perlu tahu id-nya, dan tanpa layar yang menyodorkan
        # dropdown berisi satu nama. Diresolusi dari akun yang meminta,
        # jadi ia bukan jalan pintas ke data siapa pun.
        if str(employee_id).strip().lower() == "me":
            employee_id = getattr(
                getattr(request.user, "employee_profile", None),
                "pk",
                None,
            )

            if employee_id is None:
                raise drf_serializers.ValidationError(
                    {
                        "employee": (
                            "Akun ini belum ditautkan ke data pegawai "
                            "mana pun. Hubungi HR untuk menghubungkan "
                            "akun Anda ke kartu pegawai."
                        ),
                    },
                )

        else:
            # `?employee=abc` dulu jatuh sebagai `ValueError` dari ORM —
            # 500 untuk sesuatu yang murni salah ketik di URL.
            try:
                employee_id = int(employee_id)
            except (TypeError, ValueError):
                raise drf_serializers.ValidationError(
                    {"employee": "Parameter employee harus berupa id pegawai."},
                )

        employee = (
            queryset
            .select_related(
                "organization",
                "organization__company",
                "organization__location",
                "employment",
                "employment__shift",
                "employment__work_schedule",
                "employment__employee_group",
                "employment__roster_policy",
                "employment__roster_crew",
            )
            .filter(pk=employee_id)
            .first()
        )

        if employee is None:
            raise drf_serializers.ValidationError(
                {"employee": "Pegawai tidak ditemukan atau di luar cakupan."},
            )

        start, end = resolve_calendar_range(request.query_params)

        return success_response(
            data=build_calendar_payload(employee, start, end),
            message="Shift calendar retrieved.",
        )


class ShiftCalendarAccessView(APIView):
    """
    `GET /api/hr/shift-calendar/access/`

    Satu jawaban untuk pertanyaan yang harus dijawab **sebelum**
    kalender bisa digambar: pegawai mana yang boleh dibuka orang ini,
    dan apakah ia boleh mengubahnya.

    **Kenapa backend yang menjawabnya, bukan frontend yang menyimpulkan
    dari daftar dropdown.** Layar Shift Calendar melayani empat kursi
    yang berbeda lewat satu pintu — pegawai (dirinya sendiri), atasan
    langsung (dirinya + timnya), Admin Department/Section (cakupan
    organisasinya), dan HR (Data Permission-nya). Membedakannya di
    frontend berarti menyalin aturan cakupan ke tempat kedua, dan
    salinan kedua akan menyimpang. Yang dikirim di sini **kesimpulannya**
    — bukan aturannya.

    Ini bukan penjagaan dan tidak menggantikan satu pun: endpoint
    kalender tetap memeriksa ulang tiap request, dan `ModelPermission`
    tetap yang menolak tulisan. Yang dilakukan endpoint ini cuma
    membuat layarnya tidak menyodorkan pilihan yang pasti ditolak.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        from apps.hr.models import Employee

        # Basis yang **sama** dengan dropdown `employees/lookup/`
        # (aktif + belum dihapus). Kalau berbeda, `selector_required`
        # bisa berbunyi "ada lebih dari satu" untuk daftar yang di
        # layarnya cuma berisi satu nama — dan pemakainya melihat
        # penyaring yang tidak menyaring apa pun.
        visible = viewable_employees(
            user,
            queryset=Employee.objects.filter(
                is_active=True,
                is_deleted=False,
            ),
        )

        # Dibatasi dua, bukan `count()` penuh: yang perlu dijawab cuma
        # "lebih dari satu orang?", dan menghitung sebelas ribu baris
        # untuk menjawab itu adalah query yang dibayar tiap kali layar
        # dibuka.
        sample = list(
            visible
            .select_related("organization", "organization__location")
            .order_by("first_name", "last_name")[:2]
        )

        self_employee = getattr(user, "employee_profile", None)

        # Yang dipilihkan: dirinya sendiri kalau ia memang boleh
        # dilihat, kalau tidak satu-satunya orang yang terlihat. Meja
        # yang cakupannya luas tidak dipilihkan siapa pun — menebak
        # salah satu dari tiga puluh nama lebih buruk daripada dropdown
        # kosong yang jelas menunggu dipilih.
        #
        # `not sample` adalah cabang yang paling gampang terlewat, dan
        # ia nyata: **pegawai nonaktif yang akunnya masih hidup.**
        # Daftar di atas menyaring `is_active=True` (basisnya dropdown),
        # sementara endpoint kalender hanya menyaring `is_deleted` —
        # jadi ia tidak muncul di daftar tapi kalendernya tetap boleh
        # dibuka. Tanpa cabang ini layarnya berbunyi "akun belum
        # ditautkan ke data pegawai", dan itu **salah**: akunnya
        # tertaut, orangnya yang sudah tidak aktif.
        default = None

        if self_employee is not None and (
            not sample
            or any(row.pk == self_employee.pk for row in sample)
        ):
            default = self_employee
        elif len(sample) == 1:
            default = sample[0]

        return success_response(
            data={
                "self_employee": _employee_brief(self_employee),
                "default_employee": _employee_brief(default),
                # `False` = orang ini hanya boleh melihat satu kalender,
                # jadi layarnya tidak perlu menyodorkan penyaring
                # pegawai sama sekali.
                "selector_required": len(sample) > 1,
                "can_adjust": can_adjust_shift(user),
            },
            message="Shift calendar access retrieved.",
        )


def _employee_brief(employee):
    if employee is None:
        return None

    organization = getattr(employee, "organization", None)
    location = getattr(organization, "location", None)

    return {
        "id": employee.pk,
        "employee_number": employee.employee_number,
        "name": employee.full_name,
        "location": getattr(location, "name", None),
    }
