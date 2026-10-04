from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.api.leave.rules import LeaveRuleEvaluator
from apps.hr.api.leave.scope import LEAVE_DATA_SCOPE
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import EmployeeLeave, LeaveBalance
from apps.uploads.api.attach import guard_attachment
from apps.uploads.api.serializers import UploadedFileSerializer
from apps.uploads.models import UploadedFile
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


# Izin yang menjawab "boleh menyunting baris ini" — sama persis dengan
# yang dipakai `filter_queryset()` saat PATCH.
CHANGE_PERMISSION = "hr.change_employeeleave"


class EmployeeLeaveSerializer(serializers.ModelSerializer):
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

    leave_type_name = serializers.CharField(
        source="leave_type.name",
        read_only=True,
        default=None,
    )

    leave_reason_name = serializers.CharField(
        source="leave_reason.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # **Bukan field yang boleh dipilih lewat form.** Status cuti hanya
    # berpindah lewat jalurnya sendiri: `submit/` menyalakan alurnya,
    # alur itu yang menentukan APPROVED/REJECTED, `withdraw/`
    # mengembalikannya ke DRAFT, dan pencatatan administratif
    # (RECORDED) punya aksi sendiri yang menuntut
    # `hr.record_employeeleave`.
    #
    # Sebelum ini ia field biasa, dan karena itu satu POST berisi
    # `"status": "approved"` sudah cukup untuk memotong saldo tanpa
    # satu tanda tangan pun — terbukti untuk keempat jenis aktor di
    # tenant demo, termasuk pegawai biasa atas cutinya sendiri.
    status = serializers.CharField(read_only=True)

    uploaded_file = serializers.PrimaryKeyRelatedField(
        queryset=UploadedFile.objects.active(),
        required=False,
        allow_null=True,
    )

    uploaded_file_detail = UploadedFileSerializer(
        source="uploaded_file",
        read_only=True,
    )

    # Keadaan persetujuan + kotak tanda tangannya. Bentuknya sama
    # dengan `approval` di Travel Request supaya komponen jejak
    # persetujuan di FE bisa dipakai ulang apa adanya.
    workflow = serializers.SerializerMethodField()

    # Aturan jenis cuti yang berlaku untuk dokumen ini, beserta
    # temuannya (`policy_rules.findings`) dan riwayat pemakaiannya.
    #
    # **Diturunkan saat dibaca, bukan disimpan.** Join Date, golongan
    # pegawai, dan aturannya sendiri semuanya bisa dibetulkan sesudah
    # dokumen ini dibuat — dan justru itu yang dilakukan HR terhadap
    # baris yang ditandai perlu diperiksa. Penilaian yang dibekukan
    # saat pembuatan tetap berbunyi sama sesudah sebabnya dibereskan,
    # dan sesudah itu tidak ada yang mempercayainya lagi. Pelajaran
    # yang sama dengan kolom Validation di Leave Opening Balance.
    #
    # Karena diturunkan, peringatannya ikut terlihat di **setiap**
    # meja: pengaju, HR, atasan, dan HR Manager membaca angka yang
    # sama pada hari mereka membukanya.
    policy_rules = serializers.SerializerMethodField()

    # Keadaan **dokumennya**: status yang boleh disunting siapa pun yang
    # berhak. Tidak tahu-menahu soal pembacanya — dan itu memang
    # tugasnya, karena `EmployeeLeaveService.assert_editable` memakai
    # property yang sama.
    is_editable = serializers.BooleanField(read_only=True)

    # Keadaan dokumen **untuk pembacanya**. `is_editable` saja tidak
    # cukup sejak approver boleh membuka dokumen yang bukan miliknya:
    # dokumen yang dikembalikan berstatus DRAFT — `is_editable` benar —
    # padahal yang boleh membetulkannya cuma pengajunya, bukan atasan
    # yang mengembalikannya. Layar yang cuma membaca `is_editable` akan
    # menawarkan formulir yang bisa diketik lalu ditolak API saat
    # disimpan.
    #
    # Ini kontrak read-only untuk FE (`readonly_when`), **bukan**
    # penjagaannya: yang menolak tetap `assert_editable` di service dan
    # cakupan data di viewset.
    can_edit = serializers.SerializerMethodField()

    # Diberikan service saat record dibuat, tidak pernah dihitung ulang.
    # Dibiarkan bisa ditulis lewat form akan membuat dua cuti bisa
    # bernomor sama.
    document_number = serializers.CharField(read_only=True)

    class Meta:
        model = EmployeeLeave
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "company_name",
            "branch_name",
            "location_name",
            "leave_type_name",
            "leave_reason_name",
            "status_label",
            "uploaded_file_detail",
            "workflow",
            "policy_rules",
            "is_editable",
            "can_edit",
            "document_number",
        ]

    # ------------------------------------------------------------------
    # Boleh disunting pembacanya?
    # ------------------------------------------------------------------

    def _editable_pks(self) -> set:
        """
        Kunci baris yang **masuk cakupan data** pembacanya, dihitung
        sekali per request.

        Satu query untuk seluruh halaman, bukan satu per baris: daftar
        cuti dua puluh baris tidak boleh berubah jadi dua puluh query
        untuk satu kolom boolean.
        """
        cached = self.context.get("_leave_editable_pks")

        if cached is not None:
            return cached

        from apps.accounts.scoping import DataScopeService

        instance = self.instance

        if instance is None:
            rows = []
        elif isinstance(instance, EmployeeLeave):
            rows = [instance]
        else:
            rows = list(instance)

        pks = [row.pk for row in rows if getattr(row, "pk", None)]

        if not pks:
            cached = set()
        else:
            user = getattr(self.context.get("request"), "user", None)

            cached = set(
                DataScopeService.filter(
                    EmployeeLeave.objects.filter(pk__in=pks),
                    LEAVE_DATA_SCOPE,
                    user,
                    # Izin **ubah**, bukan izin baca: yang dijawab kolom
                    # ini "boleh saya menyunting baris ini", dan sejak
                    # `filter_queryset()` memakai `change_employeeleave`
                    # untuk PATCH, memakai izin baca di sini membuat
                    # layar menawarkan formulir yang pasti dibalas 404.
                    # Terbukti pada pemegang dua role: cakupan baca
                    # se-company, cakupan ubah cuma `own`.
                    required_permission=CHANGE_PERMISSION,
                )
                .values_list("pk", flat=True)
            )

        self.context["_leave_editable_pks"] = cached

        return cached

    def get_can_edit(self, obj) -> bool:
        """
        Tiga syarat, dan ketiganya memang syarat yang berbeda:

        1. **Statusnya** boleh disunting (`is_editable`);
        2. pembacanya punya izin mengubah tabel ini (`ModelPermission`);
        3. barisnya ada di **cakupan datanya sendiri** — bukan cuma
           terlihat karena ia peserta alur.

        Yang ketiga inti perubahannya: approver membuka dokumen untuk
        **menilainya**, bukan untuk membetulkannya. Isi yang salah
        dikembalikan lewat Return, dan yang membetulkan pengajunya.
        """
        if not obj.is_editable:
            return False

        user = getattr(self.context.get("request"), "user", None)

        if user is None or not getattr(user, "is_authenticated", False):
            return False

        if user.is_superuser:
            return True

        if not user.has_perm("hr.change_employeeleave"):
            return False

        return obj.pk in self._editable_pks()

    def get_policy_rules(self, obj) -> dict:
        """
        Evaluator-nya dipegang di `serializer.context`, bukan dibuat
        per baris: satu halaman daftar berisi dua puluh cuti yang
        lazimnya menunjuk aturan yang sama, dan resolver tanpa memo
        berarti dua puluh query untuk satu baris master.
        """
        evaluator = self.context.get("_leave_rule_evaluator")

        if evaluator is None:
            evaluator = LeaveRuleEvaluator()

            self.context["_leave_rule_evaluator"] = evaluator

        is_row = isinstance(self.parent, serializers.ListSerializer)

        return EmployeeLeaveService.evaluate_rules(
            instance=obj,
            evaluator=evaluator,
            # Riwayat cuma dicari saat satu dokumen dibuka. Di layar
            # daftar ia dua query per baris untuk keterangan yang
            # tidak muat di kolom mana pun — dan `history_evaluated`
            # di payload yang membedakan "sudah dicari, bersih" dari
            # "belum dicari", supaya keduanya tidak terbaca sama.
            with_history=not is_row,
            # Sebentuk dengan riwayat, dan karena alasan yang sama:
            # satu query per baris untuk angka yang tidak muat di kolom
            # tabel mana pun. `balance_evaluated` di payload yang
            # membedakan "sudah diperiksa, cukup" dari "belum
            # diperiksa".
            with_balance=not is_row,
        ).as_dict()

    def get_workflow(self, obj) -> dict | None:
        """
        Pengajuan terakhir dokumen ini, bukan yang aktif saja: cuti yang
        sudah disetujui tidak punya pengajuan berjalan, tapi justru itu
        yang harus terlihat di layar.

        Mengembalikan None untuk cuti jalur pencatatan (RECORDED) —
        yang memang tidak pernah lewat alur mana pun.
        """
        workflow = WorkflowService.history_for(
            document=obj,
            module="hr",
            document_type="leave_request",
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

        # `status` **ditolak**, bukan diabaikan diam-diam.
        #
        # Field read-only pada DRF cuma dibuang dari `validated_data`,
        # jadi formulir yang mengirim `"status": "approved"` akan
        # mendapat 201 berisi dokumen DRAFT — dan yang mengirimnya tidak
        # pernah tahu permintaannya tidak dijalankan. Untuk kolom yang
        # menentukan sah atau tidaknya sebuah cuti, diam adalah jawaban
        # yang salah: jalur yang benar (`submit/`, `record/`, `cancel/`)
        # harus disebutkan, bukan ditebak.
        initial = getattr(self, "initial_data", None)

        if isinstance(initial, dict) and "status" in initial:
            raise serializers.ValidationError(
                {
                    "status": (
                        "Status cuti tidak diisi dari formulir. Ajukan "
                        "lewat 'submit', catat lewat 'record', "
                        "batalkan lewat 'cancel'."
                    ),
                },
            )

        # Lampiran: aktif, milik yang menempel, dan belum dipakai
        # dokumen lain. Aturannya di `FileAccessService` — menempelkan
        # berkas memberi hak baca, jadi itu pertanyaan otorisasi.
        guard_attachment(self, "uploaded_file", attrs)

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        start_date = resolved("start_date")
        end_date = resolved("end_date")
        is_half_day = resolved("is_half_day", False)
        total_days = resolved("total_days")

        errors = {}

        if start_date and end_date and end_date < start_date:
            errors["end_date"] = (
                "End Date cannot be earlier than Start Date."
            )

        if (
            is_half_day
            and start_date
            and end_date
            and start_date != end_date
        ):
            errors["is_half_day"] = (
                "Half day only applies to a single-day leave."
            )

        # Nol sengaja dibolehkan — lihat EmployeeLeave.clean().
        if total_days is not None and total_days < 0:
            errors["total_days"] = (
                "Total Days cannot be negative."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class LeaveBalanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    leave_type_name = serializers.CharField(
        source="leave_type.name",
        read_only=True,
        default=None,
    )

    # `used` diisi oleh EmployeeLeaveService dari record cuti, jadi
    # tidak boleh ditulis lewat form — kalau bisa, angkanya akan
    # ditimpa lagi pada sinkronisasi berikutnya.
    used = serializers.DecimalField(
        max_digits=6,
        decimal_places=1,
        read_only=True,
    )

    remaining = serializers.DecimalField(
        max_digits=7,
        decimal_places=1,
        read_only=True,
    )

    # Kantong saldo awal migrasi. Dijumlah ulang dari dokumen
    # `LeaveOpeningBalance`, jadi tidak boleh ditulis lewat form —
    # angka yang diketik di sini akan ditimpa pada sinkronisasi
    # berikutnya, dan yang mengetiknya tidak akan pernah tahu.
    opening_balance = serializers.DecimalField(
        max_digits=6,
        decimal_places=1,
        read_only=True,
    )

    opening_expires_at = serializers.DateField(read_only=True)

    # Hasil alokasi FIFO, ditulis bersama `used`.
    opening_used = serializers.DecimalField(
        max_digits=6,
        decimal_places=1,
        read_only=True,
    )

    carried_over_used = serializers.DecimalField(
        max_digits=6,
        decimal_places=1,
        read_only=True,
    )

    advance_used = serializers.DecimalField(
        max_digits=6,
        decimal_places=1,
        read_only=True,
    )

    entitlement_used = serializers.DecimalField(
        max_digits=7,
        decimal_places=1,
        read_only=True,
    )

    opening_remaining = serializers.DecimalField(
        max_digits=7,
        decimal_places=1,
        read_only=True,
    )

    carried_over_remaining = serializers.DecimalField(
        max_digits=7,
        decimal_places=1,
        read_only=True,
    )

    class Meta:
        model = LeaveBalance
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "leave_type_name",
            "used",
            "remaining",
            "opening_balance",
            "opening_expires_at",
            "opening_used",
            "opening_forfeited",
            "carried_over_used",
            "advance_used",
            "entitlement_used",
            "opening_remaining",
            "carried_over_remaining",
        ]

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        year = resolved("year")

        if year is not None and not (2000 <= year <= 2100):
            errors["year"] = "Year must be between 2000 and 2100."

        if (resolved("entitlement") or 0) < 0:
            errors["entitlement"] = "Entitlement cannot be negative."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
