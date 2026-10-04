from django.utils import timezone

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.api.leave.rules import LeaveRuleEvaluator
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import (
    TravelArrangement,
    TravelRequest,
    TravelRequestPurpose,
)
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


class TravelRequestSerializer(serializers.ModelSerializer):
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

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # Kepala formulir TR. Semuanya dibaca dari relasi pegawai, tidak
    # disalin ke dokumen: kalau departemen atau email pegawai
    # dikoreksi, TR yang belum terbang harus ikut betul.
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

    point_of_hire_name = serializers.CharField(
        source="employee.employment.point_of_hire.name",
        read_only=True,
        default=None,
    )

    join_date = serializers.DateField(
        source="employee.employment.join_date",
        read_only=True,
        default=None,
    )

    work_email = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()

    rotation_period_label = serializers.CharField(
        source="rotation_period.__str__",
        read_only=True,
        default=None,
    )

    # Dijumlahkan service dari baris tujuan; menulisnya lewat form
    # hanya akan ditimpa pada sinkronisasi berikutnya.
    total_days = serializers.IntegerField(read_only=True)

    # Boleh dikosongkan supaya service bisa menyalinnya dari blok
    # jadwal yang ditunjuk (`apply_rotation_period`). Kalau dibiarkan
    # `required` bawaan model, validasi DRF menolak lebih dulu dan
    # jalur pengisian otomatis itu tidak pernah kepakai — pemanggil API
    # jadi wajib mengetik ulang tanggal yang sudah ada di periodenya.
    # Pengajuan tanpa blok jadwal tetap ditolak, penjagaannya pindah ke
    # `full_clean()`.
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    # "Balance of F.B" di kepala formulir.
    leave_balances = serializers.SerializerMethodField()

    approval = serializers.SerializerMethodField()

    purpose_count = serializers.SerializerMethodField()

    # Penanda "dokumen ini masih boleh disunting", dibaca dari property
    # model — bukan daftar status kedua. Yang memakainya adalah layar:
    # tab Travel Purpose/Arrangement/Accommodation dikunci lewat
    # `readonly_when` yang menunjuk field ini, jadi tombol tambah dan
    # sunting tidak ditawarkan untuk baris yang `assert_editable` toh
    # akan tolak.
    is_editable = serializers.BooleanField(read_only=True)

    class Meta:
        model = TravelRequest
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "company_name",
            "location_name",
            "status_label",
            "department_name",
            "section_name",
            "position_name",
            "point_of_hire_name",
            "join_date",
            "work_email",
            "phone_number",
            "rotation_period_label",
            "total_days",
            "leave_balances",
            "approval",
            "purpose_count",
            "is_editable",
            # Berpindah lewat alur persetujuan, bukan lewat form.
            # Dibiarkan bisa ditulis akan memungkinkan orang menandai
            # dokumennya sendiri "Disetujui".
            "status",
        ]

    def get_work_email(self, obj) -> str | None:
        employee = obj.employee

        return employee.work_email or employee.personal_email or None

    def get_phone_number(self, obj) -> str | None:
        employee = obj.employee

        return employee.mobile or employee.phone or None

    def get_purpose_count(self, obj) -> int:
        return len(
            [
                purpose
                for purpose in obj.purposes.all()
                if not purpose.is_deleted
            ],
        )

    def get_leave_balances(self, obj) -> list[dict]:
        """
        Sisa saldo pegawai untuk tahun dokumen ini, satu baris per jenis
        cuti.

        Tidak dibatasi ke satu jenis "field break": jenis cuti itu
        master per tenant, jadi menebak salah satunya di kode berarti
        ada tenant yang kartunya selalu kosong.
        """
        year = (obj.start_date or timezone.localdate()).year

        return [
            {
                "leave_type": balance.leave_type_id,
                "code": balance.leave_type.code,
                "name": balance.leave_type.name,
                "remaining": str(balance.remaining),
            }
            for balance in obj.employee.leave_balances.all()
            if not balance.is_deleted and balance.year == year
        ]

    def get_approval(self, obj) -> dict | None:
        """
        Keadaan persetujuan + baris tanda tangan yang dicetak di kaki
        formulir.

        Yang diambil pengajuan terakhir, bukan yang aktif saja: dokumen
        yang sudah disetujui tidak punya pengajuan aktif, tapi justru
        itu yang harus tercetak.
        """
        workflow = WorkflowService.history_for(
            document=obj,
            module="hr",
            document_type="travel_request",
        ).first()

        if workflow is None:
            return None

        user = getattr(
            self.context.get("request"),
            "user",
            None,
        )

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
                return (
                    row.approver.get_full_name()
                    or row.approver.email
                )

            return None

        return {
            "instance_id": workflow.pk,
            "status": workflow.status,
            "status_label": workflow.get_status_display(),
            "flow": workflow.definition.name,
            "submitted_at": workflow.submitted_at,
            "completed_at": workflow.completed_at,
            # Dihitung, bukan ditebak dari status: menunggu persetujuan
            # orang lain dan menunggu persetujuan Anda sendiri terlihat
            # sama dari kolom status.
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
                    # Siapa yang benar-benar menekan tombolnya, kalau
                    # bukan approver-nya sendiri. Yang menandatangani
                    # atas nama orang lain harus terbaca di formulir.
                    "acted_by": (
                        (
                            row.acted_by.get_full_name()
                            or row.acted_by.email
                        )
                        if row.was_delegated
                        else None
                    ),
                }
                for row in rows
            ],
        }

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        start = resolved("start_date")
        end = resolved("end_date")

        if start and end and end < start:
            raise serializers.ValidationError(
                {
                    "end_date": (
                        "End Date cannot be earlier than Start Date."
                    ),
                },
            )

        return attrs


