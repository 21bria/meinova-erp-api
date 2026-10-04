from __future__ import annotations

from rest_framework import serializers

from apps.hr.models import (
    EmployeeAttendance,
    AttendanceStatus,
)
from apps.hr.models.organization import OrganizationAssignment

class EmployeeAttendanceListSerializer(
    serializers.ListSerializer,
):
    """
    Dokumen izin seluruh halaman diambil **sekali**, bukan sebaris satu.

    `get_permissions()` memanggil `permissions_for(employee, work_date)`,
    dan itu satu query per baris. Jumlahnya memang sudah dibatasi
    pagination — 25 baris, 25 query — jadi ia tidak pernah muncul
    sebagai halaman yang menggantung; yang terjadi cuma setiap halaman
    presensi membayar dua puluh lima perjalanan ke database untuk
    menjawab satu pertanyaan.

    Pertanyaannya tidak berubah dan aturannya tidak berubah: status yang
    dibaca tetap `READABLE_STATUSES` milik `permission_effect`, dan
    urutannya tetap `id`. Yang berubah cuma **kapan** ditanyakan.

    Pasangan (pegawai, tanggal) dikirim sebagai dua `IN` lalu dicocokkan
    di Python. Itu memang memuat sedikit baris yang tidak terpakai —
    izin pegawai A pada tanggal milik baris pegawai B — tapi keduanya
    dibatasi satu halaman, dan alternatifnya (`OR` sebanyak baris)
    menghasilkan query yang tidak bisa dipakai indeks mana pun.
    """

    def to_representation(self, data):
        rows = list(data)

        self.child.context["permission_map"] = self._permission_map(rows)

        try:
            return super().to_representation(rows)
        finally:
            # Context-nya dipakai bersama lintas request kalau
            # serializer-nya sempat dipakai ulang; petanya dibuang
            # supaya halaman berikutnya tidak pernah membaca yang lama.
            self.child.context.pop("permission_map", None)

    @staticmethod
    def _permission_map(rows) -> dict:
        from apps.hr.api.attendance.permission_effect import (
            READABLE_STATUSES,
        )
        from apps.hr.models.attendance.permission import (
            AttendancePermission,
        )

        pairs = {
            (row.employee_id, row.work_date)
            for row in rows
            if row.employee_id is not None and row.work_date is not None
        }

        if not pairs:
            return {}

        employee_ids = {employee_id for employee_id, _ in pairs}
        work_dates = {work_date for _, work_date in pairs}

        grouped: dict = {}

        queryset = (
            AttendancePermission.objects
            .filter(
                employee_id__in=employee_ids,
                date__in=work_dates,
                is_deleted=False,
                status__in=READABLE_STATUSES,
            )
            .order_by("id")
        )

        for permission in queryset:
            key = (permission.employee_id, permission.date)

            if key not in pairs:
                continue

            grouped.setdefault(key, []).append(permission)

        return grouped


class EmployeeAttendanceSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

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

    shift_name = serializers.CharField(
        source="shift.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    source_label = serializers.CharField(
        source="get_source_display",
        read_only=True,
    )

    approval_status_label = serializers.CharField(
        source="get_approval_status_display",
        read_only=True,
    )

    approved_by_name = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Kewajiban cuti
    # ------------------------------------------------------------------
    #
    # Angka **efektif**, bukan `leave_required_days`. Menampilkan angka
    # menurut aturan pada baris yang sudah dibebaskan membuat daftarnya
    # terbaca seperti pekerjaan yang belum selesai.
    leave_required_effective = serializers.DecimalField(
        max_digits=4,
        decimal_places=2,
        read_only=True,
    )

    leave_obligation_status = serializers.CharField(read_only=True)
    leave_obligation_label = serializers.CharField(read_only=True)

    leave_required_reason_label = serializers.CharField(
        source="get_leave_required_reason_display",
        read_only=True,
        default="",
    )

    review_decision_label = serializers.CharField(
        source="get_review_decision_display",
        read_only=True,
        default="",
    )

    leave_document_number = serializers.CharField(
        source="leave.document_number",
        read_only=True,
        default=None,
    )

    reviewed_by_name = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Klasifikasi izin
    # ------------------------------------------------------------------
    #
    # Yang tanpa izin **diturunkan**, bukan kolom: angkanya persis
    # selisih dua kolom yang sudah ada, dan kolom ketiga yang harus
    # konsisten dengan keduanya adalah kolom yang cepat atau lambat
    # menyimpang.
    unauthorized_late_minutes = serializers.IntegerField(read_only=True)
    unauthorized_early_leave_minutes = serializers.IntegerField(
        read_only=True,
    )
    permission_state_label = serializers.CharField(read_only=True)

    # Dokumen izin yang menyentuh tanggal ini. Tanpa tautannya,
    # "dimaafkan" tidak bisa ditelusuri ke dokumen mana pun, dan
    # pertanyaan "izin yang mana" hanya bisa dijawab dengan mencari
    # manual di layar sebelah.
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeAttendance
        fields = "__all__"

        # Dipakai DRF saat `many=True` — yaitu tepat di jalur daftar.
        list_serializer_class = EmployeeAttendanceListSerializer

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "approved_at",
            "approved_by",
            "employee_name",
            "employee_number",
            "company_name",
            "branch_name",
            "location_name",
            "shift_name",
            "status_label",
            "source_label",
            "approval_status_label",
            "approved_by_name",
            # Ditulis lewat tombol Waive / Require Leave / Issue Leave,
            # bukan lewat form: keputusan yang bisa diketik diam-diam di
            # tengah baris lain tidak meninggalkan siapa dan kapan.
            "leave_required_days",
            "leave_required_reason",
            "leave_required_reason_label",
            "leave_required_effective",
            "leave_obligation_status",
            "leave_obligation_label",
            "review_decision",
            "review_decision_label",
            "reviewed_at",
            "reviewed_by",
            "reviewed_by_name",
            "leave",
            "leave_document_number",
            # BT-3: izin perjalanan ditulis penutup hari, bukan form.
            "business_trip",
            # Ditulis `AttendancePermissionResolver` dari dokumen izin
            # yang disetujui, bukan dari form: pembebasan yang bisa
            # diketik langsung di baris presensi melewati seluruh alur
            # persetujuan.
            "excused_late_minutes",
            "excused_early_leave_minutes",
            "permission_minutes",
            "is_excused_absence",
            "permission_state",
            "permission_state_label",
            "unauthorized_late_minutes",
            "unauthorized_early_leave_minutes",
            "permissions",
        ]

    def get_reviewed_by_name(
        self,
        instance: EmployeeAttendance,
    ) -> str | None:
        user = instance.reviewed_by

        if user is None:
            return None

        full_name = str(
            getattr(user, "get_full_name", lambda: "")() or "",
        ).strip()

        return full_name or getattr(user, "username", None) or str(user)

    def get_approved_by_name(
        self,
        instance: EmployeeAttendance,
    ) -> str | None:
        user = instance.approved_by

        if user is None:
            return None

        full_name_method = getattr(
            user,
            "get_full_name",
            None,
        )

        if callable(full_name_method):
            full_name = str(
                full_name_method() or "",
            ).strip()

            if full_name:
                return full_name

        return (
            getattr(user, "email", None)
            or getattr(user, "username", None)
            or str(user)
        )
    def get_active_assignment(
            self,
            employee,
        ) -> OrganizationAssignment | None:
            if employee is None:
                return None
    
            return (
                OrganizationAssignment.objects
                .filter(
                    employee=employee,
                    is_active=True,
                    is_deleted=False,
                )
                .select_related(
                    "company",
                    "branch",
                    "location",
                )
                .order_by(
                    "-organization_effective_date",
                    "-id",
                )
                .first()
            )
    def validate(self, attrs):
            instance = self.instance
    
            employee = attrs.get(
                "employee",
                getattr(instance, "employee", None),
            )
    
            company = attrs.get(
                "company",
                getattr(instance, "company", None),
            )
    
            branch = attrs.get(
                "branch",
                getattr(instance, "branch", None),
            )
    
            location = attrs.get(
                "location",
                getattr(instance, "location", None),
            )
    
            work_date = attrs.get(
                "work_date",
                getattr(instance, "work_date", None),
            )
    
            status_value = attrs.get(
                "status",
                getattr(instance, "status", None),
            )
    
            scheduled_check_in = attrs.get(
                "scheduled_check_in",
                getattr(
                    instance,
                    "scheduled_check_in",
                    None,
                ),
            )
    
            scheduled_check_out = attrs.get(
                "scheduled_check_out",
                getattr(
                    instance,
                    "scheduled_check_out",
                    None,
                ),
            )
    
            check_in = attrs.get(
                "check_in",
                getattr(instance, "check_in", None),
            )
    
            check_out = attrs.get(
                "check_out",
                getattr(instance, "check_out", None),
            )
    
            first_check_in = attrs.get(
                "first_check_in",
                getattr(
                    instance,
                    "first_check_in",
                    None,
                ),
            )
    
            last_check_out = attrs.get(
                "last_check_out",
                getattr(
                    instance,
                    "last_check_out",
                    None,
                ),
            )
    
            is_manual_adjustment = attrs.get(
                "is_manual_adjustment",
                getattr(
                    instance,
                    "is_manual_adjustment",
                    False,
                ),
            )
    
            adjustment_reason = attrs.get(
                "adjustment_reason",
                getattr(
                    instance,
                    "adjustment_reason",
                    "",
                ),
            )
    
            errors: dict[str, str] = {}
    
            if employee is None:
                errors["employee"] = (
                    "Employee is required."
                )
    
            if company is None:
                errors["company"] = (
                    "Company is required."
                )
    
            if work_date is None:
                errors["work_date"] = (
                    "Work Date is required."
                )
    
            assignment = self.get_active_assignment(
                employee,
            )
    
            if employee is not None and assignment is None:
                errors["employee"] = (
                    "Employee does not have an active "
                    "organization assignment."
                )
    
            if assignment is not None:
                if (
                    company is not None
                    and assignment.company_id
                    != company.pk
                ):
                    errors["company"] = (
                        "Company does not match the "
                        "employee active assignment."
                    )
    
                if (
                    branch is not None
                    and assignment.branch_id
                    != branch.pk
                ):
                    errors["branch"] = (
                        "Branch does not match the "
                        "employee active assignment."
                    )
    
                if (
                    location is not None
                    and assignment.location_id
                    != location.pk
                ):
                    errors["location"] = (
                        "Location does not match the "
                        "employee active assignment."
                    )
    
            if (
                scheduled_check_in
                and scheduled_check_out
                and scheduled_check_out
                < scheduled_check_in
            ):
                errors["scheduled_check_out"] = (
                    "Scheduled Check Out cannot be "
                    "earlier than Scheduled Check In."
                )
    
            if (
                check_in
                and check_out
                and check_out < check_in
            ):
                errors["check_out"] = (
                    "Check Out cannot be earlier "
                    "than Check In."
                )
    
            if (
                first_check_in
                and last_check_out
                and last_check_out < first_check_in
            ):
                errors["last_check_out"] = (
                    "Last Check Out cannot be earlier "
                    "than First Check In."
                )
    
            if (
                status_value == AttendanceStatus.ABSENT
                and (
                    check_in
                    or check_out
                    or first_check_in
                    or last_check_out
                )
            ):
                errors["status"] = (
                    "Absent attendance cannot contain "
                    "Check In or Check Out."
                )
    
            if (
                is_manual_adjustment
                and not str(
                    adjustment_reason or "",
                ).strip()
            ):
                errors["adjustment_reason"] = (
                    "Adjustment Reason is required "
                    "for manual adjustments."
                )
    
            if (
                employee is not None
                and work_date is not None
            ):
                duplicate_queryset = (
                    EmployeeAttendance.objects
                    .filter(
                        employee=employee,
                        work_date=work_date,
                        is_deleted=False,
                    )
                )
    
                if instance is not None:
                    duplicate_queryset = (
                        duplicate_queryset.exclude(
                            pk=instance.pk,
                        )
                    )
    
                if duplicate_queryset.exists():
                    errors["work_date"] = (
                        "Attendance for this employee "
                        "and work date already exists."
                    )
    
            if errors:
                raise serializers.ValidationError(
                    errors,
                )
    
            return attrs
    def get_permissions(self, obj) -> list:
        """
        Dokumen izin pada tanggal ini — disetujui maupun masih berjalan.

        Yang masih berjalan ikut, dan itu yang menjelaskan badge
        "Menunggu izin": tanpa dokumennya terlihat, baris yang tampak
        melanggar tidak bisa dibedakan dari baris yang keputusannya
        belum keluar.
        """
        from apps.hr.api.attendance.permission_effect import permissions_for

        if obj.employee_id is None or obj.work_date is None:
            return []

        # Jalur daftar sudah memuat seluruh halaman sekaligus (lihat
        # `EmployeeAttendanceListSerializer`). Petanya lengkap untuk
        # baris-baris di halaman itu, jadi pasangan yang tidak ada di
        # dalamnya memang tidak punya dokumen izin — bukan alasan untuk
        # bertanya lagi.
        preloaded = self.context.get("permission_map")

        if preloaded is not None:
            rows = preloaded.get((obj.employee_id, obj.work_date), [])
        else:
            rows = permissions_for(obj.employee, obj.work_date)

        return [
            {
                "id": row.pk,
                "document_number": row.document_number,
                "permission_type": row.permission_type,
                "permission_type_label": row.get_permission_type_display(),
                "start_time": row.start_time,
                "end_time": row.end_time,
                "status": row.status,
                "status_label": row.get_status_display(),
                "reason": row.reason,
            }
            for row in rows
        ]
