"""
Orkestrasi payroll run.

Alurnya: Generate Employees → (Input) → Calculate → Validate → Review →
Submit → Approve → Finalize → Payslip. Tiap langkah punya pintu masuk
sendiri dan memeriksa statusnya sendiri; tidak ada langkah yang
mengandaikan pemanggilnya sudah memeriksa.

**Yang tidak dilakukan di sini:** menghitung. Aritmetikanya milik
`PayrollCalculationService`, yang tidak menyentuh database sama sekali.
Pemisahan itu yang membuat perhitungan bisa diuji tanpa membuat satu
pun run, dan membuat run bisa dihitung ulang berkali-kali tanpa
menyisakan setengah hasil.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from apps.accounts.scoping import DataScopeService

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    ACTIVE_SUCCESSOR_STATUSES,
    PayrollFindingLevel,
    PayrollInput,
    PayrollInputStatus,
    PayrollProrationMethod,
    PayrollRun,
    PayrollRunComponent,
    PayrollRunEmployee,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
    PayrollRunType,
    PayrollTaxBracket,
)
from apps.payroll.scoping import PAYROLL_RUN_SCOPE
from apps.payroll.services.accounting import PayrollAccountingError
from apps.payroll.services.bpjs import BpjsEmployeeFacts, BpjsResolver
from apps.payroll.services.calculation import (
    CalculationInput,
    PayrollCalculationService,
)
from apps.payroll.services.period import PayrollPeriodService
from apps.payroll.services.policy import PayrollPolicyService
from apps.payroll.services.setting import PayrollSettingService
from apps.payroll.services.sources import PayrollSourceService
from apps.payroll.services.validation import PayrollValidationService

ZERO = Decimal("0.00")
ONE = Decimal("1")

MODULE = "payroll"
DOCUMENT_TYPE = "payroll_run"


class PayrollRunService(BaseMasterService):
    model = PayrollRun

    WORKFLOW_MODULE = MODULE
    WORKFLOW_DOCUMENT_TYPE = DOCUMENT_TYPE

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @classmethod
    def get_queryset(cls):
        return (
            super()
            .get_queryset()
            .select_related(
                "period",
                "period__payroll_group",
                "company",
                "branch",
                "location",
                "department",
                "section",
            )
        )

    #: Wewenang yang dituntut Finalize, **sementara**.
    #:
    #: Yang benar `payroll.finalize_payrollrun` — izin tersendiri untuk
    #: tindakan yang berdampak keuangan, terpisah dari "boleh menyunting
    #: run". Izin itu menuntut migrasi (`Meta.permissions`) dan belum
    #: disetujui, jadi untuk sekarang gerbangnya memakai izin ubah yang
    #: sudah ada: siapa pun yang selama ini menjalankan payroll dari
    #: layar sudah memegangnya, sementara akun yang cuma bisa membaca —
    #: termasuk Finance Manager, yang memang hanya menyetujui — tidak.
    FINALIZE_PERMISSION = "payroll.change_payrollrun"

    @classmethod
    def assert_may_finalize(cls, *, run: PayrollRun, user=None) -> None:
        """
        Boleh mengunci run ini?

        Dijaga di **service**, bukan hanya di viewset: aksi `finalize/`
        tidak lewat `ModelPermission` (di sana hanya aksi CRUD baku
        yang dijaga), dan perintah manajemen maupun jalur lain yang
        menyusul tidak melewati viewset sama sekali.

        `user=None` berarti pemanggil internal tanpa konteks pengguna —
        hari ini hanya `manage.py tenant_command payroll_uat
        --finalize`, yang menjalankannya sudah memegang shell server.
        Jalur API **selalu** mengirim penggunanya.
        """
        if user is None:
            return

        if not getattr(user, "is_authenticated", False):
            raise PermissionDenied(
                "Hanya pengguna yang masuk yang bisa mengunci payroll.",
            )

        if getattr(user, "is_superuser", False):
            return

        if not user.has_perm(cls.FINALIZE_PERMISSION):
            raise PermissionDenied(
                "Anda tidak punya wewenang mengunci payroll run.",
            )

        # Wewenang menjawab "jenis data apa", cakupan menjawab "baris
        # milik siapa" — dan keduanya harus ditanyakan. Mesin yang sama
        # dengan penyaringan daftar, atas satu baris.
        visible = DataScopeService.filter(
            PayrollRun.objects.filter(pk=run.pk),
            PAYROLL_RUN_SCOPE,
            user,
            required_permission=cls.FINALIZE_PERMISSION,
        )

        if not visible.exists():
            raise PermissionDenied(
                "Payroll run ini berada di luar kewenangan data Anda.",
            )

    #: PF-0G — wewenang menerbitkan run koreksi.
    #:
    #: **Bukan** `change_payrollrun`: itu dipegang setiap operator yang
    #: menjalankan payroll, dan koreksi mencabut keberlakuan fakta
    #: akuntansi yang sudah terbit. Bukan izin Finance juga — yang
    #: memutuskan payroll-nya salah adalah payroll, yang memutuskan
    #: jurnalnya dibalik adalah Finance.
    CORRECT_PERMISSION = "payroll.correct_payrollrun"

    @classmethod
    def assert_may_correct(cls, *, target: PayrollRun, user=None) -> None:
        """
        Boleh menerbitkan koreksi atas run ini?

        Bentuk yang sama dengan `assert_may_finalize` dan FIN-B1/B2:
        izin eksplisit **dan** cakupan baris yang dihitung dari izin itu
        sendiri — cakupan luas dari role lain tidak meminjamkan wewenang
        koreksi.
        """
        if user is None:
            return

        if not getattr(user, "is_authenticated", False):
            raise PermissionDenied(
                "Hanya pengguna yang masuk yang bisa menerbitkan koreksi.",
            )

        if getattr(user, "is_superuser", False):
            return

        if not user.has_perm(cls.CORRECT_PERMISSION):
            raise PermissionDenied(
                "Anda tidak punya wewenang menerbitkan run koreksi.",
            )

        visible = DataScopeService.filter(
            PayrollRun.objects.filter(pk=target.pk),
            PAYROLL_RUN_SCOPE,
            user,
            required_permission=cls.CORRECT_PERMISSION,
        )

        if not visible.exists():
            raise PermissionDenied(
                "Run yang mau dikoreksi berada di luar kewenangan data "
                "Anda.",
            )

    @classmethod
    def active_successor(cls, target: PayrollRun):
        """
        Koreksi yang sedang menempati slot penerus `target`, atau `None`.

        Aturannya **sama persis** dengan constraint
        `uniq_active_payroll_run_successor` — keduanya membaca
        `ACTIVE_SUCCESSOR_STATUSES`.
        """
        return (
            PayrollRun.objects
            .filter(
                corrects_run=target,
                is_deleted=False,
                status__in=list(ACTIVE_SUCCESSOR_STATUSES),
            )
            .first()
        )

    @classmethod
    def assert_correctable(cls, target: PayrollRun) -> None:
        """
        Syarat akuntansi sebuah run boleh dikoreksi — **gagal tertutup**.

        Run lama (sebelum PF-0F), run yang gerbangnya menolak, dan run
        yang jurnalnya tidak pernah terbit **tidak** bisa dikoreksi lewat
        jalur ini: koreksi PF-0G mengganti proyeksi akuntansi yang ada,
        dan yang tidak punya proyeksi tidak punya yang diganti.
        Menormalkan run lama adalah proyek tersendiri (backfill), bukan
        efek samping koreksi.
        """
        from apps.payroll.services.accounting_bridge import (
            PayrollAccountingBridge,
        )

        if target.status != PayrollRunStatus.FINALIZED:
            raise PayrollAccountingError(
                f"Run {target.document_number or target.pk} belum "
                "difinalisasi.",
                code="correction_target_not_finalized",
            )

        state = PayrollAccountingBridge.projection_state(run=target)
        label = target.document_number or target.pk

        if not state["exists"]:
            raise PayrollAccountingError(
                f"Run {label} tidak punya kejadian akuntansi — run "
                "lama/historis dikoreksi lewat proyek normalisasi "
                "tersendiri, bukan lewat run koreksi.",
                code="correction_target_without_event",
            )

        if state["superseded"]:
            raise PayrollAccountingError(
                f"Run {label} sudah digantikan koreksi lain.",
                code="correction_target_superseded",
            )

        if not state["processed"] or not state["has_journal"]:
            raise PayrollAccountingError(
                f"Kejadian akuntansi run {label} belum menerbitkan jurnal.",
                code="correction_target_without_journal",
            )

    @classmethod
    def assert_editable(cls, instance: PayrollRun) -> None:
        if not instance.is_editable:
            raise ValidationError(
                {
                    "status": (
                        f"Payroll run berstatus "
                        f"{instance.get_status_display()} tidak bisa "
                        "diubah."
                    ),
                },
            )

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        period = data.get("period")

        if period is None:
            raise ValidationError(
                {"period": "Payroll Period wajib dipilih."},
            )

        target = data.get("corrects_run")

        is_correction = (
            data.get("run_type") == PayrollRunType.CORRECTION
            and target is not None
        )

        if period.is_locked and not is_correction:
            raise ValidationError(
                {
                    "period": (
                        "Periode ini sudah Finalized. Run baru hanya "
                        "boleh dibuat di periode yang belum dikunci."
                    ),
                },
            )

        if target is not None:
            # PF-0G. Pengecualian periode terkunci **hanya** untuk
            # koreksi yang relasinya sah: tipe koreksi, target final,
            # periode yang sama, wewenang koreksi, dan slot penerus yang
            # masih kosong. `run_type=correction` tanpa target tidak
            # membuka apa pun (lihat `PayrollRun._clean_correction`).
            data = cls._prepare_correction(data=data, target=target, user=user)

        # Company selalu ikut periodenya. Membiarkannya diisi form
        # berarti run bisa menunjuk company yang berbeda dari periode
        # yang melahirkannya, dan cakupan datanya jadi berdusta.
        data["company"] = period.company

        if not data.get("document_number"):
            data["document_number"] = DocumentNumberService.next(
                module=MODULE,
                document_type=DOCUMENT_TYPE,
                company=period.company,
                when=period.start_date,
            )

        if not data.get("name"):
            data["name"] = f"{period.name}"

        return data

    @classmethod
    def _prepare_correction(cls, *, data: dict, target: PayrollRun, user=None):
        """
        Menyiapkan run koreksi: wewenang, syarat target, dan slot penerus.

        **Targetnya dikunci** (`select_for_update`) sebelum slotnya
        diperiksa. Tanpa itu dua permintaan bersamaan sama-sama melihat
        slot kosong dan keduanya membuat koreksi — yang kedua memang
        akan ditolak constraint database, tapi sebagai `IntegrityError`
        di tengah transaksi, bukan sebagai penolakan yang bisa dibaca.
        """
        if data.get("run_type") != PayrollRunType.CORRECTION:
            raise ValidationError({
                "corrects_run": (
                    "Hanya run bertipe Correction yang boleh menunjuk run "
                    "yang dikoreksi."
                ),
            })

        locked = (
            PayrollRun.objects
            .select_for_update()
            .select_related("period", "company")
            .get(pk=target.pk)
        )

        cls.assert_may_correct(target=locked, user=user)
        cls.assert_correctable(locked)

        existing = cls.active_successor(locked)

        if existing is not None:
            raise ValidationError({
                "corrects_run": (
                    f"Run {locked.document_number or locked.pk} sudah punya "
                    f"koreksi aktif ({existing.document_number or existing.pk}"
                    f", {existing.get_status_display()}). Batalkan koreksi "
                    "itu dulu, atau koreksi koreksinya."
                ),
            })

        data["corrects_run"] = locked
        data["period"] = locked.period
        data["company"] = locked.company

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_editable(instance)

        # PF-0G. Relasi koreksi dinyatakan saat run dibuat dan tidak
        # pernah berpindah: seluruh jejak akuntansinya — payload,
        # digest, kejadian, supersesi — sudah menunjuk target itu.
        data.pop("corrects_run", None)
        data.pop("run_type", None)

        # Periode dan company tidak boleh berpindah setelah run berdiri:
        # baris pegawainya sudah dibuat untuk rentang tanggal periode
        # itu, dan menggesernya membuat angka yang sudah dihitung
        # menunjuk rentang yang berbeda tanpa satu pun tanda.
        data.pop("period", None)
        data.pop("company", None)

        return data

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        PayrollPeriodService.sync_status(period=instance.period, user=user)

        return super().after_create(instance=instance, user=user, **kwargs)

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        if instance.status not in (
            PayrollRunStatus.DRAFT,
            PayrollRunStatus.CANCELLED,
        ):
            raise ValidationError(
                {
                    "status": (
                        "Hanya run berstatus Draft atau Cancelled yang "
                        "bisa dihapus."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)

    # ------------------------------------------------------------------
    # Generate Employees
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def generate_employees(cls, *, run: PayrollRun, user=None) -> dict:
        """
        Menyusun daftar pegawai run ini dari data kepegawaian.

        Idempotent: dijalankan ulang, pegawai yang sudah ada tidak
        diduplikasi dan yang sudah tidak memenuhi syarat **ditandai
        excluded**, bukan dihapus. Baris yang menghilang tanpa jejak
        membuat "kenapa si A tidak dibayar bulan ini" tidak punya
        jawaban di dokumen mana pun.
        """
        cls.assert_editable(run)

        period = run.period

        employees = list(
            PayrollSourceService.eligible_employees(
                company=run.company,
                start_date=period.start_date,
                end_date=period.end_date,
                branch=run.branch,
                location=run.location,
                department=run.department,
                section=run.section,
                payroll_group=period.payroll_group,
            ),
        )

        existing = {
            line.employee_id: line
            for line in PayrollRunEmployee.objects.filter(
                run=run, is_deleted=False,
            )
        }

        eligible_ids = set()
        created = 0
        updated = 0

        for employee in employees:
            eligible_ids.add(employee.pk)

            line = existing.get(employee.pk)

            if line is None:
                line = PayrollRunEmployee(run=run, employee=employee)
                line.created_by = user
                created += 1
            else:
                updated += 1

            cls._apply_employee_snapshot(
                line=line,
                employee=employee,
                period=period,
            )

            line.updated_by = user
            line.full_clean()
            line.save()

        # Yang tidak lagi memenuhi syarat: dinonaktifkan, tidak dihapus.
        stale = [
            line
            for employee_id, line in existing.items()
            if employee_id not in eligible_ids
        ]

        for line in stale:
            if line.is_excluded:
                continue

            line.is_excluded = True
            line.status = PayrollRunEmployeeStatus.EXCLUDED
            line.exclusion_reason = (
                "Tidak lagi memenuhi syarat pada generate ulang "
                "(penempatan, tanggal masuk, atau tanggal berhenti)."
            )
            line.updated_by = user
            line.save(
                update_fields=[
                    "is_excluded",
                    "status",
                    "exclusion_reason",
                    "updated_by",
                    "updated_at",
                ],
            )

        run.employee_count = len(eligible_ids)
        run.status = PayrollRunStatus.PROCESSING
        run.updated_by = user
        run.save(
            update_fields=[
                "employee_count",
                "status",
                "updated_by",
                "updated_at",
            ],
        )

        PayrollPeriodService.sync_status(period=period, user=user)

        return {
            "created": created,
            "updated": updated,
            "excluded": len(stale),
            "total": len(eligible_ids),
        }

    @classmethod
    def _apply_employee_snapshot(cls, *, line, employee, period) -> None:
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        # Assignment dibaca pada tanggal cutoff, bukan hari ini:
        # payroll periode lalu yang dihitung ulang harus memakai gaji
        # yang berlaku waktu itu.
        assignment = PayrollSourceService.current_assignment(
            employee=employee,
            on_date=period.effective_cutoff,
        )

        line.payroll_assignment = assignment

        line.company = getattr(organization, "company", None)
        line.branch = getattr(organization, "branch", None)
        line.location = getattr(organization, "location", None)
        line.division = getattr(organization, "division", None)
        line.department = getattr(organization, "department", None)
        line.section = getattr(organization, "section", None)
        line.cost_center = getattr(organization, "cost_center", None)
        line.position = getattr(organization, "position", None)

        line.join_date = getattr(employment, "join_date", None)
        line.termination_date = getattr(employment, "termination_date", None)

        if assignment is not None:
            # Kebijakan perhitungan ikut dibekukan bersama sisa
            # snapshot, dan itu yang membuat effective date-nya bekerja
            # tanpa mesin kedua: assignment yang berlaku pada cutoff
            # periode ini membawa kebijakannya, jadi payroll Juni
            # memakai kebijakan lama walaupun assignment Juli sudah
            # menunjuk kebijakan baru.
            line.payroll_policy = assignment.payroll_policy
            line.payroll_group = assignment.payroll_group
            line.salary_grade = assignment.salary_grade
            line.salary_level = assignment.salary_level
            line.tax_status = assignment.tax_status
            line.overtime_group = assignment.overtime_group
            line.allowance_template = assignment.allowance_template
            line.deduction_template = assignment.deduction_template
            line.currency = assignment.currency
            line.payment_method = assignment.payment_method or ""
            line.basic_salary = Decimal(assignment.basic_salary or 0)
        else:
            line.payroll_policy = None
            line.basic_salary = ZERO

        line.period_days = (period.end_date - period.start_date).days + 1

        if line.is_excluded and line.employee_id:
            # Generate ulang menghidupkan kembali baris yang sebelumnya
            # gugur karena datanya sudah diperbaiki.
            line.is_excluded = False
            line.exclusion_reason = ""

        if line.status in (
            PayrollRunEmployeeStatus.EXCLUDED,
            "",
        ):
            line.status = PayrollRunEmployeeStatus.PENDING

    # ------------------------------------------------------------------
    # Calculate
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def calculate(cls, *, run: PayrollRun, user=None) -> dict:
        """
        Menghitung ulang seluruh baris run.

        Selalu **seluruhnya**, bukan hanya yang berubah: payroll harus
        reproducible, dan hasil sebagian adalah cara membuat total run
        tidak sama dengan jumlah barisnya.
        """
        cls.assert_editable(run)

        period = run.period

        lines = list(
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False, is_excluded=False)
            .select_related(
                "employee",
                "overtime_group",
                "tax_status",
                "allowance_template",
                "deduction_template",
                "payroll_assignment",
                "payroll_policy",
            )
        )

        brackets = list(
            PayrollTaxBracket.objects
            .filter(is_deleted=False, is_active=True)
            .order_by("sequence", "income_from")
        )

        # Dibaca sekali untuk seluruh run, bukan per pegawai: sebuah run
        # dengan 500 pegawai kalau tidak akan membaca master yang sama
        # 500 kali.
        allowance_cache: dict[int, list] = {}
        deduction_cache: dict[int, list] = {}
        tier_cache: dict[int, list] = {}

        # Kebijakan kelompok yang sudah diresolusi, dikunci id-nya.
        # Resolusinya sendiri tidak menyentuh database — yang dihemat
        # cache ini bukan query melainkan penggabungan berulang untuk
        # jawaban yang sama.
        policy_cache: dict[int | None, Any] = {}

        inputs_by_employee = cls._inputs_by_employee(period=period)

        # Master BPJS dibaca **sekali** untuk seluruh run, dengan
        # tanggal jangkar yang sama dengan yang dipakai memilih
        # assignment: cutoff periode. Jangkar yang berbeda berarti
        # assignment dan aturan BPJS bisa tidak sepakat sedang bulan
        # apa.
        bpjs_anchor = period.cutoff_date or period.end_date

        bpjs_context = BpjsResolver.build_context(
            employee_ids=[line.employee_id for line in lines],
            anchor_date=bpjs_anchor,
        )

        # Kebijakan prorata dibaca **sekali** untuk seluruh run:
        # pemiliknya perusahaan, jadi membacanya ulang tiap baris cuma
        # menghasilkan ratusan query dengan jawaban yang sama.
        # Kebijakan **perusahaan** — lapis paling bawah. Kebijakan
        # kelompok yang menimpanya dibaca per pegawai, lewat snapshot
        # yang sudah menempel di barisnya.
        policy = PayrollSettingService.resolve_policy(company=run.company)
        attendance_policy = PayrollSettingService.resolve_attendance_policy(
            company=run.company,
        )

        calculated = 0
        failed = 0

        for line in lines:
            try:
                cls._calculate_line(
                    line=line,
                    period=period,
                    brackets=brackets,
                    allowance_cache=allowance_cache,
                    deduction_cache=deduction_cache,
                    tier_cache=tier_cache,
                    policy_cache=policy_cache,
                    inputs=inputs_by_employee.get(line.employee_id, []),
                    policy=policy,
                    attendance_policy=attendance_policy,
                    bpjs_context=bpjs_context,
                    user=user,
                )
                calculated += 1
            except Exception as error:  # noqa: BLE001
                # Satu pegawai yang gagal tidak boleh membatalkan
                # perhitungan 499 lainnya. Kegagalannya tercatat di
                # barisnya sendiri dan naik jadi ERROR di validasi.
                failed += 1

                line.status = PayrollRunEmployeeStatus.ERROR
                line.findings = [
                    {
                        "level": PayrollFindingLevel.ERROR,
                        "code": "calculation_failed",
                        "message": str(error),
                    },
                ]
                line.save(
                    update_fields=["status", "findings", "updated_at"],
                )

        cls._refresh_totals(run=run)

        run.status = PayrollRunStatus.REVIEW
        run.calculated_at = timezone.now()
        run.calculated_by = user
        run.warnings_acknowledged = False
        run.acknowledged_at = None
        run.acknowledged_by = None
        run.updated_by = user
        run.save(
            update_fields=[
                "status",
                "calculated_at",
                "calculated_by",
                "warnings_acknowledged",
                "acknowledged_at",
                "acknowledged_by",
                "updated_by",
                "updated_at",
            ],
        )

        summary = cls.validate(run=run, user=user)

        PayrollPeriodService.sync_status(period=period, user=user)

        return {
            "calculated": calculated,
            "failed": failed,
            "validation": summary,
        }

    @classmethod
    def _calculate_line(
        cls,
        *,
        line,
        period,
        brackets,
        allowance_cache,
        deduction_cache,
        tier_cache,
        policy_cache,
        inputs,
        policy,
        attendance_policy,
        bpjs_context=None,
        user=None,
    ) -> None:
        from apps.payroll.models import (
            AllowanceTemplateLine,
            DeductionTemplateLine,
        )

        # Absensi dan cuti dibaca **hanya** pada rentang orangnya
        # benar-benar bekerja. Pegawai yang masuk tanggal 16 tidak alpa
        # tanggal 1-15, ia belum bekerja di sini; memotongnya adalah
        # memotong gaji yang memang tidak pernah jadi haknya, di atas
        # gaji pokok yang sudah diprorata.
        #
        # Rentangnya dihitung dari `Employment` apa adanya dan **tidak**
        # bergantung pada saklar prorata: mematikan prorata berarti
        # "bayar sebulan penuh", bukan "anggap ia sudah bekerja sejak
        # tanggal 1".
        eligible_start, eligible_end = cls._employment_range(
            line=line, period=period,
        )

        facts = PayrollSourceService.collect(
            employee=line.employee,
            start_date=eligible_start,
            end_date=eligible_end,
            # Snapshot barisnya, bukan assignment hari ini — alasan
            # yang sama dengan `_resolve_policy`.
            payroll_policy_id=line.payroll_policy_id,
        )

        divisor_days = Decimal(period.divisor_days)

        # Kebijakan pegawai ini: kebijakan kelompoknya di atas default
        # perusahaan. Dibaca dari snapshot yang sudah menempel di baris
        # — bukan dari assignment hari ini — supaya run lama yang
        # dihitung ulang memakai kebijakan yang berlaku waktu itu.
        resolved = cls._resolve_policy(
            line=line,
            company_proration=policy,
            company_attendance=attendance_policy,
            cache=policy_cache,
        )

        daily_rate = ZERO
        daily_rate_note = ""
        payable_days = ZERO

        if resolved.is_daily:
            # Dasar harian tidak mengenal prorata maupun pembagi
            # potongan, dan itu bukan penyederhanaan: keduanya menjawab
            # "berapa bagian dari sebulan", pertanyaan yang tidak ada
            # pada upah yang dibentuk dari hari.
            proration = ONE
            proration_base_days = ZERO
            proration_method = ""
            deduction_base_days = ZERO
            deduction_method = ""

            worked_days = (
                Decimal((eligible_end - eligible_start).days + 1)
                if eligible_end >= eligible_start
                else ZERO
            )

            payable_days = cls._payable_days(facts=facts, resolved=resolved)

            daily_rate, daily_rate_note = PayrollPolicyService.daily_rate(
                resolved=resolved,
                basic_salary=line.basic_salary,
                assignment_rate=getattr(
                    line.payroll_assignment, "daily_rate", None,
                ),
            )
        else:
            (
                proration,
                worked_days,
                proration_base_days,
                proration_method,
            ) = cls._proration(
                line=line,
                period=period,
                policy=resolved.proration,
            )

            deduction_base_days, deduction_method = cls._deduction_basis(
                line=line,
                period=period,
                policy=resolved.attendance,
            )

        allowance_lines: list = []

        if line.allowance_template_id:
            if line.allowance_template_id not in allowance_cache:
                allowance_cache[line.allowance_template_id] = list(
                    AllowanceTemplateLine.objects
                    .filter(
                        template_id=line.allowance_template_id,
                        is_deleted=False,
                        is_active=True,
                    )
                    .order_by("sequence", "code")
                )

            allowance_lines = allowance_cache[line.allowance_template_id]

        deduction_lines: list = []

        if line.deduction_template_id:
            if line.deduction_template_id not in deduction_cache:
                deduction_cache[line.deduction_template_id] = list(
                    DeductionTemplateLine.objects
                    .filter(
                        template_id=line.deduction_template_id,
                        is_deleted=False,
                        is_active=True,
                    )
                    .order_by("sequence", "code")
                )

            deduction_lines = deduction_cache[line.deduction_template_id]

        assignment = line.payroll_assignment

        overtime_group = line.overtime_group

        # Tingkat dibaca sekali per kelompok, bukan per pegawai: run
        # berisi 500 orang dengan kelompok yang sama kalau tidak akan
        # membaca master yang sama 500 kali. Yang masuk ke mesin hitung
        # tetap daftar objek biasa — mesinnya tidak pernah menyentuh
        # ORM.
        overtime_tiers: list = []

        if overtime_group is not None:
            if overtime_group.pk not in tier_cache:
                tier_cache[overtime_group.pk] = list(
                    overtime_group.active_tiers,
                )

            overtime_tiers = tier_cache[overtime_group.pk]

        data = CalculationInput(
            basic_salary=Decimal(line.basic_salary or 0),
            period_days=line.period_days,
            divisor_days=divisor_days,
            proration_factor=proration,
            proration_method=proration_method,
            proration_method_label=(
                PayrollProrationMethod(proration_method).label
                if proration_method
                else ""
            ),
            proration_base_days=proration_base_days,
            deduction_base_days=deduction_base_days,
            deduction_method=deduction_method,
            deduction_method_label=(
                resolved.attendance.method_label
                if not resolved.is_daily
                else ""
            ),
            deduct_absence=resolved.attendance.deduct_absence,
            deduct_unpaid_leave=resolved.attendance.deduct_unpaid_leave,
            pay_basis=resolved.pay_basis,
            daily_rate=daily_rate,
            daily_rate_note=daily_rate_note,
            payable_days=payable_days,
            working_days=worked_days,
            paid_days=(
                payable_days
                if resolved.is_daily
                else max(
                    worked_days - facts.unpaid_leave_days - facts.absent_days,
                    ZERO,
                )
            ),
            attendance_days=facts.attendance_days,
            absent_days=facts.absent_days,
            leave_days=facts.leave_days,
            unpaid_leave_days=facts.unpaid_leave_days,
            overtime_hours=facts.overtime_hours,
            allowance_lines=allowance_lines,
            deduction_lines=deduction_lines,
            bpjs_lines_provider=cls._bpjs_provider(
                context=bpjs_context,
                line=line,
                is_daily=resolved.is_daily,
                daily_rate=daily_rate,
                paid_days=payable_days,
            ),
            inputs=inputs,
            # Tanpa `or 1`: kelompok yang tidak ada tidak boleh
            # diam-diam jadi pengali satu. Ketiadaannya disampaikan
            # lewat `overtime_group_present`, dan mesin hitung
            # menyebutnya dengan nama sendiri.
            overtime_multiplier=Decimal(
                getattr(overtime_group, "hourly_multiplier", 0) or 0,
            ),
            overtime_divisor=Decimal(
                getattr(overtime_group, "hourly_divisor", 0) or 0,
            ),
            overtime_group_present=overtime_group is not None,
            overtime_tiers=overtime_tiers,
            overtime_tier_basis=getattr(overtime_group, "tier_basis", "") or "",
            overtime_daily_hours=facts.overtime_daily_hours,
            overtime_eligible=bool(
                getattr(assignment, "overtime_eligible", False),
            ),
            non_taxable_income=Decimal(
                getattr(line.tax_status, "non_taxable_income", 0) or 0,
            ),
            tax_brackets=brackets,
        )

        result = PayrollCalculationService.calculate(data)

        findings = list(result.findings)

        if facts.overtime_hours and not facts.has_attendance_source:
            findings.append(
                {
                    "level": PayrollFindingLevel.WARNING,
                    "code": "attendance_missing",
                    "message": (
                        "Belum ada satu pun baris absensi untuk periode "
                        "ini."
                    ),
                },
            )
        elif not facts.has_attendance_source:
            findings.append(
                {
                    "level": PayrollFindingLevel.WARNING,
                    "code": "attendance_missing",
                    "message": (
                        "Belum ada satu pun baris absensi untuk periode "
                        "ini. Potongan ketidakhadiran dihitung nol."
                    ),
                },
            )

        if getattr(facts, "manual_business_trip_days", 0):
            findings.append(
                {
                    "level": PayrollFindingLevel.WARNING,
                    "code": "business_trip_without_document",
                    "message": (
                        f"{facts.manual_business_trip_days} hari berstatus "
                        "Business Trip tanpa dokumen Business Trip yang "
                        "disetujui. Dihitung sebagai hari dinas sesuai "
                        "status barisnya."
                    ),
                },
            )

        # Rincian ditulis ulang, bukan ditambal. Menghitung ulang dengan
        # baris lama masih di tempatnya adalah cara paling cepat
        # menggandakan satu komponen.
        PayrollRunComponent.objects.filter(run_employee=line).delete()

        components = [
            PayrollRunComponent(
                run_employee=line,
                sequence=item.sequence,
                component_type=item.component_type,
                source=item.source,
                code=item.code,
                name=item.name,
                basis=item.basis,
                base_amount=item.base_amount,
                rate=item.rate,
                quantity=item.quantity,
                amount=item.amount,
                is_taxable=item.is_taxable,
                reduces_taxable=item.reduces_taxable,
                is_prorated=item.is_prorated,
                reference_type=item.reference_type,
                reference_id=item.reference_id,
                calculation_note=item.calculation_note[:255],
                created_by=user,
                updated_by=user,
            )
            for item in result.components
        ]

        PayrollRunComponent.objects.bulk_create(components)

        line.working_days = worked_days
        line.proration_method = proration_method
        line.proration_base_days = proration_base_days
        line.paid_days = data.paid_days
        line.attendance_days = facts.attendance_days
        line.business_trip_days = facts.business_trip_days
        line.absent_days = facts.absent_days
        line.leave_days = facts.leave_days
        line.unpaid_leave_days = facts.unpaid_leave_days
        line.overtime_hours = facts.overtime_hours
        line.proration_factor = proration

        line.pay_basis = resolved.pay_basis
        line.daily_rate = daily_rate

        line.attendance_deduction_method = deduction_method
        line.deduction_base_days = deduction_base_days
        line.absence_deduction = result.absence_deduction
        line.unpaid_leave_deduction = result.unpaid_leave_deduction

        line.gross_earning = result.gross_earning
        line.taxable_earning = result.taxable_earning
        line.total_deduction = result.total_deduction
        line.tax_amount = result.tax_amount
        line.net_pay = result.net_pay
        line.employer_contribution = result.employer_contribution

        line.findings = findings
        line.status = PayrollRunEmployeeStatus.CALCULATED
        line.updated_by = user

        line.save()

    @staticmethod
    def _bpjs_provider(
        *,
        context,
        line,
        is_daily=False,
        daily_rate=ZERO,
        paid_days=ZERO,
    ):
        """
        Penitip baris BPJS untuk satu pegawai.

        Mengembalikan **callable**, bukan daftar: dasarnya baru bisa
        disusun sesudah penghasilan selesai dihitung, dan yang tahu
        kapan itu terjadi mesin hitungnya. Yang dioper ke mesin karena
        itu cara memperolehnya, bukan hasilnya.

        `None` kalau tenant belum memakai BPJS sama sekali — mesin
        hitung melewatinya tanpa satu langkah tambahan pun, jadi run
        yang tidak memakai BPJS berjalan persis seperti sebelumnya.
        """
        if context is None or context.is_empty:
            return None

        # Upah sehari dan hari dibayar sudah diresolusi kebijakan
        # payroll di atas; dioper apa adanya supaya dasar iuran harian
        # tidak pernah menghitungnya dengan cara kedua.
        facts = BpjsEmployeeFacts(
            is_daily=bool(is_daily),
            daily_rate=Decimal(daily_rate or 0),
            paid_days=Decimal(paid_days or 0),
        )

        def provider(*, earnings, add_finding):
            return BpjsResolver.resolve_lines(
                context=context,
                employee_id=line.employee_id,
                company_id=line.company_id,
                earnings=earnings,
                add_finding=add_finding,
                facts=facts,
            )

        return provider

    @classmethod
    def _resolve_policy(cls, *, line, company_proration, company_attendance, cache):
        """
        Kebijakan yang berlaku untuk satu baris.

        Urutannya tetap dan hanya ada satu: kebijakan yang dibawa
        assignment → default perusahaan → perilaku teknis lama beserta
        temuannya. Kebijakan dibaca dari `line.payroll_policy`, kolom
        snapshot yang diisi `_apply_employee_snapshot` dari assignment
        yang berlaku pada cutoff periode — **bukan** dari assignment
        pegawai hari ini.

        Bedanya bukan teoretis: run Juni yang dihitung ulang di bulan
        Agustus harus memakai kebijakan yang berlaku bulan Juni, dan
        satu-satunya yang mengetahuinya adalah assignment yang berlaku
        waktu itu.
        """
        key = line.payroll_policy_id

        if key not in cache:
            cache[key] = PayrollPolicyService.resolve(
                policy=line.payroll_policy,
                company_proration=company_proration,
                company_attendance=company_attendance,
            )

        return cache[key]

    @staticmethod
    def _payable_days(*, facts, resolved):
        """
        Hari yang membentuk upah pegawai harian.

        Sumbernya **absensi**, satu-satunya dokumen yang menyatakan
        orang ini benar-benar bekerja hari itu. Bukan kalender kerja:
        hari kerja menurut kalender yang tidak ditempuh tidak
        menghasilkan upah harian, dan itu justru bedanya dengan pegawai
        bulanan.

        Hari alpa dan hari cuti tidak dibayar tidak ikut, dan tidak
        perlu dikurangkan: keduanya memang bukan hari hadir. Itu yang
        membuat tidak ada potongan kedua di mana pun — bukan sebuah
        pengurangan yang kebetulan menghasilkan nol.

        Cuti **dibayar** ikut atau tidak ditentukan kebijakan
        (`pay_paid_leave`), yang sengaja tidak punya bawaan. Tanggalnya
        tidak mungkin dihitung dua kali: adapter sudah mengeluarkan
        tanggal bercuti dari hari hadir.
        """
        # BT-3: hari dinas yang dibayar ikut membentuk upah harian.
        # Tidak mungkin dihitung dua kali — adapter menaruh satu tanggal
        # di satu wadah saja (tap fisik = hadir, tanpa tap = dinas).
        days = Decimal(facts.attendance_days or 0) + Decimal(
            getattr(facts, "business_trip_days", 0) or 0,
        )

        if resolved.pay_paid_leave:
            days += max(facts.paid_leave_days, ZERO)

        return days

    @classmethod
    def _proration(cls, *, line, period, policy):
        """
        Prorata gaji pokok untuk pegawai yang masuk atau berhenti di
        tengah periode. Mengembalikan
        `(faktor, hari_berhak, pembagi, metode)`.

        Dihitung dari **hari yang benar-benar dalam masa kerja**, bukan
        dari kehadiran: pegawai yang masuk tanggal 16 dibayar setengah
        bulan walaupun ia hadir setiap hari kerja sejak itu. Potongan
        ketidakhadiran adalah lapisan yang berbeda, berdiri sendiri, dan
        **tidak** memakai kebijakan ini (Business Decision #2).

        Tanggal masuk dan tanggal berhenti dua-duanya **inclusive** —
        mengikuti `PayrollSourceService.eligible_employees`, yang sudah
        membayar pegawai berhenti tanggal 20 untuk tanggal 1–20.
        Semantik `Employment` tidak diubah demi payroll.
        """
        method = policy.method

        start = period.start_date
        end = period.end_date

        if policy.prorate_on_join and line.join_date and line.join_date > start:
            start = line.join_date

        if (
            policy.prorate_on_termination
            and line.termination_date
            and line.termination_date < end
        ):
            end = line.termination_date

        full_period = start == period.start_date and end == period.end_date

        if end < start:
            return ZERO, ZERO, ZERO, method

        if method == PayrollProrationMethod.WORKING_DAYS:
            eligible, divisor = cls._working_day_basis(
                line=line,
                period=period,
                start=start,
                end=end,
            )
        else:
            eligible = Decimal((end - start).days + 1)

            divisor = (
                Decimal(30)
                if method == PayrollProrationMethod.FIXED_30
                else Decimal(
                    (period.end_date - period.start_date).days + 1,
                )
            )

        # Sebulan penuh dibayar sebulan penuh, **tanpa** dibagi lalu
        # dikali lagi. Pembagian yang hasilnya tidak bulat (10.000.000 /
        # 31 × 31) menyisakan selisih rupiah yang tidak bisa dijelaskan
        # kepada siapa pun, dan pada FIXED_30 bulan 31 hari faktornya
        # bahkan lebih dari satu.
        if full_period:
            return ONE, eligible, divisor, method

        if divisor <= ZERO:
            return ONE, eligible, divisor, method

        factor = (eligible / divisor).quantize(Decimal("0.000001"))

        return (factor if factor < ONE else ONE), eligible, divisor, method

    @classmethod
    def _employment_range(cls, *, line, period):
        """
        Rentang tanggal pegawai ini benar-benar bekerja di dalam
        periode. Mengembalikan `(mulai, selesai)`.

        Dipakai membaca absensi dan cuti — **bukan** menghitung prorata.
        Prorata punya rentangnya sendiri karena ia menghormati saklar
        `prorate_on_join` / `prorate_on_termination`; yang ini tidak.
        Perusahaan yang memilih membayar penuh pegawai barunya tetap
        tidak boleh memotongnya karena alpa di tanggal sebelum ia
        masuk: dua tanggal itu bukan hari kerja yang dilewatkan, itu
        tanggal ia belum ada di sini.

        Ujung kanannya `effective_cutoff`, sama seperti sebelumnya:
        data transaksi memang diambil sampai tanggal itu.

        Semantik `join_date` dan `termination_date` diambil apa adanya
        dari `Employment` — dua-duanya **inclusive**, mengikuti
        `eligible_employees` yang sudah membayar pegawai berhenti
        tanggal 20 untuk tanggal 1-20.
        """
        start = period.start_date
        end = period.effective_cutoff

        if line.join_date and line.join_date > start:
            start = line.join_date

        if line.termination_date and line.termination_date < end:
            end = line.termination_date

        return start, end

    @classmethod
    def _deduction_basis(cls, *, line, period, policy):
        """
        Pembagi hari untuk potongan alpa dan cuti tidak dibayar.
        Mengembalikan `(pembagi, metode)`.

        **Pembaginya periode penuh, bukan rentang kerja pegawai**, dan
        itu yang mencegah prorata dihitung dua kali. Pegawai yang masuk
        tanggal 16 dengan gaji 9 juta sudah berhak 4,5 juta; satu hari
        tidak masuk memotong 9.000.000/30 = 300.000 dari hak itu — bukan
        4.500.000/15, yang akan memotong dua kali lipat karena
        prorata-nya sudah diperhitungkan sekali di gaji pokoknya.

        Metode kosong = perusahaan belum memilih. Pembaginya lalu
        `PayrollPeriod.divisor_days`, persis perilaku engine sebelum
        kebijakan ini ada — menambah layar konfigurasi tidak boleh
        menggeser satu rupiah pun pada payroll yang sudah berjalan.
        Yang membedakannya dari "sudah memilih" adalah temuan WARNING
        di validasi, bukan angkanya.
        """
        method = policy.method

        if not method:
            return Decimal(period.divisor_days), ""

        if method == PayrollProrationMethod.FIXED_30:
            return Decimal(30), method

        if method == PayrollProrationMethod.CALENDAR_DAYS:
            return (
                Decimal((period.end_date - period.start_date).days + 1),
                method,
            )

        # WORKING_DAYS — sumber yang sama dengan Business Decision #1,
        # kalender kerja pegawai itu sendiri. Tidak ada Senin-Jumat yang
        # ditanam di Payroll.
        return (
            Decimal(
                PayrollSourceService.working_days(
                    employee=line.employee,
                    start_date=period.start_date,
                    end_date=period.end_date,
                ),
            ),
            method,
        )

    @classmethod
    def _working_day_basis(cls, *, line, period, start, end):
        """
        Pembilang dan pembagi metode WORKING_DAYS.

        Keduanya dari sumber yang sama — kalender kerja pegawai itu
        sendiri — supaya sebulan penuh selalu menghasilkan tepat satu.
        Memakai hari kerja pegawai sebagai pembilang tapi angka lain
        sebagai pembagi adalah cara membuat orang yang bekerja penuh
        dibayar 0,95 bulan.
        """
        eligible = Decimal(
            PayrollSourceService.working_days(
                employee=line.employee,
                start_date=start,
                end_date=end,
            ),
        )

        divisor = Decimal(
            PayrollSourceService.working_days(
                employee=line.employee,
                start_date=period.start_date,
                end_date=period.end_date,
            ),
        )

        return eligible, divisor

    @classmethod
    def _inputs_by_employee(cls, *, period) -> dict[int, list]:
        """
        Input periode ini, dikelompokkan per pegawai.

        Hanya yang berstatus CONFIRMED. Draft sengaja tidak ikut: nilai
        yang masih dikoreksi tidak boleh sudah masuk slip, dan yang
        dibatalkan tidak boleh masuk sama sekali.
        """
        rows = (
            PayrollInput.objects
            .filter(
                period=period,
                is_deleted=False,
                status=PayrollInputStatus.CONFIRMED,
            )
            .select_related("allowance_line", "deduction_line")
            .order_by("employee_id", "id")
        )

        grouped: dict[int, list] = {}

        for row in rows:
            grouped.setdefault(row.employee_id, []).append(row)

        return grouped

    @classmethod
    def _refresh_totals(cls, *, run: PayrollRun) -> None:
        totals = (
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False, is_excluded=False)
            .aggregate(
                earning=Sum("gross_earning"),
                deduction=Sum("total_deduction"),
                tax=Sum("tax_amount"),
                net=Sum("net_pay"),
                employer=Sum("employer_contribution"),
            )
        )

        run.total_earning = totals["earning"] or ZERO
        run.total_deduction = totals["deduction"] or ZERO
        run.total_tax = totals["tax"] or ZERO
        run.total_net = totals["net"] or ZERO
        run.total_employer_contribution = totals["employer"] or ZERO
        run.employee_count = (
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False, is_excluded=False)
            .count()
        )

        run.save(
            update_fields=[
                "total_earning",
                "total_deduction",
                "total_tax",
                "total_net",
                "total_employer_contribution",
                "employee_count",
                "updated_at",
            ],
        )

    # ------------------------------------------------------------------
    # Validasi & acknowledgement
    # ------------------------------------------------------------------

    @classmethod
    def validate(cls, *, run: PayrollRun, user=None) -> dict:
        summary = PayrollValidationService.validate(run=run)

        run.validation_summary = summary
        run.save(update_fields=["validation_summary", "updated_at"])

        return summary

    @classmethod
    @transaction.atomic
    def acknowledge(cls, *, run: PayrollRun, user=None) -> PayrollRun:
        summary = run.validation_summary or {}

        # Yang ditolak bukan "tidak ada peringatan", melainkan "belum
        # pernah diperiksa". Run bersih yang di-acknowledge tetap sah —
        # tombolnya memang ada di layar Review dan menolaknya cuma
        # memindahkan kebingungan ke pengguna yang datanya kebetulan
        # rapi. Yang tidak boleh adalah mengakui temuan yang belum
        # pernah dihitung.
        if not summary:
            raise ValidationError(
                {
                    "warnings": (
                        "Run ini belum pernah divalidasi. Jalankan "
                        "Calculate dulu."
                    ),
                },
            )

        run.warnings_acknowledged = True
        run.acknowledged_at = timezone.now()
        run.acknowledged_by = user
        run.updated_by = user
        run.save(
            update_fields=[
                "warnings_acknowledged",
                "acknowledged_at",
                "acknowledged_by",
                "updated_by",
                "updated_at",
            ],
        )

        return run

    @classmethod
    def assert_ready(cls, run: PayrollRun) -> dict:
        """
        Pintu bersama Submit dan Finalize.

        Dipanggil **dua-duanya**: temuan bisa lahir di antara pengajuan
        dan penerbitan (input baru masuk, pegawai dipindah), dan
        memeriksanya hanya di depan berarti run bisa terkunci dengan
        error yang belum pernah dilihat siapa pun.
        """
        summary = cls.validate(run=run)

        if summary["errors"]:
            raise ValidationError(
                {
                    "validation": [
                        item["message"] for item in summary["errors"][:20]
                    ],
                },
            )

        if summary["warnings"] and not run.warnings_acknowledged:
            raise ValidationError(
                {
                    "validation": [
                        (
                            f"Ada {len(summary['warnings'])} peringatan "
                            "yang belum diakui. Buka Review, periksa, "
                            "lalu tekan Acknowledge Warnings."
                        ),
                    ],
                },
            )

        return summary

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, run: PayrollRun, user=None, notes: str = ""):
        from apps.workflow.models import InstanceStatus
        from apps.workflow.services.workflow_service import WorkflowService

        if run.status not in (
            PayrollRunStatus.REVIEW,
            PayrollRunStatus.REJECTED,
        ):
            raise ValidationError(
                {
                    "status": (
                        "Hanya run yang sudah dihitung (Review) atau "
                        "ditolak yang bisa diajukan."
                    ),
                },
            )

        cls.assert_ready(run)

        scope = {
            "company": run.company,
            "branch": run.branch,
            "location": run.location,
        }

        cls.assert_definition_supported(scope=scope)

        workflow = WorkflowService.submit(
            document=run,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            # Sengaja tanpa `employee=`: satu run mewakili ratusan
            # pegawai, jadi tidak ada satu pegawai subjek. Karena itu
            # alurnya wajib bertipe Role/User — diperiksa
            # `assert_definition_supported` di atas.
            employee=None,
            user=user,
            scope=scope,
            document_number=run.document_number,
            document_label=cls.workflow_label(run),
            notes=notes,
            context={
                "period_id": run.period_id,
                "period_code": run.period.code,
                "employee_count": run.employee_count,
                "total_net": str(run.total_net),
                "run_type": run.run_type,
            },
            on_complete=lambda instance, status: cls.on_workflow_done(
                run=run,
                status=status,
                user=user,
            ),
        )

        if workflow.status == InstanceStatus.PENDING:
            run.status = PayrollRunStatus.SUBMITTED
            run.submitted_at = timezone.now()
            run.submitted_by = user
            run.updated_by = user
            run.save(
                update_fields=[
                    "status",
                    "submitted_at",
                    "submitted_by",
                    "updated_by",
                    "updated_at",
                ],
            )

            PayrollPeriodService.sync_status(period=run.period, user=user)

        return workflow

    @classmethod
    def assert_definition_supported(cls, *, scope) -> None:
        """
        Alur payroll run **wajib** hanya memakai meja Role atau User.

        Meja per-pegawai (atasan langsung, kepala departemen) tidak
        punya arti pada dokumen yang mewakili ratusan orang: "atasan
        langsung dari 300 orang" bukan satu orang. Aturan yang sama
        dipegang Roster Setup, dengan alasan yang sama.
        """
        from apps.workflow.models.step import ApproverType
        from apps.workflow.services import WorkflowDefinitionResolver

        definition = WorkflowDefinitionResolver.match(
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            **scope,
        )

        if definition is None:
            raise ValidationError(
                {
                    "workflow": (
                        "Belum ada alur aktif untuk payroll/payroll_run "
                        "yang cocok dengan cakupan run ini. Seed lewat "
                        "seed_payroll_workflow, atau buat sendiri di "
                        "Workflow Definitions."
                    ),
                },
            )

        unsupported = [
            step
            for step in definition.steps.filter(
                is_deleted=False, is_active=True,
            )
            if step.approver_type
            not in (ApproverType.ROLE, ApproverType.USER)
        ]

        if unsupported:
            names = ", ".join(
                f"#{step.sequence} {step.name}" for step in unsupported
            )

            raise ValidationError(
                {
                    "workflow": (
                        f"Alur {definition.code} memuat meja "
                        f"per-pegawai ({names}). Payroll run mewakili "
                        "banyak pegawai sekaligus, jadi seluruh mejanya "
                        "harus bertipe Role Holder atau Specific User."
                    ),
                },
            )

    @staticmethod
    def workflow_label(run: PayrollRun) -> str:
        period = run.period

        return (
            f"Payroll {period.name} — {run.employee_count} pegawai, "
            f"net {run.total_net}"
        )

    @classmethod
    @transaction.atomic
    def on_workflow_done(cls, *, run: PayrollRun, status, user=None):
        """
        Dipanggil engine saat alurnya selesai.

        **Tidak** ikut mem-finalize. Persetujuan dan penguncian adalah
        dua keputusan yang berbeda: yang pertama menyatakan angkanya
        benar, yang kedua menerbitkan slip dan mengunci periode. Finance
        yang menekan Finalize, setelah pembayarannya dijadwalkan.
        """
        from apps.workflow.models import InstanceStatus

        mapping = {
            InstanceStatus.APPROVED: PayrollRunStatus.APPROVED,
            InstanceStatus.REJECTED: PayrollRunStatus.REJECTED,
            InstanceStatus.CANCELLED: PayrollRunStatus.REVIEW,
            InstanceStatus.RETURNED: PayrollRunStatus.REVIEW,
        }

        target = mapping.get(status)

        if target is None or run.status == target:
            return run

        run.status = target

        fields = ["status", "updated_at"]

        if target == PayrollRunStatus.APPROVED:
            run.approved_at = timezone.now()
            run.approved_by = user
            fields += ["approved_at", "approved_by"]

        run.save(update_fields=fields)

        PayrollPeriodService.sync_status(period=run.period, user=user)

        return run

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, run: PayrollRun, user=None) -> PayrollRun:
        from apps.workflow.models import InstanceStatus
        from apps.workflow.services.workflow_service import WorkflowService

        if run.status != PayrollRunStatus.SUBMITTED:
            raise ValidationError(
                {
                    "status": (
                        "Hanya run yang sedang menunggu persetujuan "
                        "yang bisa ditarik kembali."
                    ),
                },
            )

        instance = WorkflowService.instance_for(
            document=run,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
        )

        if instance is not None:
            WorkflowService.cancel(
                instance=instance,
                user=user,
                comment="Ditarik kembali oleh pengaju.",
            )

        run.status = PayrollRunStatus.REVIEW
        run.submitted_at = None
        run.submitted_by = None
        run.updated_by = user
        run.save(
            update_fields=[
                "status",
                "submitted_at",
                "submitted_by",
                "updated_by",
                "updated_at",
            ],
        )

        PayrollPeriodService.sync_status(period=run.period, user=user)

        return run

    # ------------------------------------------------------------------
    # Finalize & Payslip
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def finalize(cls, *, run: PayrollRun, user=None) -> dict:
        """
        Mengunci run dan menerbitkan slip.

        Setelah ini angka payroll tidak bergantung pada master lagi:
        seluruh konfigurasi yang dipakai sudah dibekukan di
        `PayrollRunEmployee.snapshot`, dan slipnya membawa salinannya
        sendiri. Perubahan Salary Master bulan depan tidak menyentuh
        satu angka pun di sini.

        Urutannya mengikat, dan tiap langkah menjaga langkah berikutnya:

        1. **Barisnya dikunci lebih dulu** (`select_for_update`), lalu
           statusnya dibaca ulang dari database. Dua permintaan yang
           datang bersamaan — klik ganda, retry jaringan — kalau tidak
           akan sama-sama melihat APPROVED pada objek yang sudah di
           tangan, dan keduanya menerbitkan slip.
        2. **Wewenang.** Mengunci payroll adalah tindakan yang
           berdampak keuangan, dan aksi `finalize/` tidak dijaga
           `ModelPermission` (yang di sana hanya aksi CRUD baku).
        3. **Validasi payroll** tetap yang pertama berbicara: temuan
           seperti assignment yang hilang harus muncul sebelum kalimat
           apa pun tentang akuntansi.
        4. **Gerbang akuntansi** (PF-0D). Kalau fakta payroll tidak bisa
           dinormalisasi jadi fakta akuntansi yang sah, run **tidak**
           dikunci sama sekali — seluruhnya di dalam satu transaksi, jadi
           tidak ada slip yang terbit dan tidak ada status yang bergeser.
           Gerbangnya tidak membuat jurnal apa pun.
        5. **Jembatan akuntansi** (PF-0F). Payload yang disahkan gerbang
           diserahkan **apa adanya** ke Finance sebagai `PAYROLL_POSTED`,
           dan jurnalnya harus terbit — untuk kebijakan gaji bawaan,
           sebagai DRAFT. Gagal di sini membatalkan seluruh Finalize,
           termasuk slip yang sudah disusun di langkah sebelumnya.
        """
        from apps.payroll.services.accounting_bridge import (
            PayrollAccountingBridge,
        )
        from apps.payroll.services.accounting_gate import PayrollAccountingGate
        from apps.payroll.services.payslip import PayslipService

        run = (
            PayrollRun.objects
            .select_for_update()
            .select_related("period", "company")
            .get(pk=run.pk)
        )

        if run.status != PayrollRunStatus.APPROVED:
            raise ValidationError(
                {
                    "status": (
                        "Hanya run yang sudah disetujui yang bisa "
                        "difinalisasi."
                    ),
                },
            )

        cls.assert_may_finalize(run=run, user=user)

        # PF-0G. Mengunci run koreksi = mencabut keberlakuan proyeksi
        # lama. Itu wewenang koreksi, bukan wewenang finalisasi biasa —
        # ditagih lagi di sini supaya jalur mana pun (API, shell, perintah
        # manajemen) melewatinya, bukan hanya jalur pembuatan run.
        if run.corrects_run_id is not None:
            cls.assert_may_correct(target=run.corrects_run, user=user)

        cls.assert_ready(run)

        cls._refresh_totals(run=run)

        # Dibaca ulang supaya kontrol total di payload menilai angka yang
        # baru saja dibekukan, bukan yang dipegang pemanggil.
        run.refresh_from_db()

        # Dipegang, bukan dibuang: payload inilah yang dikirim ke Finance
        # di akhir. Membangunnya ulang sesudah slip terbit berarti dua
        # pembacaan yang bisa berbeda untuk satu kejadian.
        gate = PayrollAccountingGate.evaluate(run=run)

        lines = list(
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False, is_excluded=False)
            .select_related("employee")
            .prefetch_related("components")
        )

        for line in lines:
            line.snapshot = PayslipService.build_snapshot(
                run=run,
                line=line,
            )
            line.status = PayrollRunEmployeeStatus.FINALIZED
            line.updated_by = user
            line.save(
                update_fields=[
                    "snapshot",
                    "status",
                    "updated_by",
                    "updated_at",
                ],
            )

        payslips = PayslipService.issue_for_run(run=run, user=user)

        run.status = PayrollRunStatus.FINALIZED
        run.finalized_at = timezone.now()
        run.finalized_by = user
        run.updated_by = user
        run.save(
            update_fields=[
                "status",
                "finalized_at",
                "finalized_by",
                "updated_by",
                "updated_at",
            ],
        )

        PayrollPeriodService.sync_status(period=run.period, user=user)

        # Langkah terakhir, masih di dalam transaksi ini. Lemparannya
        # membatalkan semua yang di atas — tidak ada run FINALIZED tanpa
        # kejadian akuntansi dan jurnal drafnya.
        # PF-0G. Untuk run koreksi, proyeksi penggantinya membawa tautan
        # ke kejadian yang digantikannya — Finance memakainya menolak
        # pembukuan pengganti selagi ayat lama masih hidup di buku besar.
        accounting = PayrollAccountingBridge.record(
            run=run,
            gate=gate,
            user=user,
            replaces_run=run.corrects_run,
        )

        if run.corrects_run_id is not None:
            # **Sesudah** penggantinya benar-benar terbit, tidak sebelum:
            # kalau langkah di atas gagal, transaksi ini batal seluruhnya
            # dan proyeksi lama tidak pernah tersentuh.
            accounting["supersession"] = cls._supersede_predecessor(
                run=run, accounting=accounting, user=user,
            )

        return {
            "employees": len(lines),
            "payslips": payslips,
            "accounting": accounting,
        }

    @classmethod
    def _supersede_predecessor(cls, *, run: PayrollRun, accounting: dict, user=None):
        """
        Mencabut keberlakuan proyeksi run yang dikoreksi — **hanya**
        kalau jurnalnya belum masuk buku besar (Case A).

        Case B (jurnal lama sudah POSTED) sengaja tidak disentuh:
        sejarah buku besar dikoreksi lewat pembalikan Finance oleh aktor
        Finance yang memegang `finance.reverse_journal`, dan yang
        memfinalisasi payroll tidak memegangnya. Sampai pembalikan itu
        terjadi, jurnal pengganti ditolak kalau dicoba diposting
        (`correction_predecessor_not_reversed`).
        """
        from apps.payroll.services.accounting_bridge import (
            PayrollAccountingBridge,
        )

        target = run.corrects_run

        state = PayrollAccountingBridge.projection_state(run=target)

        if state["posted"]:
            return {
                "mode": "reversal_required",
                "predecessor_event_id": state["event_id"],
                "predecessor_journal_id": state["journal_id"],
            }

        result = PayrollAccountingBridge.supersede(
            old_run=target,
            new_run=run,
            new_event_id=accounting["event_id"],
            user=user,
        )

        return {"mode": "superseded", **result}

    @classmethod
    @transaction.atomic
    def cancel(cls, *, run: PayrollRun, user=None, notes: str = "") -> PayrollRun:
        if run.status == PayrollRunStatus.FINALIZED:
            raise ValidationError(
                {
                    "status": (
                        "Run yang sudah difinalisasi tidak bisa "
                        "dibatalkan. Terbitkan run Correction untuk "
                        "periode yang sama."
                    ),
                },
            )

        run.status = PayrollRunStatus.CANCELLED
        run.notes = notes or run.notes
        run.updated_by = user
        run.save(
            update_fields=["status", "notes", "updated_by", "updated_at"],
        )

        PayrollPeriodService.sync_status(period=run.period, user=user)

        return run