class TravelRequestPurposeSerializer(serializers.ModelSerializer):
    purpose_name = serializers.CharField(
        source="purpose.name",
        read_only=True,
        default=None,
    )

    # Ditampilkan di grid supaya pengisinya tahu baris mana yang akan
    # memotong saldo — tanpa itu Field Break dan Cuti Tahunan terlihat
    # sama persis di tabel.
    deducts_leave = serializers.BooleanField(
        source="purpose.deducts_leave",
        read_only=True,
        default=False,
    )

    employee_leave_label = serializers.CharField(
        source="employee_leave.__str__",
        read_only=True,
        default=None,
    )

    # Aturan jenis cuti yang berlaku untuk baris ini — bentuk yang
    # sama persis dengan `policy_rules` di modul Cuti, karena memang
    # evaluator yang sama (`LeaveRuleEvaluator` lewat
    # `EmployeeLeaveService.evaluate_rules`). Travel Request tidak
    # boleh punya pembacaan Leave Policy sendiri: dua salinan aturan
    # yang harus tetap sama adalah persis cara selisih diam-diam lahir
    # di salah satunya.
    #
    # Kenapa baris TR perlu melihatnya sama sekali: `deducts_leave`
    # cuma bisa bilang "memotong", sedangkan yang menentukan berapa
    # dan apakah ada yang bisa dipotong adalah Leave Policy. Baris
    # yang aturannya ternyata tidak bersaldo (`uses_balance=False`)
    # atau yang harinya melebihi `max_days` sekarang terbaca **sebelum**
    # pengajuannya disetujui, bukan lewat log sesudahnya.
    #
    # `None` untuk baris yang memang tidak menyentuh cuti (Field Break)
    # atau yang masternya belum menunjuk Leave Type — dict kosong akan
    # terbaca "sudah dinilai, bersih".
    policy_rules = serializers.SerializerMethodField()

    # Diisi service dengan nomor bebas berikutnya kalau form tidak
    # menyebutkannya. `default=None` bukan hiasan: `UniqueTogetherValidator`
    # yang dibangkitkan DRF dari constraint (request, sequence) memaksa
    # setiap field anggotanya hadir di payload dan membalas "This field
    # is required" sebelum service sempat mengisinya.
    sequence = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = TravelRequestPurpose
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "purpose_name",
            "deducts_leave",
            "employee_leave_label",
            "policy_rules",
            # Diterbitkan service saat pengajuan disetujui.
            "employee_leave",
            # Ditulis `issue_leave_records`, dibaca `cancel_leave_records`.
            # Kalau bisa dikirim dari luar, catatan cuti milik HR yang
            # cuma diadopsi bisa ditandai "terbit dari dokumen ini" —
            # dan ikut dibatalkan berikut saldonya.
            "leave_issued",
        ]

    def get_policy_rules(self, obj) -> dict | None:
        """
        Evaluator-nya dipegang di `serializer.context`, bukan dibuat
        per baris: satu dokumen berisi beberapa baris yang lazimnya
        menunjuk Leave Type yang sama, dan resolver tanpa memo berarti
        satu query master untuk tiap barisnya. Pola yang sama dengan
        `LeaveSerializer.get_policy_rules`.
        """
        purpose = obj.purpose

        if purpose is None or not purpose.deducts_leave:
            return None

        leave_type = purpose.leave_type

        if leave_type is None:
            return None

        employee = getattr(obj.request, "employee", None)

        if employee is None:
            return None

        evaluator = self.context.get("_leave_rule_evaluator")

        if evaluator is None:
            evaluator = LeaveRuleEvaluator()

            self.context["_leave_rule_evaluator"] = evaluator

        # Sebentuk dengan modul Cuti: riwayat dan kartu saldo dua query
        # per baris untuk keterangan yang tidak muat di kolom tabel mana
        # pun, jadi layar daftar melewatinya. `history_evaluated` /
        # `balance_evaluated` di payload yang membedakan "sudah dicari,
        # bersih" dari "belum dicari".
        is_row = isinstance(self.parent, serializers.ListSerializer)

        leave = obj.employee_leave

        if leave is not None:
            # Cutinya sudah terbit — yang dinilai catatan cuti yang
            # sungguhan, dengan `total_days` hasil `LeaveDayCalculator`.
            # Menilai ulang dari tanggal baris TR akan menampilkan angka
            # yang tidak cocok dengan angka mana pun di kartu cutinya.
            return EmployeeLeaveService.evaluate_rules(
                instance=leave,
                evaluator=evaluator,
                with_history=not is_row,
                with_balance=not is_row,
            ).as_dict()

        # Belum terbit: penilaian **perkiraan** atas baris seperti yang
        # sedang diketik. `total_days` di sini hari kalender baris TR,
        # bukan hari kerja yang nanti dihitung `LeaveDayCalculator` —
        # angkanya bisa berbeda, dan yang ditampilkan memang perkiraan
        # sebelum pengajuannya disetujui.
        return EmployeeLeaveService.evaluate_rules(
            data={
                "employee": employee,
                "leave_type": leave_type,
                "start_date": obj.start_date,
                "total_days": obj.total_days,
                "uploaded_file": None,
            },
            evaluator=evaluator,
            with_history=not is_row,
            with_balance=not is_row,
        ).as_dict()

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        start = resolved("start_date")
        end = resolved("end_date")

        if start and end and end < start:
            raise serializers.ValidationError(
                {
                    "end_date": (
                        "End Date cannot be earlier than Start Date."
                    ),
                },
            )

        return attrs


