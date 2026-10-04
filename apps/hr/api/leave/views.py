from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date

from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, PermissionDenied

from apps.core.responses.api import created_response, success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.write_scope import (
    EmployeeSubjectWriteGuardMixin,
    assert_employee_writable,
)

from apps.hr.api.leave.calculator import LeaveDayCalculator
from apps.hr.models import Employee, EmployeeLeave, LeaveBalance
from apps.hr.models.leave import LeaveStatus
from apps.workflow.services import WorkflowService

from .schema import LEAVE_BALANCE_SCHEMA, LEAVE_SCHEMA
from .scope import LEAVE_DATA_SCOPE
from .serializers import EmployeeLeaveSerializer, LeaveBalanceSerializer
from .services import EmployeeLeaveService, LeaveBalanceService


# Kemampuan mencatat cuti tanpa alur persetujuan. Dideklarasikan di
# `EmployeeLeave.Meta.permissions`, jadi ia izin Django biasa yang bisa
# dicentang per tenant di layar Roles.
RECORD_PERMISSION = "hr.record_employeeleave"


def parse_date_value(raw):
    """
    Tanggal dari form yang belum lengkap boleh saja tidak terbaca.

    Mengembalikan None, bukan melempar: layar Create memanggil ini pada
    setiap ketikan, dan satu tanggal setengah diketik tidak boleh
    membalas 400 ke layar yang sedang diisi orangnya.
    """
    if not raw:
        return None

    try:
        return parse_date(str(raw)[:10])
    except (ValueError, TypeError):
        return None


