"""
Pembuangan dataset UAT dari sebuah tenant.

**Ini perkakas maintenance, bukan fitur aplikasi.** Ia sengaja memotong
jalur service domain: run payroll yang sudah FINALIZED tidak punya jalan
keluar lewat `PayrollRunService` (satu-satunya jalan resminya menerbitkan
run Correction), sementara yang dibutuhkan di sini justru membuang data
percobaan tanpa meninggalkan jejak koreksi palsu di buku.

Konsekuensinya dipikul sadar dan dicatat di laporan:

- Status, `finalized_at`, `finalized_by`, dan kunci periode **tidak
  pernah disentuh** supaya run tampak bisa dibatalkan. Baris FINALIZED
  dihapus apa adanya, dan laporannya menyebut itu sebagai pengecualian.
- Tidak ada run Correction yang dibuat-buat.
- Tidak ada `UPDATE` pada lifecycle field mana pun. Yang dilakukan hanya
  `DELETE`.

Keselamatannya bersandar pada tiga lapis, bukan pada daftar ID saja:

1. **Provenance diperiksa ulang saat jalan.** ID cuma penunjuk; yang
   menentukan boleh-tidaknya sebuah baris dibuang adalah ciri UAT-nya
   (nomor pegawai ber-prefix, company, departemen). ID yang isinya sudah
   berubah membatalkan seluruh operasi.
2. **Dependency ditemukan, bukan didaftar.** Relasi balik `Employee` dan
   `PayrollRun` ditelusuri lewat `_meta.related_objects`. Relasi yang
   tidak ada dalam daftar tangani-an tapi berisi baris = temuan baru
   yang belum pernah diaudit, dan itu menggagalkan operasi.
3. **Pagar mati.** Sekumpulan ID yang tidak boleh ikut terhapus dalam
   keadaan apa pun diperiksa terhadap rencana sebelum eksekusi.

Rencana dihitung dengan cara yang sama persis di mode kering maupun
eksekusi — `plan()` dipanggil ulang di dalam transaksi sebelum baris
pertama dihapus, jadi laporan kering tidak pernah menjanjikan sesuatu
yang berbeda dari yang akan dikerjakan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from django.db import transaction


# ----------------------------------------------------------------------
# Spesifikasi
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class UatCleanupSpec:
    """
    Cakupan satu pembuangan.

    Dibuat parametrik, bukan konstanta di dalam service, supaya test bisa
    membangun dataset UAT-nya sendiri dan membuktikan perilakunya tanpa
    bergantung pada isi tenant `demo`.
    """

    # Sasaran utama
    employee_ids: tuple[int, ...] = ()
    run_ids: tuple[int, ...] = ()
    period_ids: tuple[int, ...] = ()

    # Catatan kejadian yang menunjuk dokumen tanpa FK
    workflow_instance_ids: tuple[int, ...] = ()
    workflow_approval_ids: tuple[int, ...] = ()
    notification_log_ids: tuple[int, ...] = ()

    # Master/konfigurasi yang lahir khusus untuk UAT (kategori C).
    # Dibuang paling akhir, sesudah seluruh pemakainya hilang.
    leave_rule_ids: tuple[int, ...] = ()
    leave_type_ids: tuple[int, ...] = ()
    overtime_group_ids: tuple[int, ...] = ()
    allowance_template_ids: tuple[int, ...] = ()
    deduction_template_ids: tuple[int, ...] = ()
    payroll_policy_ids: tuple[int, ...] = ()
    section_ids: tuple[int, ...] = ()
    department_ids: tuple[int, ...] = ()

    # Ciri provenance yang wajib dipenuhi tiap pegawai sasaran
    employee_number_prefix: str = "UAT"
    expected_company_id: int | None = None
    expected_department_id: int | None = None

    # Pagar mati — tidak boleh ikut terhapus dalam keadaan apa pun
    protected_employee_ids: tuple[int, ...] = ()
    protected_run_ids: tuple[int, ...] = ()
    protected_period_ids: tuple[int, ...] = ()
    protected_department_ids: tuple[int, ...] = ()
    protected_section_ids: tuple[int, ...] = ()
    protected_leave_type_ids: tuple[int, ...] = ()
    protected_overtime_group_ids: tuple[int, ...] = ()
    protected_allowance_template_ids: tuple[int, ...] = ()
    protected_deduction_template_ids: tuple[int, ...] = ()
    protected_workflow_definition_ids: tuple[int, ...] = ()

    # Modul sumber yang sah untuk catatan kejadian di atas
    workflow_module: str = "payroll"
    workflow_document_type: str = "payroll_run"
    notification_module: str = "payroll"
    notification_object_type: str = "payroll-payroll_run"

    # Bel in-app (`administration.Notification`) memakai tabel yang
    # berbeda dari log pengiriman, dan sama-sama menunjuk dokumen lewat
    # `object_id` tanpa FK. Cakupannya ditentukan **object type + ID run
    # sasaran**, bukan pencocokan nama "UAT" — judul bel ditulis manusia
    # dan tidak pernah jadi bukti kepemilikan.
    inapp_notification_object_type: str = "payroll-payroll_run"


@dataclass
class CleanupReport:
    """Hasil satu perhitungan rencana, dipakai kering maupun basah."""

    planned: dict[str, int] = field(default_factory=dict)
    deleted: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    finalized_runs: list[str] = field(default_factory=list)
    executed: bool = False

    @property
    def planned_total(self) -> int:
        return sum(self.planned.values())

    @property
    def deleted_total(self) -> int:
        return sum(self.deleted.values())

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)


class UatCleanupAborted(RuntimeError):
    """Preflight menolak. Tidak ada satu baris pun yang dihapus."""

    def __init__(self, blockers: Iterable[str]):
        self.blockers = list(blockers)
        super().__init__(
            f"{len(self.blockers)} pemeriksaan preflight gagal.",
        )


# ----------------------------------------------------------------------
# Relasi yang memang ditangani
# ----------------------------------------------------------------------
#
# Kunci: (label model, nama field FK). Relasi balik di luar daftar ini
# yang ternyata berisi baris berarti ada dependency yang belum pernah
# diaudit — operasinya dibatalkan, bukan diteruskan dengan asumsi.

HANDLED_EMPLOYEE_RELATIONS = {
    ("hr.EmployeeAttendance", "employee"),
    ("hr.EmployeeLeave", "employee"),
    ("hr.EmployeeOvertime", "employee"),
    ("hr.PayrollAssignment", "employee"),
    ("hr.EmploymentAssignment", "employee"),
    ("hr.OrganizationAssignment", "employee"),
    ("payroll.PayrollRunEmployee", "employee"),
    ("payroll.Payslip", "employee"),
    ("payroll.PayrollInput", "employee"),
}

HANDLED_RUN_RELATIONS = {
    ("payroll.PayrollRunEmployee", "run"),
    ("payroll.Payslip", "run"),
}


class UatCleanupService:
    # ------------------------------------------------------------------
    # Pintu masuk
    # ------------------------------------------------------------------

    @classmethod
    def plan(cls, *, spec: UatCleanupSpec) -> CleanupReport:
        """Hitung rencana tanpa menyentuh apa pun."""

        report = CleanupReport()

        cls._preflight(spec=spec, report=report)
        cls._count(spec=spec, report=report)

        return report

    @classmethod
    def execute(
        cls,
        *,
        spec: UatCleanupSpec,
        labels: set[str] | None = None,
    ) -> CleanupReport:
        """
        Jalankan pembuangan. Semua atau tidak sama sekali.

        Preflight dihitung ulang **di dalam** transaksi: laporan kering
        yang dibuat semenit lalu tidak dianggap masih berlaku.

        `labels` mempersempit **penghapusannya**, bukan pemeriksaannya:
        preflight tetap berjalan penuh, jadi pekerjaan susulan yang
        terarah tetap dijaga invariant yang sama dengan pembuangan
        besarnya.
        """

        with transaction.atomic():
            report = cls.plan(spec=spec)

            if report.is_blocked:
                raise UatCleanupAborted(report.blockers)

            cls._delete(spec=spec, report=report, labels=labels)
            cls._assert_guards_intact(spec=spec, report=report)

            report.executed = True

        return report

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    @classmethod
    def _preflight(cls, *, spec: UatCleanupSpec, report: CleanupReport) -> None:
        cls._check_schema_drift(spec=spec, report=report)

        # Kolom yang hilang tidak menghentikan pemeriksaan di bawah:
        # semuanya menyeleksi kolom secara eksplisit, jadi tetap bisa
        # berjalan dan tetap berguna dibaca. Yang gagal karena kolom itu
        # cuma `delete()`, dan itu sudah dijaga blocker-nya. Laporan
        # kering karenanya tetap utuh — termasuk daftar run FINALIZED.
        #
        # Yang tidak bisa diramal tetap ditangkap: tenant yang
        # tertinggal jauh bisa membuat salah satu query di bawah gagal,
        # dan galat mentah itu diterjemahkan jadi blocker, bukan
        # dibiarkan meledak sebagai jejak tumpukan.
        from django.db import DatabaseError

        checks = (
            cls._check_guard_overlap,
            cls._check_employee_provenance,
            cls._check_unknown_employee_dependencies,
            cls._check_run_scope,
            cls._check_unknown_run_dependencies,
            cls._check_period_scope,
            cls._check_audit_record_provenance,
            cls._check_master_unreferenced,
            cls._check_finance_untouched,
        )

        for check in checks:
            try:
                # Savepoint sendiri per pemeriksaan: satu query yang
                # gagal tidak boleh meracuni transaksi dan menjatuhkan
                # pemeriksaan berikutnya ikut-ikutan.
                with transaction.atomic():
                    check(spec=spec, report=report)
            except DatabaseError as exc:
                report.blockers.append(
                    f"PEMERIKSAAN GAGAL: {check.__name__} tidak bisa "
                    f"dijalankan pada tenant ini ({exc}). Cakupannya "
                    f"tidak terbukti aman, jadi pembuangan dihentikan.",
                )

    @classmethod
    def _check_schema_drift(cls, *, spec, report) -> None:
        """
        Model dan tabel harus sepakat sebelum apa pun dihitung.

        Migrasi tenant di repo ini di-apply per schema, jadi sebuah
        tenant bisa tertinggal di belakang kode. Kolom yang ada di model
        tapi belum ada di tabelnya membuat `delete()` — yang menarik
        baris utuh untuk menelusuri CASCADE — gagal dengan galat
        database mentah di tengah pembuangan. Lebih baik ketahuan di
        sini, dengan kalimat yang menyebut migrasinya.
        """

        from django.db import connection

        models = {
            queryset.model for _, queryset in cls._steps(spec=spec)
        }

        with connection.cursor() as cursor:
            for model in sorted(models, key=lambda m: m._meta.label):
                table = model._meta.db_table

                introspection = connection.introspection

                try:
                    described = introspection.get_table_description(
                        cursor,
                        table,
                    )
                except Exception:
                    # Tabelnya tidak ada sama sekali bukan urusan
                    # pemeriksaan ini.
                    continue

                actual = {column.name for column in described}
                expected = {
                    field.column for field in model._meta.concrete_fields
                }
                missing = sorted(expected - actual)

                if missing:
                    report.blockers.append(
                        f"SCHEMA: tabel {table} belum punya kolom "
                        f"{missing} yang sudah ada di model "
                        f"{model._meta.label}. Tenant ini tertinggal "
                        f"migrasi — pembuangan akan gagal di tengah "
                        f"jalan kalau diteruskan.",
                    )

    @classmethod
    def _check_guard_overlap(cls, *, spec, report) -> None:
        """Pagar mati diperiksa sebelum apa pun dihitung."""

        pairs = (
            ("pegawai", spec.employee_ids, spec.protected_employee_ids),
            ("payroll run", spec.run_ids, spec.protected_run_ids),
            ("payroll period", spec.period_ids, spec.protected_period_ids),
            (
                "department",
                spec.department_ids,
                spec.protected_department_ids,
            ),
            ("section", spec.section_ids, spec.protected_section_ids),
            (
                "leave type",
                spec.leave_type_ids,
                spec.protected_leave_type_ids,
            ),
            (
                "overtime group",
                spec.overtime_group_ids,
                spec.protected_overtime_group_ids,
            ),
            (
                "allowance template",
                spec.allowance_template_ids,
                spec.protected_allowance_template_ids,
            ),
            (
                "deduction template",
                spec.deduction_template_ids,
                spec.protected_deduction_template_ids,
            ),
        )

        for label, targets, protected in pairs:
            overlap = sorted(set(targets) & set(protected))

            if overlap:
                report.blockers.append(
                    f"PAGAR: {label} {overlap} ada di daftar sasaran "
                    f"sekaligus daftar terlindungi.",
                )

    @classmethod
    def _check_employee_provenance(cls, *, spec, report) -> None:
        """
        Tiap pegawai sasaran yang masih ada wajib berciri UAT.

        Yang sudah tidak ada dilewati begitu saja — itu justru keadaan
        normal pada jalan kedua (idempoten).
        """

        from apps.hr.models import Employee

        rows = Employee._base_manager.filter(
            pk__in=spec.employee_ids,
        ).values("pk", "employee_number", "first_name")

        prefix = spec.employee_number_prefix.upper()

        for row in rows:
            number = (row["employee_number"] or "").upper()

            if not number.startswith(prefix):
                report.blockers.append(
                    f"PROVENANCE: pegawai id={row['pk']} bernomor "
                    f"'{row['employee_number']}' tidak lagi ber-prefix "
                    f"'{prefix}'. Data di ID ini sudah berganti.",
                )

        found = {row["pk"] for row in rows}
        report.notes.append(
            f"Pegawai sasaran ditemukan: {len(found)} dari "
            f"{len(spec.employee_ids)}.",
        )

        cls._check_company_and_department(
            spec=spec,
            report=report,
            employee_ids=found,
        )
        cls._check_no_stray_uat_employee(spec=spec, report=report)

    @classmethod
    def _check_company_and_department(
        cls,
        *,
        spec,
        report,
        employee_ids,
    ) -> None:
        if not employee_ids:
            return

        from apps.hr.models import OrganizationAssignment

        rows = OrganizationAssignment._base_manager.filter(
            employee_id__in=employee_ids,
        ).values("employee_id", "company_id", "department_id")

        for row in rows:
            if (
                spec.expected_company_id is not None
                and row["company_id"] != spec.expected_company_id
            ):
                report.blockers.append(
                    f"PROVENANCE: pegawai id={row['employee_id']} berada "
                    f"di company {row['company_id']}, bukan "
                    f"{spec.expected_company_id}.",
                )

            if (
                spec.expected_department_id is not None
                and row["department_id"] != spec.expected_department_id
            ):
                report.blockers.append(
                    f"PROVENANCE: pegawai id={row['employee_id']} berada "
                    f"di department {row['department_id']}, bukan "
                    f"{spec.expected_department_id}.",
                )

    @classmethod
    def _check_no_stray_uat_employee(cls, *, spec, report) -> None:
        """
        Pegawai ber-prefix UAT di luar daftar sasaran.

        Kalau ada, dataset-nya sudah tumbuh sejak diaudit. Menghapus
        sebagian saja meninggalkan sisa yang tidak dicatat siapa pun,
        jadi operasinya berhenti dan minta daftarnya diperbarui.
        """

        from apps.hr.models import Employee

        stray = (
            Employee._base_manager.filter(
                employee_number__istartswith=spec.employee_number_prefix,
            )
            .exclude(pk__in=spec.employee_ids)
            .values_list("pk", "employee_number")
        )

        for pk, number in stray:
            report.blockers.append(
                f"CAKUPAN: pegawai id={pk} ('{number}') ber-prefix "
                f"'{spec.employee_number_prefix}' tapi tidak ada dalam "
                f"daftar sasaran. Dataset UAT bertambah sejak diaudit.",
            )

    @classmethod
    def _check_unknown_employee_dependencies(cls, *, spec, report) -> None:
        from apps.hr.models import Employee

        cls._walk_relations(
            model=Employee,
            target_ids=spec.employee_ids,
            handled=HANDLED_EMPLOYEE_RELATIONS,
            label="pegawai UAT",
            report=report,
        )

    @classmethod
    def _check_unknown_run_dependencies(cls, *, spec, report) -> None:
        from apps.payroll.models import PayrollRun

        cls._walk_relations(
            model=PayrollRun,
            target_ids=spec.run_ids,
            handled=HANDLED_RUN_RELATIONS,
            label="payroll run UAT",
            report=report,
        )

    @classmethod
    def _walk_relations(
        cls,
        *,
        model,
        target_ids,
        handled,
        label,
        report,
    ) -> None:
        """
        Temukan dependency, jangan mendaftarnya dari ingatan.

        Relasi balik dibaca dari metadata model sehingga kolom yang baru
        ditambahkan orang lain ikut terperiksa tanpa berkas ini perlu
        diubah.
        """

        if not target_ids:
            return

        for rel in model._meta.related_objects:
            related_model = rel.related_model
            field_name = rel.field.name
            key = (related_model._meta.label, field_name)

            count = related_model._base_manager.filter(
                **{f"{field_name}__in": target_ids},
            ).count()

            if not count:
                continue

            if key in handled:
                continue

            report.blockers.append(
                f"DEPENDENCY BARU: {related_model._meta.label}."
                f"{field_name} memuat {count} baris yang menunjuk "
                f"{label}. Relasi ini tidak ada dalam audit — cakupannya "
                f"harus diperiksa manual sebelum apa pun dihapus.",
            )

    @classmethod
    def _check_run_scope(cls, *, spec, report) -> None:
        """Run sasaran tidak boleh memuat satu pun pegawai non-UAT."""

        if not spec.run_ids:
            return

        from apps.payroll.models import PayrollRun, PayrollRunEmployee

        outsiders = (
            PayrollRunEmployee._base_manager.filter(run_id__in=spec.run_ids)
            .exclude(employee_id__in=spec.employee_ids)
            .values_list("run_id", "employee_id")
        )

        for run_id, employee_id in outsiders:
            report.blockers.append(
                f"CAKUPAN: run {run_id} memuat pegawai {employee_id} "
                f"yang bukan sasaran UAT.",
            )

        # Run FINALIZED dibuang sebagai pengecualian, dan itu dinyatakan
        # terang-terangan di laporan — bukan disembunyikan di balik
        # jumlah total.
        finalized = PayrollRun._base_manager.filter(
            pk__in=spec.run_ids,
            status="finalized",
        ).values_list("pk", "document_number", "status")

        for pk, number, status in finalized:
            report.finalized_runs.append(
                f"run id={pk} ({number or '-'}) status={status}",
            )

    @classmethod
    def _check_period_scope(cls, *, spec, report) -> None:
        """Periode sasaran tidak boleh dipakai run di luar sasaran."""

        if not spec.period_ids:
            return

        from apps.payroll.models import PayrollRun

        outsiders = (
            PayrollRun._base_manager.filter(period_id__in=spec.period_ids)
            .exclude(pk__in=spec.run_ids)
            .values_list("period_id", "pk")
        )

        for period_id, run_id in outsiders:
            report.blockers.append(
                f"CAKUPAN: period {period_id} masih dipakai run {run_id} "
                f"yang bukan sasaran UAT.",
            )

    @classmethod
    def _check_audit_record_provenance(cls, *, spec, report) -> None:
        """
        Catatan kejadian menunjuk dokumen tanpa FK, jadi penunjuknya
        diverifikasi sendiri di sini sebelum ikut dibuang.
        """

        from apps.notifications.models import NotificationLog
        from apps.workflow.models import WorkflowApproval, WorkflowInstance

        run_keys = {str(run_id) for run_id in spec.run_ids}

        instances = WorkflowInstance._base_manager.filter(
            pk__in=spec.workflow_instance_ids,
        ).values("pk", "module", "document_type", "object_id")

        for row in instances:
            if (
                row["module"] != spec.workflow_module
                or row["document_type"] != spec.workflow_document_type
                or str(row["object_id"]) not in run_keys
            ):
                report.blockers.append(
                    f"PROVENANCE: workflow instance {row['pk']} menunjuk "
                    f"{row['module']}/{row['document_type']}/"
                    f"{row['object_id']} — bukan run UAT yang dibuang.",
                )

        approvals = WorkflowApproval._base_manager.filter(
            pk__in=spec.workflow_approval_ids,
        ).values_list("pk", "instance_id")

        for pk, instance_id in approvals:
            if instance_id not in spec.workflow_instance_ids:
                report.blockers.append(
                    f"PROVENANCE: approval {pk} milik instance "
                    f"{instance_id} yang tidak ikut dibuang.",
                )

        # Approval lain pada instance yang dibuang akan jadi yatim.
        leftover = (
            WorkflowApproval._base_manager.filter(
                instance_id__in=spec.workflow_instance_ids,
            )
            .exclude(pk__in=spec.workflow_approval_ids)
            .values_list("pk", flat=True)
        )

        for pk in leftover:
            report.blockers.append(
                f"CAKUPAN: approval {pk} menempel pada instance yang "
                f"dibuang tapi tidak terdaftar untuk ikut dibuang.",
            )

        cls._check_inapp_notification_provenance(spec=spec, report=report)

        logs = NotificationLog._base_manager.filter(
            pk__in=spec.notification_log_ids,
        ).values("pk", "module", "object_type", "object_id")

        for row in logs:
            if (
                row["module"] != spec.notification_module
                or row["object_type"] != spec.notification_object_type
                or str(row["object_id"]) not in run_keys
            ):
                report.blockers.append(
                    f"PROVENANCE: notification log {row['pk']} menunjuk "
                    f"{row['module']}/{row['object_type']}/"
                    f"{row['object_id']} — bukan run UAT yang dibuang.",
                )

    @classmethod
    def _check_inapp_notification_provenance(cls, *, spec, report) -> None:
        """
        Bel in-app yang ikut dibuang harus menunjuk run sasaran.

        Barisnya milik **pengguna sungguhan** — bel ini yang mereka lihat
        di aplikasi. Yang membuatnya boleh dibuang bukan siapa
        pemiliknya, melainkan dokumen yang ditunjuknya: begitu run UAT
        hilang, bel itu menunjuk sesuatu yang tidak ada lagi. Karena itu
        pemeriksaan di sini soal `object_type` + `object_id`, tidak
        pernah soal nama atau pemilik.
        """

        from apps.administration.models import Notification

        run_keys = {str(run_id) for run_id in spec.run_ids}
        protected_keys = {
            str(run_id) for run_id in spec.protected_run_ids
        }

        selected = Notification._base_manager.filter(
            object_type=spec.inapp_notification_object_type,
            object_id__in=run_keys,
        ).values("pk", "object_type", "object_id")

        for row in selected:
            if row["object_type"] != spec.inapp_notification_object_type:
                report.blockers.append(
                    f"PROVENANCE: notifikasi in-app {row['pk']} ber-"
                    f"object_type '{row['object_type']}', bukan "
                    f"'{spec.inapp_notification_object_type}'.",
                )

            if str(row["object_id"]) not in run_keys:
                report.blockers.append(
                    f"PROVENANCE: notifikasi in-app {row['pk']} menunjuk "
                    f"run {row['object_id']} yang bukan sasaran UAT.",
                )

            if str(row["object_id"]) in protected_keys:
                report.blockers.append(
                    f"PAGAR: notifikasi in-app {row['pk']} menunjuk run "
                    f"terlindungi {row['object_id']}.",
                )

    @classmethod
    def _check_master_unreferenced(cls, *, spec, report) -> None:
        """
        Master kategori C hanya boleh dibuang kalau tidak ada lagi yang
        memakainya di luar baris yang memang ikut dibuang.
        """

        from apps.hr.models import EmployeeLeave, PayrollAssignment
        from apps.payroll.models import (
            PayrollLeaveRule,
            PayrollRunEmployee,
        )

        checks = (
            (
                "leave type",
                spec.leave_type_ids,
                EmployeeLeave._base_manager.filter(
                    leave_type_id__in=spec.leave_type_ids,
                ).exclude(employee_id__in=spec.employee_ids),
                "cuti pegawai non-UAT",
            ),
            (
                "leave type",
                spec.leave_type_ids,
                PayrollLeaveRule._base_manager.filter(
                    leave_type_id__in=spec.leave_type_ids,
                ).exclude(pk__in=spec.leave_rule_ids),
                "payroll leave rule di luar sasaran",
            ),
            (
                "overtime group",
                spec.overtime_group_ids,
                PayrollAssignment._base_manager.filter(
                    overtime_group_id__in=spec.overtime_group_ids,
                ).exclude(employee_id__in=spec.employee_ids),
                "penugasan payroll pegawai non-UAT",
            ),
            (
                "allowance template",
                spec.allowance_template_ids,
                PayrollAssignment._base_manager.filter(
                    allowance_template_id__in=spec.allowance_template_ids,
                ).exclude(employee_id__in=spec.employee_ids),
                "penugasan payroll pegawai non-UAT",
            ),
            (
                "deduction template",
                spec.deduction_template_ids,
                PayrollAssignment._base_manager.filter(
                    deduction_template_id__in=spec.deduction_template_ids,
                ).exclude(employee_id__in=spec.employee_ids),
                "penugasan payroll pegawai non-UAT",
            ),
            (
                "payroll policy",
                spec.payroll_policy_ids,
                PayrollAssignment._base_manager.filter(
                    payroll_policy_id__in=spec.payroll_policy_ids,
                ).exclude(employee_id__in=spec.employee_ids),
                "penugasan payroll pegawai non-UAT",
            ),
            (
                "payroll policy",
                spec.payroll_policy_ids,
                PayrollRunEmployee._base_manager.filter(
                    payroll_policy_id__in=spec.payroll_policy_ids,
                ).exclude(run_id__in=spec.run_ids),
                "baris run di luar sasaran",
            ),
        )

        for label, ids, queryset, who in checks:
            if not ids:
                continue

            count = queryset.count()

            if count:
                report.blockers.append(
                    f"MASTER: {label} {sorted(ids)} masih dipakai "
                    f"{count} {who}.",
                )

        cls._check_org_unit_unreferenced(spec=spec, report=report)

    @classmethod
    def _check_org_unit_unreferenced(cls, *, spec, report) -> None:
        from apps.hr.models import OrganizationAssignment
        from apps.payroll.models import (
            PayrollRun,
            PayrollRunEmployee,
            Payslip,
        )

        unit_filters = (
            ("department", spec.department_ids, "department_id"),
            ("section", spec.section_ids, "section_id"),
        )

        for label, ids, column in unit_filters:
            if not ids:
                continue

            leftovers = (
                (
                    "penempatan pegawai non-UAT",
                    OrganizationAssignment._base_manager.filter(
                        **{f"{column}__in": ids},
                    ).exclude(employee_id__in=spec.employee_ids),
                ),
                (
                    "payroll run di luar sasaran",
                    PayrollRun._base_manager.filter(
                        **{f"{column}__in": ids},
                    ).exclude(pk__in=spec.run_ids),
                ),
                (
                    "baris run di luar sasaran",
                    PayrollRunEmployee._base_manager.filter(
                        **{f"{column}__in": ids},
                    ).exclude(run_id__in=spec.run_ids),
                ),
                (
                    "payslip di luar sasaran",
                    Payslip._base_manager.filter(
                        **{f"{column}__in": ids},
                    ).exclude(run_id__in=spec.run_ids),
                ),
            )

            for who, queryset in leftovers:
                count = queryset.count()

                if count:
                    report.blockers.append(
                        f"MASTER: {label} {sorted(ids)} masih dipakai "
                        f"{count} {who}.",
                    )

    @classmethod
    def _check_finance_untouched(cls, *, spec, report) -> None:
        """
        Finance tidak boleh ikut terseret.

        Audit membuktikan tidak ada satu pun kejadian akuntansi yang
        lahir dari run UAT. Pemeriksaan ini menjaga kesimpulan itu tetap
        benar pada saat perintah dijalankan, bukan hanya saat diaudit.
        """

        if not spec.run_ids:
            return

        from apps.finance.models import AccountingEvent, Journal

        run_keys = {str(run_id) for run_id in spec.run_ids}

        events = AccountingEvent._base_manager.filter(
            source_type="payroll_run",
        ).values_list("pk", "source_id")

        for pk, source_id in events:
            if str(source_id) in run_keys:
                report.blockers.append(
                    f"FINANCE: AccountingEvent {pk} berasal dari run "
                    f"{source_id} yang hendak dibuang. Jalurnya "
                    f"pembalikan, bukan penghapusan.",
                )

        journals = Journal._base_manager.filter(
            source_type="payroll_run",
        ).values_list("pk", "source_id")

        for pk, source_id in journals:
            if str(source_id) in run_keys:
                report.blockers.append(
                    f"FINANCE: Journal {pk} berasal dari run {source_id} "
                    f"yang hendak dibuang.",
                )

    # ------------------------------------------------------------------
    # Perhitungan
    # ------------------------------------------------------------------

    @classmethod
    def _steps(cls, *, spec):
        """
        Urutan pembuangan: anak dulu, induk belakangan.

        Dipakai bersama oleh penghitung dan penghapus supaya angka di
        laporan kering tidak pernah berasal dari jalan yang berbeda.
        """

        from apps.administration.models import (
            Department,
            LeaveType,
            Notification,
            Section,
        )
        from apps.hr.models import (
            EmployeeAttendance,
            EmployeeLeave,
            EmployeeOvertime,
            EmploymentAssignment,
            Employee,
            OrganizationAssignment,
            PayrollAssignment,
        )
        from apps.notifications.models import NotificationLog
        from apps.payroll.models import (
            AllowanceTemplate,
            DeductionTemplate,
            OvertimeGroup,
            PayrollInput,
            PayrollLeaveRule,
            PayrollPeriod,
            PayrollPolicy,
            PayrollRun,
            PayrollRunComponent,
            PayrollRunEmployee,
            Payslip,
        )
        from apps.workflow.models import WorkflowApproval, WorkflowInstance

        employees = spec.employee_ids
        runs = spec.run_ids

        # `object_id` disimpan sebagai teks; dicocokkan sebagai teks.
        run_keys = [str(run_id) for run_id in runs]

        return [
            (
                "payroll.PayrollRunComponent",
                PayrollRunComponent._base_manager.filter(
                    run_employee__run_id__in=runs,
                ),
            ),
            # Payslip lebih dulu dari PayrollRunEmployee: relasinya
            # OneToOne CASCADE, jadi membuang baris run duluan akan
            # menyeret slip-nya diam-diam dan membuat angka "terhapus"
            # di laporan tidak lagi cocok dengan angka "direncanakan".
            (
                "payroll.Payslip",
                Payslip._base_manager.filter(run_id__in=runs),
            ),
            (
                "payroll.PayrollRunEmployee",
                PayrollRunEmployee._base_manager.filter(run_id__in=runs),
            ),
            (
                "payroll.PayrollInput",
                PayrollInput._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "workflow.WorkflowApproval",
                WorkflowApproval._base_manager.filter(
                    pk__in=spec.workflow_approval_ids,
                ),
            ),
            (
                "workflow.WorkflowInstance",
                WorkflowInstance._base_manager.filter(
                    pk__in=spec.workflow_instance_ids,
                ),
            ),
            (
                "notifications.NotificationLog",
                NotificationLog._base_manager.filter(
                    pk__in=spec.notification_log_ids,
                ),
            ),
            (
                "administration.Notification",
                Notification._base_manager.filter(
                    object_type=spec.inapp_notification_object_type,
                    object_id__in=run_keys,
                ),
            ),
            (
                "payroll.PayrollRun",
                PayrollRun._base_manager.filter(pk__in=runs),
            ),
            (
                "payroll.PayrollPeriod",
                PayrollPeriod._base_manager.filter(
                    pk__in=spec.period_ids,
                ),
            ),
            (
                "hr.EmployeeAttendance",
                EmployeeAttendance._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "hr.EmployeeLeave",
                EmployeeLeave._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "hr.EmployeeOvertime",
                EmployeeOvertime._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "hr.PayrollAssignment",
                PayrollAssignment._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "hr.EmploymentAssignment",
                EmploymentAssignment._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "hr.OrganizationAssignment",
                OrganizationAssignment._base_manager.filter(
                    employee_id__in=employees,
                ),
            ),
            (
                "hr.Employee",
                Employee._base_manager.filter(pk__in=employees),
            ),
            (
                "payroll.PayrollLeaveRule",
                PayrollLeaveRule._base_manager.filter(
                    pk__in=spec.leave_rule_ids,
                ),
            ),
            (
                "administration.LeaveType",
                LeaveType._base_manager.filter(
                    pk__in=spec.leave_type_ids,
                ),
            ),
            (
                "payroll.OvertimeGroup",
                OvertimeGroup._base_manager.filter(
                    pk__in=spec.overtime_group_ids,
                ),
            ),
            (
                "payroll.AllowanceTemplate",
                AllowanceTemplate._base_manager.filter(
                    pk__in=spec.allowance_template_ids,
                ),
            ),
            (
                "payroll.DeductionTemplate",
                DeductionTemplate._base_manager.filter(
                    pk__in=spec.deduction_template_ids,
                ),
            ),
            (
                "payroll.PayrollPolicy",
                PayrollPolicy._base_manager.filter(
                    pk__in=spec.payroll_policy_ids,
                ),
            ),
            (
                "administration.Section",
                Section._base_manager.filter(pk__in=spec.section_ids),
            ),
            (
                "administration.Department",
                Department._base_manager.filter(
                    pk__in=spec.department_ids,
                ),
            ),
        ]

    @classmethod
    def _count(cls, *, spec: UatCleanupSpec, report: CleanupReport) -> None:
        for label, queryset in cls._steps(spec=spec):
            report.planned[label] = queryset.count()

    # ------------------------------------------------------------------
    # Eksekusi
    # ------------------------------------------------------------------

    @classmethod
    def _delete(
        cls,
        *,
        spec: UatCleanupSpec,
        report: CleanupReport,
        labels: set[str] | None = None,
    ) -> None:
        for label, queryset in cls._steps(spec=spec):
            if labels is not None and label not in labels:
                continue

            # `delete()` pada queryset ikut menarik CASCADE-nya. Yang
            # dicatat di sini hanya jumlah baris model itu sendiri;
            # turunannya sudah punya barisnya sendiri di daftar langkah.
            pks = list(queryset.values_list("pk", flat=True))

            if not pks:
                report.deleted[label] = 0
                continue

            model = queryset.model
            _, per_model = model._base_manager.filter(pk__in=pks).delete()
            report.deleted[label] = per_model.get(model._meta.label, 0)

    @classmethod
    def _assert_guards_intact(
        cls,
        *,
        spec: UatCleanupSpec,
        report: CleanupReport,
    ) -> None:
        """
        Sesudah semuanya dihapus, pagar mati dihitung ulang.

        Kalau satu pun hilang, transaksinya dibatalkan — lebih baik tidak
        jadi bersih daripada diam-diam menghapus data yang dilindungi.
        """

        from apps.administration.models import Department, LeaveType, Section
        from apps.hr.models import Employee
        from apps.payroll.models import (
            AllowanceTemplate,
            DeductionTemplate,
            OvertimeGroup,
            PayrollPeriod,
            PayrollRun,
        )
        from apps.workflow.models import WorkflowDefinition

        guards = (
            ("pegawai", Employee, spec.protected_employee_ids),
            ("payroll run", PayrollRun, spec.protected_run_ids),
            ("payroll period", PayrollPeriod, spec.protected_period_ids),
            ("department", Department, spec.protected_department_ids),
            ("section", Section, spec.protected_section_ids),
            ("leave type", LeaveType, spec.protected_leave_type_ids),
            (
                "overtime group",
                OvertimeGroup,
                spec.protected_overtime_group_ids,
            ),
            (
                "allowance template",
                AllowanceTemplate,
                spec.protected_allowance_template_ids,
            ),
            (
                "deduction template",
                DeductionTemplate,
                spec.protected_deduction_template_ids,
            ),
            (
                "workflow definition",
                WorkflowDefinition,
                spec.protected_workflow_definition_ids,
            ),
        )

        missing: list[str] = []

        for label, model, ids in guards:
            if not ids:
                continue

            found = set(
                model._base_manager.filter(pk__in=ids).values_list(
                    "pk",
                    flat=True,
                ),
            )
            gone = sorted(set(ids) - found)

            if gone:
                missing.append(f"{label} {gone}")

        if missing:
            raise UatCleanupAborted(
                [
                    f"PAGAR JEBOL: {item} hilang sesudah pembuangan."
                    for item in missing
                ],
            )
