from __future__ import annotations

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import AttendancePermission, Employee
from apps.uploads.api.attach import guard_attachment
from apps.uploads.api.serializers import UploadedFileSerializer
from apps.uploads.models import UploadedFile
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


# Kemampuan HR: menerbitkan izin **di luar jam kerja** pegawainya.
# Dideklarasikan di `AttendancePermission.Meta.permissions`, jadi ia izin
# Django biasa yang bisa dicentang per tenant di layar Roles.
OVERRIDE_PERMISSION = "hr.override_attendancepermission"

# Kolom yang hanya boleh disentuh pemegang kemampuan itu.
OVERRIDE_FIELDS = ("allow_outside_shift", "outside_shift_reason")


class AttendancePermissionSerializer(serializers.ModelSerializer):
    # Dikosongkan = diisi service dari akun yang mengetik — jalur
    # Employee Self Service, yang formnya memang tidak punya kolom
    # pegawai. Wajib `required=False` di sini: kalau dibiarkan required
    # bawaan model, DRF menolak **sebelum** service sempat jalan dan
    # pengisian otomatisnya tidak pernah kepakai. Jebakan yang sama
    # dengan `requester` di Visitor Request dan `location` di Roster
    # Setup.
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.filter(is_deleted=False),
        required=False,
    )

    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    # **Diturunkan dari penempatan pegawainya, bukan dikirim client.**
    # Sebelum ini ketiganya field biasa dan `apply_organization` hanya
    # mengisi yang kosong, jadi satu request berisi `"location": 1`
    # memindahkan dokumen ke unit lain — keluar dari jangkauan HR yang
    # seharusnya melihatnya, masuk ke jangkauan HR yang tidak
    # berkepentingan. Terbukti untuk keempat jenis aktor di tenant demo.
    company = serializers.PrimaryKeyRelatedField(read_only=True)

    branch = serializers.PrimaryKeyRelatedField(read_only=True)

    location = serializers.PrimaryKeyRelatedField(read_only=True)

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    permission_type_label = serializers.CharField(
        source="get_permission_type_display",
        read_only=True,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    duration_minutes = serializers.IntegerField(read_only=True)

    # `.active()`, bukan `objects.all()` bawaan ModelSerializer: tanpa
    # ini berkas yang sudah dihapus masih bisa ditempel, dan jalur Cuti
    # sudah lama memakai aturan yang lebih ketat. Dua kolom lampiran
    # yang berbeda pendapat soal berkas terhapus adalah selisih yang
    # tidak ada yang memutuskannya.
    supporting_document = serializers.PrimaryKeyRelatedField(
        queryset=UploadedFile.objects.active(),
        required=False,
        allow_null=True,
    )

    supporting_document_detail = UploadedFileSerializer(
        source="supporting_document",
        read_only=True,
    )

    # Jadwal pegawai pada tanggal izin, ikut dikirim.
    #
    # Supervisor yang menyetujui izin **harus** melihat jam kerja yang
    # sedang dimintakan kelonggarannya. Tanpa itu "boleh datang jam 10"
    # tidak bisa dinilai siapa pun: sepuluh pagi untuk shift 08:00
    # adalah dua jam, untuk shift malam ia di luar jam kerja sama
    # sekali.
    shift = serializers.SerializerMethodField()

    # Presensi sesungguhnya pada tanggal itu, kalau barisnya sudah ada.
    attendance = serializers.SerializerMethodField()

    conflicts = serializers.SerializerMethodField()

    approval = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Kolom daftar yang murah
    # ------------------------------------------------------------------
    #
    # Keduanya ada supaya layar daftar tidak perlu membuka `shift`,
    # `attendance`, `approval`, atau `conflicts` — empat blok yang
    # masing-masing menembak database per baris dan **tidak dihitung
    # sama sekali** saat serializer dipakai untuk banyak baris.

    time_window = serializers.SerializerMethodField()

    current_approver = serializers.SerializerMethodField()

    class Meta:
        model = AttendancePermission
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "document_number",
            "employee_name",
            "employee_number",
            "company_name",
            "branch_name",
            "location_name",
            "permission_type_label",
            "status_label",
            "duration_minutes",
            "supporting_document_detail",
            "shift",
            "attendance",
            "conflicts",
            "approval",
            "time_window",
            "current_approver",
            # Perpindahan status **hanya** lewat tombol alur. Kalau
            # kolomnya bisa dikirim form, siapa pun yang menembak API
            # langsung bisa menuliskan `approved` tanpa satu pun tanda
            # tangan — dan seluruh alur persetujuan jadi hiasan.
            "status",
            "submitted_at",
            "approved_at",
            "rejected_at",
            "cancelled_at",
        ]

    # ------------------------------------------------------------------
    # Detail vs daftar
    # ------------------------------------------------------------------

    @property
    def _is_detail(self) -> bool:
        """
        Benar saat serializer ini melayani **satu** record.

        `self.parent` terisi `ListSerializer` begitu `many=True`, jadi
        pemeriksaannya tidak butuh viewset mengirim apa pun — jalur
        aksi (`_respond`) dan `retrieve` sama-sama single-object.

        Kenapa ada sama sekali: empat blok konteks di bawah
        (`shift`, `attendance`, `conflicts`, `approval`) masing-masing
        menembak database, dan diukur **11 query per baris** saat
        seluruhnya ikut di daftar. Satu halaman 25 baris = 275 query
        untuk layar yang cuma menampilkan tujuh kolom. Yang dibutuhkan
        daftar sudah dijawab `time_window` dan `current_approver` yang
        tidak menyentuh database sendiri.
        """
        return self.parent is None

    def get_time_window(self, obj) -> str:
        """
        Jendela izin sebagai satu kalimat pendek, tanpa query.

        Artinya berbeda per jenis, dan itu yang membuat satu kolom
        "Time" bisa dibaca tanpa membuka dokumennya: Late Arrival
        menyebut batas datang, Early Leave menyebut sejak jam berapa
        boleh pulang, Temporary Out menyebut jendelanya, Full Day tidak
        punya jam sama sekali.
        """
        from apps.hr.models import AttendancePermissionType

        kind = obj.permission_type

        def hhmm(value):
            return value.strftime("%H:%M") if value else ""

        if kind == AttendancePermissionType.LATE_ARRIVAL:
            return f"s/d {hhmm(obj.end_time)}" if obj.end_time else ""

        if kind == AttendancePermissionType.EARLY_LEAVE:
            return f"mulai {hhmm(obj.start_time)}" if obj.start_time else ""

        if kind == AttendancePermissionType.TEMPORARY_OUT:
            if obj.start_time and obj.end_time:
                return f"{hhmm(obj.start_time)}–{hhmm(obj.end_time)}"

            return ""

        return "Sehari penuh"

    def get_current_approver(self, obj) -> str:
        """
        Nama orang yang mejanya sedang menahan dokumen ini.

        Dibaca dari peta yang disiapkan viewset **sekali per halaman**
        (`context["current_approvers"]`), bukan dengan menanyakan
        workflow per baris. Kosong berarti tidak sedang menunggu
        siapa-siapa — draft, atau sudah selesai.
        """
        mapping = self.context.get("current_approvers")

        if mapping is not None:
            return mapping.get(obj.pk, "")

        # Jalur detail: petanya tidak disiapkan, dan `approval` memang
        # dihitung penuh di sini.
        approval = self.get_approval(obj) or {}

        step = approval.get("current_step") or {}

        return step.get("approver") or ""

    # ------------------------------------------------------------------

    def get_shift(self, obj) -> dict | None:
        from apps.hr.api.attendance.schedule import resolve_shift, shift_span

        if not self._is_detail:
            return None

        if obj.employee_id is None or obj.date is None:
            return None

        resolved = resolve_shift(obj.employee, obj.date)

        if resolved is None:
            return None

        start, end = shift_span(
            obj.date,
            resolved.start_time,
            resolved.end_time,
            resolved.crosses_midnight,
        )

        return {
            "code": resolved.shift_code,
            "name": resolved.shift_name,
            "source": resolved.source,
            "start": start,
            "end": end,
            "crosses_midnight": resolved.crosses_midnight,
        }

    def get_attendance(self, obj) -> dict | None:
        from apps.hr.models import EmployeeAttendance

        if not self._is_detail:
            return None

        if obj.employee_id is None or obj.date is None:
            return None

        row = (
            EmployeeAttendance.objects
            .filter(
                employee_id=obj.employee_id,
                work_date=obj.date,
                is_deleted=False,
            )
            .first()
        )

        if row is None:
            return None

        return {
            "id": row.pk,
            "status": row.status,
            "status_label": row.get_status_display(),
            "check_in": row.check_in,
            "check_out": row.check_out,
            "late_minutes": row.late_minutes,
            "excused_late_minutes": row.excused_late_minutes,
            "unauthorized_late_minutes": row.unauthorized_late_minutes,
            "early_leave_minutes": row.early_leave_minutes,
            "excused_early_leave_minutes": row.excused_early_leave_minutes,
            "unauthorized_early_leave_minutes": (
                row.unauthorized_early_leave_minutes
            ),
            "permission_minutes": row.permission_minutes,
            "is_excused_absence": row.is_excused_absence,
            "permission_state": row.permission_state,
            "permission_state_label": row.permission_state_label,
        }

    def get_conflicts(self, obj) -> list:
        """
        Peringatan, bukan penolakan — lihat
        `AttendancePermissionService.detect_conflicts`.

        Dihitung saat dibaca, bukan disimpan: cuti yang disetujui
        sesudah izinnya dibuat harus langsung terbaca sebagai konflik,
        dan kolom yang ditulis sekali saat penyimpanan tidak akan
        pernah menyebutnya.

        **Hanya di jalur detail.** Tiga query per baris untuk kotak
        peringatan yang tidak dirender di layar daftar.
        """
        if obj.pk is None or not self._is_detail:
            return []

        from apps.hr.api.attendance_permission.services import (
            AttendancePermissionService,
        )

        return AttendancePermissionService.detect_conflicts(obj)

    def get_approval(self, obj) -> dict | None:
        """
        Keadaan persetujuan + baris tanda tangan.

        Bentuknya **sengaja sama persis** dengan `approval` di Visitor
        Request dan Travel Request: komponen jejak persetujuan di
        frontend dipakai ulang apa adanya.
        """
        if not self._is_detail:
            return None

        workflow = WorkflowService.history_for(
            document=obj,
            module="hr",
            document_type="attendance_permission",
        ).first()

        if workflow is None:
            return None

        user = getattr(self.context.get("request"), "user", None)

        rows = sorted(
            workflow.approvals.all(),
            key=lambda row: (row.sequence, row.pk),
        )

        current = next(
            (
                row
                for row in rows
                if row.status == ApprovalStatus.PENDING
                and row.step_id == workflow.current_step_id
            ),
            None,
        )

        def approver_name(row):
            if row.approver_employee_id:
                return row.approver_employee.full_name

            if row.approver_id:
                return row.approver.get_full_name() or row.approver.email

            return None

        return {
            "instance_id": workflow.pk,
            "status": workflow.status,
            "status_label": workflow.get_status_display(),
            "flow": workflow.definition.name,
            "submitted_at": workflow.submitted_at,
            "completed_at": workflow.completed_at,
            "can_act": (
                current is not None
                and WorkflowApprovalService.can_act(
                    approval=current,
                    user=user,
                )
            ),
            "current_step": (
                {
                    "approval_id": current.pk,
                    "sequence": current.sequence,
                    "name": current.name,
                    "approver": approver_name(current),
                }
                if current is not None
                else None
            ),
            "steps": [
                {
                    "approval_id": row.pk,
                    "sequence": row.sequence,
                    "name": row.name,
                    "approver": approver_name(row),
                    "decision": row.status,
                    "decision_label": row.get_status_display(),
                    "decided_at": row.acted_at,
                    "notes": row.comment or row.assignment_reference,
                    "acted_by": (
                        (row.acted_by.get_full_name() or row.acted_by.email)
                        if row.was_delegated
                        else None
                    ),
                }
                for row in rows
            ],
        }

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Override HR
    # ------------------------------------------------------------------

    def _assert_may_override(self, attrs) -> None:
        """
        Menyalakan `allow_outside_shift` adalah wewenang HR, bukan isian
        biasa.

        Kolom itu mem-bypass `assert_within_shift` — satu-satunya
        penjagaan yang memastikan izin memang berada di dalam jam kerja
        pegawainya. Sebelum ini siapa pun pemegang
        `hr.add_attendancepermission` (role EMPLOYEE hasil seed
        memilikinya) bisa menyalakannya untuk dirinya sendiri; terbukti
        untuk keempat jenis aktor di tenant demo.

        Yang dijaga **perubahannya**, bukan sekadar kehadiran kolomnya:
        formulir mengirim seluruh isi tab apa adanya, jadi
        `allow_outside_shift: false` dari pegawai biasa adalah keadaan
        normal dan tidak boleh ditolak. Yang ditolak menyalakannya,
        mematikannya kembali, atau mengubah alasannya — tanpa
        kemampuan itu.
        """
        request = self.context.get("request")

        if request is None:
            # Jalur internal memakai serializer sebagai pemeriksa
            # bentuk; tidak ada pemakai yang memilih apa pun di sana.
            return

        user = getattr(request, "user", None)

        changed = []

        for field in OVERRIDE_FIELDS:
            if field not in attrs:
                continue

            current = getattr(self.instance, field, None) if self.instance else None

            new = attrs[field]

            # Kosong dan `None` berarti hal yang sama untuk alasan
            # override; dibedakan akan menolak formulir yang mengirim
            # string kosong untuk kolom yang memang belum diisi.
            if isinstance(new, str) or isinstance(current, str):
                if (new or "").strip() == (current or "").strip():
                    continue
            elif bool(new) == bool(current):
                continue

            changed.append(field)

        if not changed:
            return

        if getattr(user, "is_superuser", False):
            return

        if user is not None and user.has_perm(OVERRIDE_PERMISSION):
            return

        raise serializers.ValidationError({
            field: [
                "Izin di luar jam kerja adalah wewenang HR. Hubungi "
                "administrator untuk menambahkannya ke role Anda."
            ]
            for field in changed
        })

    def validate(self, attrs):
        """
        Bentuk per tipe izin dinilai di sini supaya pesannya menempel di
        kolom yang salah.

        `Model.clean()` tetap memeriksa hal yang sama — ini bukan
        penggantinya. Yang dijaga di sini urutannya: `clean_fields()`
        berjalan lebih dulu dan pesan bawaannya muncul sebagai error
        pertama, dan itu yang ditampilkan form.
        """
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        self._assert_may_override(attrs)

        # Lampiran: aktif, milik yang menempel, belum dipakai dokumen
        # lain. Aturannya di `FileAccessService` — menempelkan berkas
        # memberi hak baca, jadi itu pertanyaan otorisasi.
        guard_attachment(self, "supporting_document", attrs)

        permission_type = resolved("permission_type")

        errors = {}

        if permission_type:
            for name in AttendancePermission.REQUIRED_TIMES.get(
                permission_type, (),
            ):
                if resolved(name) is None:
                    errors[name] = (
                        "Wajib diisi untuk jenis izin ini."
                    )

        if not (resolved("reason") or "").strip():
            errors["reason"] = "Alasan izin wajib diisi."

        if (
            resolved("allow_outside_shift")
            and not (resolved("outside_shift_reason") or "").strip()
        ):
            errors["outside_shift_reason"] = (
                "Alasan override wajib diisi."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