class TravelArrangementSerializer(serializers.ModelSerializer):
    direction_label = serializers.CharField(
        source="get_direction_display",
        read_only=True,
    )

    transport_mode_name = serializers.CharField(
        source="transport_mode.name",
        read_only=True,
        default=None,
    )

    accommodation_type_name = serializers.CharField(
        source="accommodation_type.name",
        read_only=True,
        default=None,
    )

    accommodation_nights = serializers.IntegerField(read_only=True)

    # Diisi service dengan nomor etape berikutnya di arah yang sama.
    # `default=None` bukan hiasan: `UniqueTogetherValidator` yang
    # dibangkitkan DRF dari constraint (request, direction, sequence)
    # memaksa setiap field anggotanya hadir di payload dan membalas
    # "This field is required" sebelum service sempat mengisinya.
    sequence = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )

    # Opsional di payload, tetap NOT NULL di tabel: baris yang dibuat
    # dari tab Accommodation tidak punya kolom Departure Date, dan
    # service mengisinya dari check-in (`apply_departure_from_stay`)
    # atau menolaknya dengan pesan yang menunjuk kolomnya.
    travel_start_date = serializers.DateField(required=False)

    class Meta:
        model = TravelArrangement
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "direction_label",
            "transport_mode_name",
            "accommodation_type_name",
            "accommodation_nights",
        ]

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        travel_start = resolved("travel_start_date")
        travel_end = resolved("travel_end_date")

        if travel_start and travel_end and travel_end < travel_start:
            errors["travel_end_date"] = (
                "Arrival Date cannot be earlier than Departure Date."
            )

        checkin = resolved("accommodation_checkin")
        checkout = resolved("accommodation_checkout")

        if checkin and checkout and checkout < checkin:
            errors["accommodation_checkout"] = (
                "Check-out cannot be earlier than check-in."
            )

        # Nomor etape yang bentrok. Diperiksa di sini juga, bukan hanya
        # lewat constraint database: IntegrityError membalas 500,
        # sedangkan pesan ini sampai ke form sebagai 400 yang terbaca.
        # Hanya kalau nomornya diketik — yang dikosongkan diisi service
        # dengan nomor bebas berikutnya.
        request_obj = resolved("request")
        direction = resolved("direction")
        sequence = attrs.get("sequence")

        if request_obj is not None and direction and sequence:
            duplicate = (
                TravelArrangement.objects
                .filter(
                    request=request_obj,
                    direction=direction,
                    sequence=sequence,
                    is_deleted=False,
                )
                .exclude(pk=getattr(instance, "pk", None))
                .exists()
            )

            if duplicate:
                errors["sequence"] = (
                    f"Etape #{sequence} sudah ada untuk arah tersebut."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