class EmployeeLeaveViewSet(
    # `employee` di body dijaga cakupan tulis — create tidak pernah
    # melewati `filter_queryset()`. Lihat `employee/write_scope.py`.
    EmployeeSubjectWriteGuardMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Penyaringan data per baris (kewenangan `RoleAssignment`). Petanya ada di
    # `scope.py` karena serializer membaca peta yang **sama** untuk
    # menjawab `can_edit` — dua salinan yang boleh berbeda berarti layar
    # dan API tidak sepakat soal siapa boleh menyunting apa.
    data_scope = LEAVE_DATA_SCOPE

    # Peserta alur boleh **membaca** dokumen yang ditagihkan kepadanya,
    # sekalipun cakupan datanya cuma "milik sendiri". Atasan langsung
    # lazimnya begitu, dan tanpa ini email "menunggu persetujuan Anda"
    # mendarat di 404 yang berbunyi seperti dokumennya hilang.
    #
    # Membaca dan menjalankan keputusan alurnya saja — menyunting isinya
    # tetap jatuh ke cakupan datanya sendiri. Lihat
    # `BaseMasterViewSet._widen_for_workflow_participants`.
    workflow_document = (
        EmployeeLeaveService.WORKFLOW_MODULE,
        EmployeeLeaveService.WORKFLOW_DOCUMENT_TYPE,
    )

    # Pencatatan administratif punya izinnya sendiri, jadi cakupan
    # barisnya juga dihitung dari izin itu — bukan dari izin baca yang
    # dipegang role lain milik orang yang sama.
    action_scope_permissions = {
        "record": RECORD_PERMISSION,
        "cancel": RECORD_PERMISSION,
    }

    serializer_class = EmployeeLeaveSerializer
    service_class = EmployeeLeaveService

    framework_module = "hr/leave"
    schema = LEAVE_SCHEMA

    # Default base-nya ["code", "name"], dan EmployeeLeave tidak punya
    # dua kolom itu — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "leave_type__name",
        "leave_reason__name",
        "notes",
    ]

    filterset_fields = [
        "document_number",
        "employee",
        "company",
        "branch",
        "location",
        "leave_type",
        "leave_reason",
        "status",
        "is_half_day",
        "start_date",
        "end_date",
    ]

    ordering_fields = [
        "start_date",
        "end_date",
        "total_days",
        "status",
        "employee__employee_number",
        "employee__first_name",
        "leave_type__name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-start_date",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            EmployeeLeave.objects
            .select_related(
                "employee",
                "company",
                "branch",
                "location",
                "leave_type",
                "leave_reason",
                "uploaded_file",
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Status bukan isian form
    # ------------------------------------------------------------------

    def perform_create(self, serializer):
        """
        Cuti yang lahir lewat POST biasa selalu **DRAFT**.

        Bawaan modelnya RECORDED — benar untuk jalur pencatatan yang
        memanggil service langsung (Travel Request, konversi presensi,
        seed), salah untuk pintu terbuka bernama `POST /api/hr/leaves/`.
        Tanpa baris ini, "buat cuti" dan "cuti ini sah tanpa
        persetujuan" adalah request yang sama persis.

        Pencatatan administratif ada pintunya sendiri: `record/`.
        """
        serializer.validated_data["status"] = LeaveStatus.DRAFT

        super().perform_create(serializer)

    def _assert_may_record(self, request):
        user = request.user

        if not getattr(user, "is_authenticated", False):
            raise NotAuthenticated()

        if user.is_superuser or user.has_perm(RECORD_PERMISSION):
            return

        raise PermissionDenied(
            "Mencatat cuti tanpa alur persetujuan butuh wewenang "
            "tersendiri. Hubungi administrator untuk menambahkannya ke "
            "role Anda.",
        )

    @action(detail=False, methods=["post"])
    def record(self, request):
        """
        Pencatatan administratif: cuti yang **sudah** terjadi atau sudah
        disetujui di luar sistem, masuk sebagai RECORDED tanpa alur.

        Aksi tersendiri, bukan `status` di formulir. Bedanya bukan soal
        bentuk: yang boleh membuat cuti adalah setiap pegawai (untuk
        dirinya sendiri), sedangkan yang boleh menyatakan sebuah cuti
        sah tanpa tanda tangan cuma meja yang memang diberi
        `hr.record_employeeleave`.

        Sisanya persis jalur create biasa — serializer yang sama,
        service yang sama, saldo dan aturan yang sama. Yang berbeda cuma
        dua hal yang memang harus berbeda: kemampuan yang dituntut, dan
        cakupan barisnya (dihitung dari izin pencatatan itu, lihat
        `action_scope_permissions`).
        """
        self._assert_may_record(request)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self._user(request)

        assert_employee_writable(
            employee=serializer.validated_data.get("employee"),
            user=user,
            permission=RECORD_PERMISSION,
        )

        instance = EmployeeLeaveService.create(
            data={
                **serializer.validated_data,
                "status": LeaveStatus.RECORDED,
            },
            user=user,
        )

        return created_response(
            data={
                "leave": EmployeeLeaveSerializer(
                    instance,
                    context=self.get_serializer_context(),
                ).data,
            },
            message="Cuti dicatat.",
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """
        Membatalkan cuti **pencatatan**, dan hanya itu.

        Pasangan dari `record/`: yang boleh mencatat cuti tanpa alur
        harus bisa membatalkan catatannya sendiri, kalau tidak
        satu-satunya jalan keluar dari salah ketik adalah menghapus
        barisnya — yang menghilangkan jejaknya juga.

        Dokumen yang lewat alur tidak dibatalkan dari sini: yang masih
        berjalan ditarik pengajunya (`withdraw/`) atau ditolak
        approver-nya, dan pembatalan cuti yang **sudah disetujui** belum
        punya aturan di sistem ini — tidak dikarang di sini.
        """
        self._assert_may_record(request)

        instance = self.get_object()

        if instance.status != LeaveStatus.RECORDED:
            raise ValidationError(
                {
                    "status": (
                        f"Cuti berstatus {instance.get_status_display()} "
                        "tidak dibatalkan dari sini."
                    ),
                },
            )

        EmployeeLeaveService.set_status(
            instance=instance,
            status=LeaveStatus.CANCELLED,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message="Catatan cuti dibatalkan.",
        )

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------
    #
    # Tombolnya ada di layar cuti, tapi keputusannya juga bisa diambil
    # dari kotak masuk generik (`/api/workflow/approvals/`). Dua jalur
    # itu memanggil service yang sama — kalau tidak, "kenapa hasilnya
    # beda kalau saya approve dari sini" jadi pertanyaan tanpa jawaban.

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message):
        instance.refresh_from_db()

        return success_response(
            data={
                "leave": EmployeeLeaveSerializer(
                    instance,
                    context=self.get_serializer_context(),
                ).data,
            },
            message=message,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="preview-rules",
    )
    def preview_rules(self, request):
        """
        Menilai isian yang **belum tersimpan**.

        Layar Create tidak punya record untuk dibacakan `policy_rules`,
        jadi tanpa endpoint ini satu-satunya cara menampilkan saldo dan
        peringatan adalah menghitungnya ulang di frontend — dan sejak
        itu ada dua penilai untuk satu aturan, yang cepat atau lambat
        berbeda. Yang menilai tetap `LeaveRuleEvaluator` yang sama
        dengan jalur simpan.

        Tidak menulis apa pun, dan **tidak pernah melempar** karena
        isian yang belum lengkap: form yang baru diisi separuh adalah
        keadaan normal, bukan kesalahan. Yang belum bisa dinilai
        dikembalikan sebagai `evaluated: false`.

        `total_days` ikut dikembalikan karena ia juga milik backend —
        hari kerja diturunkan dari kalender, roster, dan hari libur
        pegawainya, dan frontend tidak boleh menebaknya dari selisih
        tanggal.
        """
        from apps.administration.models import LeaveType

        data = request.data or {}

        employee = self._lookup(Employee, data.get("employee"))

        leave_type = self._lookup(LeaveType, data.get("leave_type"))

        start_date = parse_date_value(data.get("start_date"))
        end_date = parse_date_value(data.get("end_date"))

        if employee is None or leave_type is None:
            return success_response(
                data={"evaluated": False, "total_days": None, "rules": None},
                message="Lengkapi pegawai dan jenis cutinya dulu.",
            )

        is_half_day = str(data.get("is_half_day")).lower() in (
            "true",
            "1",
        )

        # Isian manual tetap menang, sama seperti di jalur simpan —
        # kalau tidak, angka yang diketik orang diabaikan di layar lalu
        # dihormati saat disimpan.
        total_days = data.get("total_days")

        if total_days in (None, ""):
            total_days = LeaveDayCalculator.calculate(
                employee=employee,
                start=start_date,
                end=end_date,
                is_half_day=is_half_day,
            )
        else:
            try:
                total_days = Decimal(str(total_days))
            except (InvalidOperation, ValueError):
                total_days = None

        instance = self._preview_instance(data.get("id"))

        report = EmployeeLeaveService.evaluate_rules(
            {
                "employee": employee,
                "leave_type": leave_type,
                "start_date": start_date,
                "end_date": end_date,
                "total_days": total_days,
                "is_half_day": is_half_day,
                "uploaded_file": data.get("uploaded_file") or None,
            },
            instance=instance,
        )

        return success_response(
            data={
                "evaluated": True,
                "total_days": (
                    str(total_days) if total_days is not None else None
                ),
                "rules": report.as_dict(),
            },
            message="Penilaian aturan cuti.",
        )

    def _preview_instance(self, raw):
        """
        Dokumen yang sedang disunting, kalau ada.

        Dipakai dua hal yang keduanya salah tanpa ini: riwayat harus
        mengecualikan dokumen itu sendiri, dan saldo harus
        mengembalikan potongan yang sudah dibuatnya. Lewat
        `get_queryset()` supaya cakupan data tetap berlaku —
        id yang diketik tangan tidak boleh membuka dokumen orang lain.
        """
        if raw in (None, ""):
            return None

        return self.filter_queryset(
            self.get_queryset(),
        ).filter(pk=raw).first()

    @staticmethod
    def _lookup(model, raw):
        if raw in (None, ""):
            return None

        return model.objects.filter(pk=raw, is_deleted=False).first()

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        instance = self.get_object()

        EmployeeLeaveService.submit(
            instance=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan cuti dikirim.",
        )

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        instance = self.get_object()

        EmployeeLeaveService.withdraw(
            instance=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan ditarik kembali.",
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(
            request,
            handler=WorkflowService.approve,
            message="Cuti disetujui.",
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(
            request,
            handler=WorkflowService.reject,
            message="Cuti ditolak.",
            require_notes=True,
        )

    @action(detail=True, methods=["post"], url_path="return")
    def send_back(self, request, pk=None):
        return self._decide(
            request,
            handler=WorkflowService.send_back,
            message="Cuti dikembalikan ke pengaju.",
            require_notes=True,
        )

    def _decide(self, request, *, handler, message, require_notes=False):
        from apps.workflow.registry import completion_handler

        instance = self.get_object()

        notes = str(request.data.get("notes", "")).strip()

        # Penolakan tanpa alasan tidak bisa ditindaklanjuti pengaju —
        # dia hanya tahu ditolak, tidak tahu apa yang harus dibetulkan.
        if require_notes and not notes:
            raise ValidationError(
                {"notes": "Alasan wajib diisi."},
            )

        workflow = WorkflowService.instance_for(
            document=instance,
            module=EmployeeLeaveService.WORKFLOW_MODULE,
            document_type=EmployeeLeaveService.WORKFLOW_DOCUMENT_TYPE,
        )

        if workflow is None:
            raise ValidationError(
                {
                    "status": (
                        "Cuti ini tidak sedang menunggu persetujuan."
                    ),
                },
            )

        handler(
            instance=workflow,
            user=self._user(request),
            comment=notes,
            on_complete=completion_handler(
                module=EmployeeLeaveService.WORKFLOW_MODULE,
                document_type=(
                    EmployeeLeaveService.WORKFLOW_DOCUMENT_TYPE
                ),
            ),
        )

        return self._respond(instance=instance, message=message)


class LeaveBalanceViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Seluruh organisasinya lewat penempatan pegawai — baris ini tidak
    # menyimpan satu pun kolom organisasi sendiri.
    data_scope = {
        "company": "employee__organization__company",
        "branch": "employee__organization__branch",
        "location": "employee__organization__location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = LeaveBalanceSerializer
    service_class = LeaveBalanceService

    framework_module = "hr/leave-balances"
    schema = LEAVE_BALANCE_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "leave_type__name",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "leave_type",
        "year",
    ]

    ordering_fields = [
        "year",
        "entitlement",
        "carried_over",
        "adjustment",
        "used",
        "employee__employee_number",
        "leave_type__name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-year",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            LeaveBalance.objects
            .select_related(
                "employee",
                "leave_type",
            )
            .filter(is_deleted=False)
        )
