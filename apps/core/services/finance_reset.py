"""
Pembuangan fixture transaksi Finance dari sebuah tenant.

**Perkakas maintenance, bukan lifecycle Finance.** Jurnal yang sudah
diposting tidak pernah dihapus lewat aplikasi — itu aturan inti, dan
berkas ini tidak melonggarkannya satu milimeter pun: `JournalService`
dan `FinancePostingService` tidak disentuh, sehingga layar Finance tetap
menolak menghapus jurnal posted seperti sebelumnya.

Yang dikerjakan di sini adalah hal yang berbeda secara jenis: membuang
**fixture smoke test** yang tidak pernah mewakili transaksi apa pun.
Karena itu **tidak ada pembalikan**. Membalik berarti menyatakan "ayat
ini benar-benar terjadi lalu dikoreksi"; untuk baris yang lahir dari
skrip uji, pernyataan itu palsu dan akan tercetak di buku selamanya.

Tiga hal yang membuatnya boleh dipercaya:

1. **Provenance diuji per baris, bukan per daftar.** Sebuah jurnal hanya
   lolos kalau company-nya sasaran, aktornya termasuk akun uji yang
   dinyatakan, umurnya di dalam jendela fixture, dan sumbernya memang
   tidak menunjuk dokumen yang benar-benar ada. Satu baris gagal ⇒
   seluruh operasi batal.
2. **Pagar master dihitung ulang sesudahnya.** COA, kebijakan, periode,
   tahun buku, mata uang, penomoran — hilang satu saja, transaksinya
   di-rollback.
3. **Satu transaksi.** Pemutusan siklus PROTECT dan seluruh penghapusan
   berada di dalam `transaction.atomic()` yang sama. Tidak pernah ada
   keadaan ter-commit di mana tautan pembalikan sudah putus tapi
   jurnalnya masih berdiri.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db import transaction


# ----------------------------------------------------------------------
# Spesifikasi
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class FinanceResetSpec:
    """Cakupan satu reset. Parametrik supaya test punya panggungnya sendiri."""

    # Pagar tenant — schema yang boleh dikenai reset.
    schema_names: tuple[str, ...] = ()

    # Pagar company — hanya transaksi milik company ini yang disentuh.
    company_ids: tuple[int, ...] = ()

    # Provenance: akun yang boleh muncul sebagai aktor pada fixture.
    # NULL selalu diterima (dibuat jalur tepercaya tanpa pengguna).
    allowed_actor_ids: tuple[int, ...] = ()

    # Jendela pembuatan fixture. Jurnal di luar rentang ini bukan bagian
    # dari sesi uji yang diaudit, dan menggagalkan operasi.
    fixture_window_start: date | None = None
    fixture_window_end: date | None = None

    # Sumber yang sah untuk jurnal otomatis. Jurnal yang menunjuk
    # dokumen yang **benar-benar ada** ditolak — itu tanda ia bukan
    # fixture.
    allowed_source_types: tuple[str, ...] = ("payroll_run",)

    # Pengajuan alur yang masih hidup dan ikut dibersihkan.
    workflow_instance_ids: tuple[int, ...] = ()
    workflow_approval_ids: tuple[int, ...] = ()

    # Keadaan yang diharapkan untuk pengajuan di atas — diverifikasi
    # **berdasarkan keadaan**, bukan ID. Kunci: module, document_type,
    # object_id, status.
    expected_instance_state: tuple[dict, ...] = ()

    # Kunci: instance_id, status, approver_employee_id, approver_id.
    expected_approval_state: tuple[dict, ...] = ()

    # Pagar master: label model -> jumlah baris yang wajib bertahan.
    protected_counts: tuple[tuple[str, int], ...] = ()


@dataclass
class CycleBreak:
    """Satu tautan pembalikan yang diputus sebelum penghapusan."""

    journal_id: int
    journal_number: str
    field: str
    previous_value: int

    def __str__(self) -> str:
        return (
            f"Journal {self.journal_id} ({self.journal_number}) "
            f".{self.field}: {self.previous_value} -> NULL"
        )


@dataclass
class FinanceResetReport:
    planned: dict[str, int] = field(default_factory=dict)
    deleted: dict[str, int] = field(default_factory=dict)
    cycle_breaks: list[CycleBreak] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
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


class FinanceResetAborted(RuntimeError):
    """Preflight menolak. Tidak ada satu baris pun yang berubah."""

    def __init__(self, blockers):
        self.blockers = list(blockers)
        super().__init__(f"{len(self.blockers)} pemeriksaan gagal.")


# Relasi balik yang memang ditangani. Selebihnya yang berisi baris
# berarti dependency yang belum pernah diaudit.
HANDLED_JOURNAL_RELATIONS = {
    ("finance.AccountingEvent", "generated_journal"),
    ("finance.Journal", "reversal_of"),
    ("finance.Journal", "reversed_by"),
    ("finance.JournalLine", "journal"),
}

HANDLED_EVENT_RELATIONS = {
    ("finance.AccountingEvent", "superseded_by"),
}


class FinanceResetService:
    # ------------------------------------------------------------------
    # Pintu masuk
    # ------------------------------------------------------------------

    @classmethod
    def plan(cls, *, spec: FinanceResetSpec) -> FinanceResetReport:
        report = FinanceResetReport()

        cls._preflight(spec=spec, report=report)
        cls._count(spec=spec, report=report)
        cls._collect_cycle_breaks(spec=spec, report=report)

        return report

    @classmethod
    def execute(cls, *, spec: FinanceResetSpec) -> FinanceResetReport:
        """
        Semua atau tidak sama sekali.

        Pemutusan siklus dan penghapusan berbagi satu `atomic()`, jadi
        kegagalan di langkah mana pun mengembalikan tautan pembalikan
        persis seperti semula.
        """

        with transaction.atomic():
            report = cls.plan(spec=spec)

            if report.is_blocked:
                raise FinanceResetAborted(report.blockers)

            cls._break_cycles(spec=spec, report=report)
            cls._delete(spec=spec, report=report)
            cls._assert_protected_intact(spec=spec)
            cls._assert_ledger_empty(spec=spec)

            report.executed = True

        return report

    # ------------------------------------------------------------------
    # Cakupan
    # ------------------------------------------------------------------

    @staticmethod
    def _journal_scope(spec: FinanceResetSpec):
        from apps.finance.models import Journal

        return Journal._base_manager.filter(
            company_id__in=spec.company_ids,
        )

    @staticmethod
    def _event_scope(spec: FinanceResetSpec):
        from apps.finance.models import AccountingEvent

        return AccountingEvent._base_manager.filter(
            company_id__in=spec.company_ids,
        )

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    @classmethod
    def _preflight(cls, *, spec, report) -> None:
        cls._check_tenant_guard(spec=spec, report=report)

        if report.is_blocked:
            # Schema yang salah membuat seluruh angka di bawah tidak
            # berarti apa-apa. Berhenti sebelum menghitungnya.
            return

        from django.db import DatabaseError

        checks = (
            cls._check_company_guard,
            cls._check_journal_provenance,
            cls._check_unknown_dependencies,
            cls._check_workflow_state,
            cls._check_protected_baseline,
        )

        for check in checks:
            try:
                with transaction.atomic():
                    check(spec=spec, report=report)
            except DatabaseError as exc:
                report.blockers.append(
                    f"PEMERIKSAAN GAGAL: {check.__name__} ({exc}).",
                )

    @classmethod
    def _check_tenant_guard(cls, *, spec, report) -> None:
        from django.db import connection
        from django_tenants.utils import get_public_schema_name

        current = getattr(connection, "schema_name", None)
        public = get_public_schema_name()

        if current == public:
            report.blockers.append(
                "TENANT: reset tidak pernah dijalankan pada schema "
                f"publik ('{public}').",
            )

            return

        if spec.schema_names and current not in spec.schema_names:
            report.blockers.append(
                f"TENANT: schema '{current}' tidak ada dalam daftar "
                f"yang diizinkan {list(spec.schema_names)}.",
            )

            return

        report.notes.append(f"Tenant: {current}")

    @classmethod
    def _check_company_guard(cls, *, spec, report) -> None:
        """Transaksi milik company lain tidak boleh ikut terbaca."""

        from apps.finance.models import AccountingEvent, Journal, JournalLine

        outsiders = (
            Journal._base_manager
            .exclude(company_id__in=spec.company_ids)
            .count()
        )
        line_outsiders = (
            JournalLine._base_manager
            .exclude(company_id__in=spec.company_ids)
            .count()
        )
        event_outsiders = (
            AccountingEvent._base_manager
            .exclude(company_id__in=spec.company_ids)
            .count()
        )

        report.notes.append(
            f"Company sasaran: {list(spec.company_ids)} — di luar "
            f"sasaran tetap: {outsiders} jurnal, {line_outsiders} baris, "
            f"{event_outsiders} kejadian.",
        )

    @classmethod
    def _check_journal_provenance(cls, *, spec, report) -> None:
        """
        Tiap jurnal diuji sendiri-sendiri. Tidak ada yang lolos karena
        "yang lain juga fixture".
        """

        from apps.payroll.models import PayrollRun

        rows = cls._journal_scope(spec).values(
            "pk",
            "journal_number",
            "company_id",
            "source_type",
            "source_id",
            "created_at",
            "created_by_id",
            "submitted_by_id",
            "approved_by_id",
            "posted_by_id",
        )

        allowed = set(spec.allowed_actor_ids)

        for row in rows:
            pk = row["pk"]
            number = row["journal_number"] or "-"

            actors = {
                row["created_by_id"],
                row["submitted_by_id"],
                row["approved_by_id"],
                row["posted_by_id"],
            } - {None}

            stranger = actors - allowed

            if stranger:
                report.blockers.append(
                    f"PROVENANCE: jurnal {pk} ({number}) menyebut aktor "
                    f"{sorted(stranger)} di luar akun uji yang "
                    f"dinyatakan. Ini tanda transaksi nyata.",
                )

            created = row["created_at"].date()

            if spec.fixture_window_start and created < spec.fixture_window_start:
                report.blockers.append(
                    f"PROVENANCE: jurnal {pk} ({number}) dibuat "
                    f"{created}, sebelum jendela fixture "
                    f"{spec.fixture_window_start}.",
                )

            if spec.fixture_window_end and created > spec.fixture_window_end:
                report.blockers.append(
                    f"PROVENANCE: jurnal {pk} ({number}) dibuat "
                    f"{created}, sesudah jendela fixture "
                    f"{spec.fixture_window_end}.",
                )

            source_type = (row["source_type"] or "").strip()
            source_id = (row["source_id"] or "").strip()

            if not source_type:
                continue

            if source_type not in spec.allowed_source_types:
                report.blockers.append(
                    f"PROVENANCE: jurnal {pk} ({number}) bersumber "
                    f"'{source_type}' yang tidak dikenal perkakas ini.",
                )

                continue

            # Jurnal yang sumbernya benar-benar ada bukan fixture —
            # itu proyeksi dokumen sungguhan.
            if source_id.isdigit() and PayrollRun._base_manager.filter(
                pk=int(source_id),
            ).exists():
                report.blockers.append(
                    f"PROVENANCE: jurnal {pk} ({number}) memproyeksikan "
                    f"PayrollRun {source_id} yang MASIH ADA. Ini bukan "
                    f"fixture — jalurnya pembalikan Finance, bukan "
                    f"reset.",
                )

        report.notes.append(f"Jurnal diperiksa: {len(rows)}")

    @classmethod
    def _check_unknown_dependencies(cls, *, spec, report) -> None:
        from apps.finance.models import AccountingEvent, Journal

        cls._walk(
            model=Journal,
            ids=list(cls._journal_scope(spec).values_list("pk", flat=True)),
            handled=HANDLED_JOURNAL_RELATIONS,
            label="jurnal sasaran",
            report=report,
        )
        cls._walk(
            model=AccountingEvent,
            ids=list(cls._event_scope(spec).values_list("pk", flat=True)),
            handled=HANDLED_EVENT_RELATIONS,
            label="kejadian sasaran",
            report=report,
        )

    @staticmethod
    def _walk(*, model, ids, handled, label, report) -> None:
        """Relasi dibaca dari metadata, termasuk yang `related_name='+'`."""

        from django.db.models.deletion import (
            get_candidate_relations_to_delete,
        )

        if not ids:
            return

        for rel in get_candidate_relations_to_delete(model._meta):
            related = rel.related_model
            name = rel.field.name
            key = (related._meta.label, name)

            count = related._base_manager.filter(
                **{f"{name}__in": ids},
            ).count()

            if not count or key in handled:
                continue

            report.blockers.append(
                f"DEPENDENCY BARU: {related._meta.label}.{name} memuat "
                f"{count} baris yang menunjuk {label}. Relasi ini belum "
                f"pernah diaudit.",
            )

    @classmethod
    def _check_workflow_state(cls, *, spec, report) -> None:
        """
        Pengajuan alur diverifikasi lewat **keadaannya**, bukan ID.

        Nomornya cuma penunjuk; yang menentukan boleh-tidaknya dibuang
        adalah dokumen yang ditunjuk, statusnya yang masih terbuka, dan
        siapa yang sedang ditunggu tanda tangannya.
        """

        from apps.workflow.models import WorkflowApproval, WorkflowInstance

        journal_ids = {
            str(pk)
            for pk in cls._journal_scope(spec).values_list("pk", flat=True)
        }

        for expected in spec.expected_instance_state:
            pk = expected["id"]
            row = (
                WorkflowInstance._base_manager
                .filter(pk=pk)
                .values("pk", "module", "document_type", "object_id", "status")
                .first()
            )

            if row is None:
                # Sudah tidak ada = sudah dibereskan. Bukan kegagalan.
                continue

            for key in ("module", "document_type", "object_id", "status"):
                if str(row[key]) != str(expected[key]):
                    report.blockers.append(
                        f"WORKFLOW: instance {pk} punya {key}="
                        f"'{row[key]}', diharapkan '{expected[key]}'. "
                        f"Keadaannya berubah sejak diaudit.",
                    )

            if str(row["object_id"]) not in journal_ids:
                report.blockers.append(
                    f"WORKFLOW: instance {pk} menunjuk jurnal "
                    f"{row['object_id']} yang bukan sasaran reset.",
                )

        for expected in spec.expected_approval_state:
            pk = expected["id"]
            row = (
                WorkflowApproval._base_manager
                .filter(pk=pk)
                .values(
                    "pk",
                    "instance_id",
                    "status",
                    "approver_employee_id",
                    "approver_id",
                )
                .first()
            )

            if row is None:
                continue

            for key in (
                "instance_id",
                "status",
                "approver_employee_id",
                "approver_id",
            ):
                if row[key] != expected[key]:
                    report.blockers.append(
                        f"WORKFLOW: approval {pk} punya {key}="
                        f"{row[key]}, diharapkan {expected[key]}. "
                        f"Keadaannya berubah sejak diaudit.",
                    )

        # Approval lain pada instance yang dibuang akan jadi yatim.
        leftover = (
            WorkflowApproval._base_manager
            .filter(instance_id__in=spec.workflow_instance_ids)
            .exclude(pk__in=spec.workflow_approval_ids)
            .values_list("pk", flat=True)
        )

        for pk in leftover:
            report.blockers.append(
                f"WORKFLOW: approval {pk} menempel pada instance yang "
                f"dibuang tapi tidak terdaftar ikut dibuang.",
            )

    @classmethod
    def _check_protected_baseline(cls, *, spec, report) -> None:
        for label, expected in spec.protected_counts:
            actual = cls._count_label(label)

            if actual != expected:
                report.blockers.append(
                    f"PAGAR: {label} berisi {actual} baris, diharapkan "
                    f"{expected}. Master/konfigurasi berubah sejak "
                    f"diaudit.",
                )

    @staticmethod
    def _count_label(label: str) -> int:
        from django.apps import apps

        app_label, model_name = label.split(".")
        model = apps.get_model(app_label, model_name)

        return model._base_manager.count()

    # ------------------------------------------------------------------
    # Perhitungan
    # ------------------------------------------------------------------

    @classmethod
    def _steps(cls, *, spec):
        from apps.finance.models import (
            AccountingEvent,
            Journal,
            JournalLine,
            JournalLineDimension,
        )
        from apps.workflow.models import WorkflowApproval, WorkflowInstance

        journals = list(
            cls._journal_scope(spec).values_list("pk", flat=True),
        )
        lines = list(
            JournalLine._base_manager
            .filter(journal_id__in=journals)
            .values_list("pk", flat=True),
        )

        return [
            (
                "finance.JournalLineDimension",
                JournalLineDimension._base_manager.filter(
                    journal_line_id__in=lines,
                ),
            ),
            (
                "finance.JournalLine",
                JournalLine._base_manager.filter(pk__in=lines),
            ),
            # Kejadian lebih dulu dari jurnalnya: `generated_journal`
            # ber-PROTECT.
            (
                "finance.AccountingEvent",
                cls._event_scope(spec),
            ),
            (
                "finance.Journal",
                Journal._base_manager.filter(pk__in=journals),
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
        ]

    @classmethod
    def _count(cls, *, spec, report) -> None:
        for label, queryset in cls._steps(spec=spec):
            report.planned[label] = queryset.count()

    # ------------------------------------------------------------------
    # Siklus PROTECT
    # ------------------------------------------------------------------

    @classmethod
    def _reversal_pairs(cls, *, spec):
        """
        Pasangan pembalikan yang **keduanya** ikut dibuang.

        `Journal.reversed_by` dan `Journal.reversal_of` sama-sama
        PROTECT dan saling menunjuk, jadi tidak ada urutan hapus yang
        bisa menyelesaikannya — Django melempar `ProtectedError` walau
        kedua barisnya ada di batch yang sama. Satu sisi harus diputus
        lebih dulu.

        Yang diputus hanya `reversed_by` pada jurnal **asli**: satu
        kolom, satu baris per pasangan. `reversal_of` tidak disentuh
        sama sekali, dan jurnal yang tidak berpasangan tidak ikut
        di-UPDATE.
        """

        journals = set(
            cls._journal_scope(spec).values_list("pk", flat=True),
        )

        return list(
            cls._journal_scope(spec)
            .filter(
                reversed_by__isnull=False,
                reversed_by__in=journals,
            )
            .values_list("pk", "journal_number", "reversed_by_id")
            .order_by("pk"),
        )

    @classmethod
    def _collect_cycle_breaks(cls, *, spec, report) -> None:
        report.cycle_breaks = [
            CycleBreak(
                journal_id=pk,
                journal_number=number or "-",
                field="reversed_by",
                previous_value=target,
            )
            for pk, number, target in cls._reversal_pairs(spec=spec)
        ]

    @classmethod
    def _break_cycles(cls, *, spec, report) -> None:
        from apps.finance.models import Journal

        ids = [item.journal_id for item in report.cycle_breaks]

        if not ids:
            return

        Journal._base_manager.filter(pk__in=ids).update(reversed_by=None)

    # ------------------------------------------------------------------
    # Penghapusan
    # ------------------------------------------------------------------

    @classmethod
    def _delete(cls, *, spec, report) -> None:
        for label, queryset in cls._steps(spec=spec):
            if label == "finance.Journal":
                report.deleted[label] = cls._delete_journals(
                    spec=spec,
                    report=report,
                )

                continue

            pks = list(queryset.values_list("pk", flat=True))

            if not pks:
                report.deleted[label] = 0

                continue

            model = queryset.model
            _, per_model = model._base_manager.filter(pk__in=pks).delete()
            report.deleted[label] = per_model.get(model._meta.label, 0)

    @classmethod
    def _delete_journals(cls, *, spec, report) -> int:
        """
        Dua giliran, dan urutannya bukan selera.

        Sesudah `reversed_by` diputus, jurnal **pembalik** tidak lagi
        ditunjuk siapa pun sehingga bisa pergi lebih dulu. Barulah
        jurnal aslinya bebas, karena `reversal_of` yang tadinya menahan
        mereka ikut hilang bersama pembaliknya.
        """

        from apps.finance.models import Journal

        reversals = [item.previous_value for item in report.cycle_breaks]
        deleted = 0

        if reversals:
            _, per_model = Journal._base_manager.filter(
                pk__in=reversals,
            ).delete()
            deleted += per_model.get(Journal._meta.label, 0)

        remaining = list(
            cls._journal_scope(spec).values_list("pk", flat=True),
        )

        if remaining:
            _, per_model = Journal._base_manager.filter(
                pk__in=remaining,
            ).delete()
            deleted += per_model.get(Journal._meta.label, 0)

        return deleted

    # ------------------------------------------------------------------
    # Jaminan sesudah
    # ------------------------------------------------------------------

    @classmethod
    def _assert_protected_intact(cls, *, spec) -> None:
        missing = []

        for label, expected in spec.protected_counts:
            actual = cls._count_label(label)

            if actual != expected:
                missing.append(f"{label}: {actual} (harusnya {expected})")

        if missing:
            raise FinanceResetAborted(
                [f"PAGAR JEBOL: {item}" for item in missing],
            )

    @classmethod
    def _assert_ledger_empty(cls, *, spec) -> None:
        """
        Buku besar company sasaran harus kosong sesudahnya.

        Dihitung dengan rumus yang sama persis dengan `LedgerService`
        (`is_deleted=False, is_posted=True`), bukan perkiraan.
        """

        from apps.finance.models import JournalLine

        left = JournalLine._base_manager.filter(
            is_deleted=False,
            is_posted=True,
            company_id__in=spec.company_ids,
        ).count()

        if left:
            raise FinanceResetAborted([
                f"LEDGER: masih ada {left} baris terposting di company "
                f"sasaran sesudah reset.",
            ])
