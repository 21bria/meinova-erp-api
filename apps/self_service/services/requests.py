"""
Pengajuan pribadi dari My Workspace — **adapter tulis, bukan pemilik proses**.

    request.user → CurrentEmployeeService → Employee
        → serializer HR (validasi bentuk)
        → EmployeeLeaveService / AttendancePermissionService (create + submit)

Yang ditentukan berkas ini hanya tiga hal:

1. **Subjek.** Selalu pegawai yang sedang login. Tidak ada satu pun
   kolom dari client yang bisa menggesernya — `employee`, `employee_id`,
   `user`, `user_id`, `id`, `employee_number`, dan `subject` **ditolak**
   (`field_not_accepted`), bukan diabaikan.
2. **Kolom yang boleh diisi pegawai.** Daftar putih. Kolom HR — status,
   override jendela shift, company/branch/location, nomor dokumen,
   total hari — ikut ditolak: status ditentukan alur, override adalah
   keputusan HR, organisasi dan total hari diisi service.
3. **Jalur "pengajuan".** Dokumen dibuat lalu langsung diajukan ke alur
   persetujuan, dalam satu transaksi. Cuti selalu lahir DRAFT lalu
   `submit()` — tidak pernah RECORDED; jalur pencatatan tanpa approval
   adalah milik HR.

Yang **tidak** ada di sini: aturan jenis cuti, saldo, hitungan hari,
tumpang tindih, jendela shift, periode terkunci, penomoran, workflow.
Seluruhnya tetap di service domainnya, dan dijalankan persis sama
dengan jalur HR.

Lampiran dibatasi ke file yang **diunggah akun ini sendiri**. Jalur HR
menerima id `UploadedFile` apa pun; di jalur pribadi itu berarti
dokumen milik orang lain bisa ditempelkan ke pengajuan sendiri lalu
dibaca approver sebagai milik pemohon.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from rest_framework.exceptions import PermissionDenied

from apps.self_service.exceptions import FieldNotAccepted


# Kolom yang pernah — di endpoint mana pun — dipakai menyebut orang.
IDENTITY_FIELDS = frozenset(
    {
        "employee",
        "employee_id",
        "user",
        "user_id",
        "id",
        "employee_number",
        "subject",
    }
)

IDENTITY_MESSAGE = (
    "Pegawai ditentukan dari akun yang sedang login; "
    "kolom ini tidak diterima pada pengajuan pribadi."
)

NOT_ALLOWED_MESSAGE = "Kolom ini tidak diterima pada pengajuan pribadi."

ATTACHMENT_MESSAGE = "Lampiran harus file yang Anda unggah sendiri."


@dataclass(frozen=True)
class PersonalRequestSpec:
    permission: str
    fields: tuple[str, ...]
    attachment_field: str

    def serializer_class(self):
        raise NotImplementedError

    def create(self, *, data, user):
        raise NotImplementedError

    def submit(self, *, instance, user):
        raise NotImplementedError


class LeaveRequestSpec(PersonalRequestSpec):
    def serializer_class(self):
        from apps.hr.api.leave.serializers import EmployeeLeaveSerializer

        return EmployeeLeaveSerializer

    def create(self, *, data, user):
        from apps.hr.api.leave.services import EmployeeLeaveService
        from apps.hr.models.leave import LeaveStatus

        # Pengajuan, bukan pencatatan. Default model RECORDED — tanpa
        # baris ini cuti pribadi lahir sudah memotong saldo tanpa satu
        # tanda tangan pun.
        data["status"] = LeaveStatus.DRAFT

        return EmployeeLeaveService.create(data=data, user=user)

    def submit(self, *, instance, user):
        from apps.hr.api.leave.services import EmployeeLeaveService

        EmployeeLeaveService.submit(instance=instance, user=user)


class AttendancePermissionRequestSpec(PersonalRequestSpec):
    def serializer_class(self):
        from apps.hr.api.attendance_permission.serializers import (
            AttendancePermissionSerializer,
        )

        return AttendancePermissionSerializer

    def create(self, *, data, user):
        from apps.hr.api.attendance_permission.services import (
            AttendancePermissionService,
        )

        # `status` read-only di serializer HR; model lahir DRAFT.
        return AttendancePermissionService.create(data=data, user=user)

    def submit(self, *, instance, user):
        from apps.hr.api.attendance_permission.services import (
            AttendancePermissionService,
        )

        AttendancePermissionService.submit(permission=instance, user=user)


LEAVE_REQUEST = LeaveRequestSpec(
    permission="hr.add_employeeleave",
    fields=(
        "leave_type",
        "leave_reason",
        "start_date",
        "end_date",
        "is_half_day",
        "uploaded_file",
        "notes",
    ),
    attachment_field="uploaded_file",
)

ATTENDANCE_PERMISSION_REQUEST = AttendancePermissionRequestSpec(
    permission="hr.add_attendancepermission",
    fields=(
        "permission_type",
        "date",
        "start_time",
        "end_time",
        "reason",
        "notes",
        "supporting_document",
    ),
    attachment_field="supporting_document",
)


class SelfRequestService:
    """Membuat dan mengajukan dokumen pribadi untuk pegawai yang login."""

    @staticmethod
    def assert_permitted(user, spec: PersonalRequestSpec) -> None:
        """
        Izin model yang sama dengan jalur HR dan dengan syarat tombolnya
        di `/me` (`ActionResolver`). Jalur pribadi tidak membuka hak baru.
        """
        if getattr(user, "is_superuser", False):
            return

        if not user.has_perm(spec.permission):
            raise PermissionDenied(
                "Akun Anda tidak memiliki izin untuk mengajukan dokumen ini.",
            )

    @staticmethod
    def clean_payload(payload, spec: PersonalRequestSpec) -> dict:
        errors = {}

        for key in payload.keys():
            if key in IDENTITY_FIELDS:
                errors[key] = [IDENTITY_MESSAGE]
            elif key not in spec.fields:
                errors[key] = [NOT_ALLOWED_MESSAGE]

        if errors:
            raise FieldNotAccepted(errors)

        return {key: payload.get(key) for key in spec.fields if key in payload}

    @staticmethod
    def assert_attachment_owned(validated: dict, *, user, spec) -> None:
        """
        Aturannya **satu**, bentuk galatnya yang berbeda.

        Yang menilai `FileAccessService.attachment_problem()` — sama
        persis dengan jalur HR — supaya "boleh menempel apa" tidak
        pernah punya dua pendapat. Yang tetap milik Self Service kode
        galatnya (`field_not_accepted`), karena seluruh kontrak
        `/api/me/*` memang berbunyi begitu.
        """
        from apps.uploads.services.access_service import FileAccessService

        attachment = validated.get(spec.attachment_field)

        if attachment is None:
            return

        problem = FileAccessService.attachment_problem(
            uploaded_file=attachment,
            user=user,
        )

        if problem is not None:
            raise FieldNotAccepted({
                spec.attachment_field: [ATTACHMENT_MESSAGE, problem],
            })

    @classmethod
    def create(cls, *, spec: PersonalRequestSpec, employee, user, payload, request):
        cls.assert_permitted(user, spec)

        data = cls.clean_payload(payload, spec)

        # Subjek disuntikkan **sesudah** daftar putih, dari resolver —
        # satu-satunya sumbernya.
        data["employee"] = employee.pk

        serializer_class = spec.serializer_class()

        serializer = serializer_class(
            data=data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        validated = dict(serializer.validated_data)

        # Dipasang ulang dari instance resolver, bukan dari hasil
        # validasi — tidak ada jalan bagi apa pun di antaranya untuk
        # menggantinya.
        validated["employee"] = employee

        cls.assert_attachment_owned(validated, user=user, spec=spec)

        with transaction.atomic():
            instance = spec.create(data=validated, user=user)

            spec.submit(instance=instance, user=user)

        instance.refresh_from_db()

        return serializer_class(instance, context={"request": request}).data
