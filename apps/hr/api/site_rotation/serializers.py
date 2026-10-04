from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.api.site_rotation.services import build_schedule_warnings
from apps.hr.models import (
    EmployeeShiftAssignment,
    RosterSegmentType,
    RotationPeriod,
    ShiftAssignmentLayer,
    SiteRotation,
)


class SiteRotationSerializer(serializers.ModelSerializer):
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

    roster_crew_name = serializers.CharField(
        source="roster_crew.name",
        read_only=True,
        default=None,
    )

    # Rencana yang lahir dari dokumen Roster Setup tidak punya crew —
    # polanya datang dari policy. Tanpa kolom ini daftar jadwal
    # memperlihatkan "-" di kolom Roster Crew untuk semuanya, dan itu
    # terbaca seperti data yang belum diisi, bukan seperti jalur yang
    # memang berbeda.
    roster_policy_name = serializers.CharField(
        source="roster_policy.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # Boleh dikosongkan supaya service bisa menurunkannya dari jangkar
    # siklus crew. Kalau dibiarkan `required` bawaan model, validasi DRF
    # menolak request lebih dulu dan jalur pengisian otomatis itu tidak
    # pernah kepakai. Dokumen tanpa crew tetap wajib mengisinya —
    # penjagaannya pindah ke `full_clean()`.
    start_date = serializers.DateField(required=False)

    # Diisi generator dari periode terakhir; menulisnya lewat form hanya
    # akan ditimpa pada sinkronisasi berikutnya.
    end_date = serializers.DateField(read_only=True)

    # Kepala Travel Request. Semuanya dibaca dari relasi pegawai, tidak
    # disalin ke dokumen: kalau departemen atau email pegawai dikoreksi,
    # TR yang belum terbang harus ikut betul. Menyalinnya berarti punya
    # dua versi data yang sama dan yang satu diam-diam basi.
    point_of_hire_name = serializers.CharField(
        source="employee.employment.point_of_hire.name",
        read_only=True,
        default=None,
    )

    department_name = serializers.CharField(
        source="employee.organization.department.name",
        read_only=True,
        default=None,
    )

    section_name = serializers.CharField(
        source="employee.organization.section.name",
        read_only=True,
        default=None,
    )

    position_name = serializers.CharField(
        source="employee.organization.position.name",
        read_only=True,
        default=None,
    )

    # Email kantor lebih dulu; kalau pegawainya belum punya, jatuh ke
    # email pribadi — TR dikirim ke orangnya, bukan ke kolom yang kosong.
    work_email = serializers.SerializerMethodField()

    phone_number = serializers.SerializerMethodField()

    join_date = serializers.DateField(
        source="employee.employment.join_date",
        read_only=True,
        default=None,
    )

    # Menjawab "Cycle Count 7 itu dari mana". Dihitung, bukan disimpan.
    cycle_length = serializers.IntegerField(read_only=True)

    cycles_per_year = serializers.SerializerMethodField()

    period_count = serializers.SerializerMethodField()

    schedule_warnings = serializers.SerializerMethodField()

    class Meta:
        model = SiteRotation
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "company_name",
            "branch_name",
            "location_name",
            "roster_crew_name",
            "roster_policy_name",
            "point_of_hire_name",
            "department_name",
            "section_name",
            "position_name",
            "work_email",
            "phone_number",
            "join_date",
            "status_label",
            "end_date",
            "cycle_length",
            "cycles_per_year",
            "period_count",
            "schedule_warnings",
        ]

    def get_work_email(self, obj) -> str | None:
        employee = obj.employee

        return (
            employee.work_email
            or employee.personal_email
            or None
        )

    def get_phone_number(self, obj) -> str | None:
        employee = obj.employee

        return (
            employee.mobile
            or employee.phone
            or None
        )

    def get_cycles_per_year(self, obj) -> int | None:
        """Perkiraan siklus untuk menutupi 365 hari, dibulatkan ke atas."""
        length = obj.cycle_length

        if not length:
            return None

        return -(-365 // length)

    def get_period_count(self, obj) -> int:
        # `periods` sudah di-prefetch viewset, jadi ini tidak menambah
        # query per baris.
        return len(
            [
                period
                for period in obj.periods.all()
                if not period.is_deleted
            ],
        )

    def get_schedule_warnings(self, obj) -> list[dict]:
        """
        Celah dan tumpang tindih antar periode. Kosong = jadwalnya rapat.

        Dihitung dari baris yang sudah di-prefetch viewset, jadi tidak
        menambah query per dokumen.
        """
        return build_schedule_warnings(obj.periods.all())

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        cycle_count = resolved("cycle_count")

        if cycle_count is not None and cycle_count < 1:
            errors["cycle_count"] = "Cycle Count must be at least 1."

        for field_name, label in (
            ("cycle_work_days", "Cycle Work Days"),
            ("cycle_off_days", "Cycle Off Days"),
        ):
            value = resolved(field_name)

            if value is not None and value < 1:
                errors[field_name] = f"{label} must be at least 1."

        # Nol itu sah — artinya travel dianggap masuk blok kerja, dan
        # itu memang yang berlaku untuk site yang bisa ditempuh dalam
        # sehari. Yang ditolak cuma nilai negatif.
        travel_days = resolved("cycle_travel_days")

        if travel_days is not None and travel_days < 0:
            errors["cycle_travel_days"] = (
                "Travel Days cannot be negative."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class RotationPeriodSerializer(serializers.ModelSerializer):
    # Rencana shift normal blok ini, dibacakan dari lapis `BASELINE`.
    #
    # Ada di sini supaya pertanyaan "blok ini shift apa" punya jawaban
    # **di layar roster**, bukan cuma di kalender. Itu inti dari
    # menyusun roster sekali: yang menetapkan kapan bekerja dan yang
    # menetapkan shift normalnya adalah layar yang sama.
    #
    # Penyesuaian sengaja tidak ikut — yang ditampilkan rencananya,
    # bukan hasil akhirnya. Hasil akhir per tanggal milik Shift
    # Calendar, dan ia yang tahu tanggal mana yang disesuaikan.
    shift_plan = serializers.SerializerMethodField()

    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    period_type_label = serializers.CharField(
        source="get_period_type_display",
        read_only=True,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    purpose_name = serializers.CharField(
        source="purpose.name",
        read_only=True,
        default=None,
    )

    employee_leave_label = serializers.CharField(
        source="employee_leave.__str__",
        read_only=True,
        default=None,
    )

    # Disalin service dari dokumen induk. Dibiarkan bisa ditulis akan
    # memungkinkan periode menempel ke pegawai yang berbeda dari
    # pemilik dokumennya.
    employee = serializers.PrimaryKeyRelatedField(read_only=True)

    # Diisi service dengan nomor bebas berikutnya kalau form tidak
    # menyebutkannya — jalur baris sisipan. Tetap `required` di model.
    #
    # `default=None` bukan hiasan: `UniqueTogetherValidator` yang
    # dibangkitkan DRF dari constraint (rotation, sequence) memaksa setiap
    # field anggotanya hadir di payload dan membalas "This field is
    # required" lebih dulu, sebelum service sempat mengisinya —
    # `required=False` saja tidak cukup untuk melewatinya.
    sequence = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = RotationPeriod
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee",
            "employee_name",
            "employee_number",
            "period_type_label",
            "status_label",
            "purpose_name",
            "employee_leave_label",
            "shift_plan",
        ]

    def get_shift_plan(self, obj) -> str:
        """
        `"SHIFT-1 → SHIFT-3 → SHIFT-2"` untuk blok kerja; `""` selebihnya.

        Hari off dan hari perjalanan tidak punya shift, dan menuliskan
        satu pun di sana akan membuat orang mengira ada kewajiban
        presensi di blok istirahatnya.

        Barisnya diambil sekali per pegawai per request lalu disimpan di
        `context`. Tanpa itu, satu dokumen berisi tiga puluh periode
        berarti tiga puluh query untuk jawaban yang sumbernya sama.
        """
        if obj.segment_type != RosterSegmentType.WORK:
            return ""

        cache = self.context.setdefault("_shift_plan_rows", {})

        rows = cache.get(obj.employee_id)

        if rows is None:
            rows = list(
                EmployeeShiftAssignment.objects
                .filter(
                    employee_id=obj.employee_id,
                    is_deleted=False,
                    layer=ShiftAssignmentLayer.BASELINE,
                )
                .select_related("shift")
                .order_by("start_date"),
            )

            cache[obj.employee_id] = rows

        codes = []

        for row in rows:
            if row.end_date < obj.start_date or row.start_date > obj.end_date:
                continue

            # Hari pemulihan tidak menunjuk shift, dan menuliskannya
            # sebagai langkah perputaran akan membuat "SHIFT-3 → ? →
            # SHIFT-2" terbaca seperti master yang bolong. Yang
            # ditampilkan kolom ini urutan shift-nya; hari pemulihan
            # milik kalender, yang tahu tanggal mana yang mana.
            if row.shift_id is None:
                continue

            code = row.shift.code

            # Berurutan dan sama = satu sebutan. Blok yang dipotong
            # penyesuaian rentang bisa meninggalkan dua baris baseline
            # bersebelahan dengan shift yang sama, dan "SHIFT-1 →
            # SHIFT-1" terbaca seperti data ganda.
            if not codes or codes[-1] != code:
                codes.append(code)

        return " → ".join(codes)

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        start_date = resolved("start_date")
        end_date = resolved("end_date")

        if start_date and end_date and end_date < start_date:
            errors["end_date"] = (
                "End Date cannot be earlier than Start Date."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
