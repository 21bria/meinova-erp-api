"""
Normalisasi akuntansi payroll — fakta payroll → payload `PAYROLL_POSTED`.

Berkas ini menerjemahkan hasil payroll yang sudah dihitung menjadi fakta
akuntansi **bermakna**, bukan jurnal. Yang dikeluarkannya dict
deterministik (`payroll.posting/v1`); siapa yang membaca dict itu dan
akun mana yang menerima angkanya adalah urusan kebijakan dan pemetaan
akun milik Finance. Tidak ada satu pun kode akun di sini, dan tidak ada
satu pun model Finance yang diimpor.

Dua lapis, dan pemisahannya disengaja — pola yang sama dengan
`PayrollCalculationService`:

* **Inti murni** (`PayrollAccountingNormalizer`) menerima dataclass
  (`RunFacts`, `EmployeeFacts`, `ComponentFacts`) dan tidak menyentuh
  database. Klasifikasi, agregasi, kontrol, dan digest diuji tanpa
  tenant.
* **Pemuat** (`PayrollAccountingService.build_payload`) membaca baris
  run dengan jumlah query tetap — tidak bergantung jumlah pegawai
  maupun komponen — lalu menyerahkannya ke inti.

Tiga aturan yang tidak boleh dilonggarkan:

1. **Gagal tertutup.** Kombinasi `component_type` / `source` / `basis`
   yang tidak dikenal dilempar, tidak pernah dijatuhkan ke OTHER. Angka
   yang mendarat di akun "lain-lain" karena tebakan tidak terlihat
   janggal di laporan mana pun.
2. **Tanpa identitas pegawai.** Payload hanya membawa makna, dimensi
   organisasi yang dibekukan, dan jumlah teragregasi. Nama komponen juga
   **tidak** ikut: ia teks bebas tenant, bukan kontrak.
3. **Kontrol harus rekonsiliasi.** Total yang dibaca ulang dari
   komponen harus sama persis dengan kolom hasil milik
   `PayrollRunEmployee`; kalau tidak, payload tidak diterbitkan. Tidak
   ada baris penyeimbang.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.payroll.models import (
    PayrollBasis,
    PayrollComponentSource,
    PayrollComponentType,
    PayrollInputType,
    PayrollRunEmployeeStatus,
)


SCHEMA = "payroll.posting/v1"

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

INPUT_REFERENCE_TYPE = "payroll.payroll_input"
BPJS_REFERENCE_TYPE = "payroll.bpjs_rule"

#: Urutan dimensi di kunci agregasi dan di baris payload. Persis kolom
#: snapshot organisasi `PayrollRunEmployee` minus `company` (milik
#: kepala dokumen) dan `position` (bukan dimensi akuntansi).
DIMENSIONS = (
    "branch_id",
    "location_id",
    "division_id",
    "department_id",
    "section_id",
    "cost_center_id",
)

#: Baris yang sudah dihitung. Baris `pending`/`error` belum punya hasil
#: yang sah, dan menormalisasinya berarti membukukan angka yang belum
#: pernah dinyatakan benar.
ACCOUNTABLE_LINE_STATUSES = frozenset({
    PayrollRunEmployeeStatus.CALCULATED,
    PayrollRunEmployeeStatus.FINALIZED,
})


class Semantic:
    """Makna akuntansi yang dikunci PF-0B. Nilainya kontrak — jangan diganti."""

    BASIC_SALARY = "BASIC_SALARY"
    ALLOWANCE = "ALLOWANCE"
    OVERTIME = "OVERTIME"
    OTHER_EARNING = "OTHER_EARNING"
    EARNING_REDUCTION = "EARNING_REDUCTION"
    EMPLOYEE_INCOME_TAX = "EMPLOYEE_INCOME_TAX"
    EMPLOYEE_SOCIAL_DEDUCTION = "EMPLOYEE_SOCIAL_DEDUCTION"
    EMPLOYER_SOCIAL_CONTRIBUTION = "EMPLOYER_SOCIAL_CONTRIBUTION"
    OTHER_EMPLOYEE_DEDUCTION = "OTHER_EMPLOYEE_DEDUCTION"
    OTHER_EMPLOYER_CONTRIBUTION = "OTHER_EMPLOYER_CONTRIBUTION"
    NET_PAY = "NET_PAY"


# Sifat tiap makna **dalam persamaan kontrol**, bukan keputusan akun.
# Debit/kredit sesungguhnya tetap ditentukan kebijakan Finance; yang di
# sini cuma dipakai membuktikan bahwa fakta yang dikirim seimbang.
# Beban perusahaan muncul di kedua sisi: beban dan kewajibannya.
DEBIT_SEMANTICS = frozenset({
    Semantic.BASIC_SALARY,
    Semantic.ALLOWANCE,
    Semantic.OVERTIME,
    Semantic.OTHER_EARNING,
    Semantic.EMPLOYER_SOCIAL_CONTRIBUTION,
    Semantic.OTHER_EMPLOYER_CONTRIBUTION,
})

CREDIT_SEMANTICS = frozenset({
    Semantic.EARNING_REDUCTION,
    Semantic.EMPLOYEE_INCOME_TAX,
    Semantic.EMPLOYEE_SOCIAL_DEDUCTION,
    Semantic.OTHER_EMPLOYEE_DEDUCTION,
    Semantic.EMPLOYER_SOCIAL_CONTRIBUTION,
    Semantic.OTHER_EMPLOYER_CONTRIBUTION,
    Semantic.NET_PAY,
})

# Pengurang penghasilan menurut **mesin hitung** (Business Decision #2).
# Sengaja dieja ulang di sini, bukan hanya diimpor: kontrol di bawah
# harus membaca definisi yang sama persis dengan `_settle_earnings()`,
# dan test menjaganya tetap sama dengan `EARNINGS_REDUCTION_BASES`.
REDUCTION_DETAIL_BY_BASIS = {
    PayrollBasis.PER_ABSENT_DAY: "ABSENCE",
    PayrollBasis.PER_UNPAID_LEAVE_DAY: "UNPAID_LEAVE",
}

# Input ber-sisi potongan yang maknanya gaji yang tidak terbentuk.
# Mesin hitung tetap menghitungnya sebagai potongan biasa (basisnya
# `fixed`), jadi keduanya **tidak** ikut kontrol `earning_reduction` —
# hanya maknanya yang berbeda.
INPUT_REDUCTION_DETAIL = {
    PayrollInputType.UNPAID_LEAVE: "INPUT_UNPAID_LEAVE",
    PayrollInputType.ATTENDANCE: "INPUT_ATTENDANCE",
}

KNOWN_INPUT_TYPES = frozenset(PayrollInputType.values)

# Sumber yang boleh melahirkan pengurang ber-basis ketidakhadiran.
REDUCTION_SOURCES = frozenset({
    PayrollComponentSource.ATTENDANCE,
    PayrollComponentSource.LEAVE,
    PayrollComponentSource.DEDUCTION_TEMPLATE,
})


class PayrollAccountingError(ValidationError):
    """Fakta payroll yang tidak bisa dinormalisasi dengan aman."""

    def __init__(self, message: str, *, code: str):
        super().__init__({"accounting": [message]}, code=code)
        self.error_code = code


# ----------------------------------------------------------------------
# Fakta masukan
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentFacts:
    component_type: str
    source: str
    basis: str
    amount: Decimal
    reference_type: str = ""
    reference_id: str = ""
    is_taxable: bool = False
    # Diisi pemuat dari baris sumbernya — bukan dari teks komponen.
    input_type: str = ""
    program: str = ""


@dataclass(frozen=True)
class EmployeeFacts:
    status: str
    company_id: int | None
    currency: str
    net_pay: Decimal
    gross_earning: Decimal
    total_deduction: Decimal
    tax_amount: Decimal
    employer_contribution: Decimal
    dimensions: tuple  # urutan `DIMENSIONS`
    components: tuple[ComponentFacts, ...] = ()


@dataclass(frozen=True)
class RunFacts:
    id: int
    document_number: str
    run_type: str
    company_id: int
    period_code: str
    period_start: date
    period_end: date
    # PF-0G. Diturunkan dari relasi `corrects_run`; run biasa memakai
    # nilai netral. Nomor dokumennya ikut dibekukan di sini supaya
    # normalizer tidak perlu menyentuh ORM lagi — nilainya tetap
    # diturunkan, bukan kolom tersendiri di `PayrollRun`.
    corrects_run_id: int | None = None
    corrects_document_number: str = ""
    # Kolom total yang dibekukan di `PayrollRun`. Kontrol tambahan,
    # bukan sumber angka. `None` = tidak diperiksa.
    totals: dict | None = None


@dataclass
class _Controls:
    earning_total: Decimal = ZERO
    earning_reduction: Decimal = ZERO
    deduction_total: Decimal = ZERO
    income_tax: Decimal = ZERO
    employer_contribution: Decimal = ZERO
    net_pay: Decimal = ZERO
    gross_earning: Decimal = ZERO
    total_deduction: Decimal = ZERO


@dataclass
class _EmployeeSums:
    earning: Decimal = ZERO
    reduction: Decimal = ZERO
    deduction: Decimal = ZERO
    tax: Decimal = ZERO
    employer: Decimal = ZERO
    buckets: dict = field(default_factory=lambda: defaultdict(lambda: ZERO))


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT)


def amount_text(value: Decimal) -> str:
    # `Decimal("-0.00")` dicetak "-0.00"; nol tidak pernah sampai ke sini
    # untuk komponen, tapi kontrol boleh nol.
    value = money(value)

    if value == ZERO:
        value = ZERO

    return f"{value:.2f}"


# ----------------------------------------------------------------------
# Inti murni
# ----------------------------------------------------------------------


class PayrollAccountingNormalizer:
    """Fakta → payload. Tanpa database."""

    # ------------------------------------------------------------------
    # Klasifikasi
    # ------------------------------------------------------------------

    @classmethod
    def classify(cls, component: ComponentFacts) -> tuple[str, str, str]:
        """`(semantic, detail, program)` untuk satu komponen, atau lempar."""
        kind = component.component_type

        if kind == PayrollComponentType.EARNING:
            return cls._classify_earning(component)

        if kind == PayrollComponentType.DEDUCTION:
            return cls._classify_deduction(component)

        if kind == PayrollComponentType.EMPLOYER_CONTRIBUTION:
            return cls._classify_employer(component)

        raise cls._unknown(component)

    @classmethod
    def _classify_earning(cls, component):
        source = component.source

        if source == PayrollComponentSource.BASIC:
            return Semantic.BASIC_SALARY, "", ""

        if source == PayrollComponentSource.ALLOWANCE_TEMPLATE:
            return (
                Semantic.ALLOWANCE,
                "TAXABLE" if component.is_taxable else "NON_TAXABLE",
                "",
            )

        if source == PayrollComponentSource.OVERTIME:
            return Semantic.OVERTIME, "", ""

        if source == PayrollComponentSource.INPUT:
            input_type = cls._input_type(component)

            if input_type == PayrollInputType.OVERTIME:
                return Semantic.OVERTIME, "INPUT", ""

            if input_type == PayrollInputType.ALLOWANCE:
                return Semantic.ALLOWANCE, "INPUT", ""

            # Insentif, reimbursement, koreksi, dan input ber-sisi
            # potongan yang dipindah ke sisi penghasilan. Detailnya kode
            # enum `PayrollInputType`, bukan teks bebas.
            return Semantic.OTHER_EARNING, input_type.upper(), ""

        raise cls._unknown(component)

    @classmethod
    def _classify_deduction(cls, component):
        source = component.source
        basis = component.basis

        if basis in REDUCTION_DETAIL_BY_BASIS:
            if source not in REDUCTION_SOURCES:
                raise cls._unknown(component)

            return (
                Semantic.EARNING_REDUCTION,
                REDUCTION_DETAIL_BY_BASIS[basis],
                "",
            )

        if source == PayrollComponentSource.TAX:
            return Semantic.EMPLOYEE_INCOME_TAX, "", ""

        if source == PayrollComponentSource.BPJS:
            return (
                Semantic.EMPLOYEE_SOCIAL_DEDUCTION,
                "",
                cls._program(component),
            )

        if source == PayrollComponentSource.INPUT:
            input_type = cls._input_type(component)

            if input_type in INPUT_REDUCTION_DETAIL:
                return (
                    Semantic.EARNING_REDUCTION,
                    INPUT_REDUCTION_DETAIL[input_type],
                    "",
                )

            # Termasuk `adjustment` → ADJUSTMENT dan `deduction` →
            # DEDUCTION. Pinjaman/kasbon belum dibedakan (M4 ditunda).
            return Semantic.OTHER_EMPLOYEE_DEDUCTION, input_type.upper(), ""

        if source == PayrollComponentSource.DEDUCTION_TEMPLATE:
            return Semantic.OTHER_EMPLOYEE_DEDUCTION, "TEMPLATE", ""

        # `attendance`/`leave` tanpa basis ketidakhadiran, atau sumber
        # sisi penghasilan yang tercatat sebagai potongan.
        raise cls._unknown(component)

    @classmethod
    def _classify_employer(cls, component):
        source = component.source

        if source == PayrollComponentSource.BPJS:
            return (
                Semantic.EMPLOYER_SOCIAL_CONTRIBUTION,
                "",
                cls._program(component),
            )

        if source == PayrollComponentSource.DEDUCTION_TEMPLATE:
            return Semantic.OTHER_EMPLOYER_CONTRIBUTION, "TEMPLATE", ""

        raise cls._unknown(component)

    @classmethod
    def _input_type(cls, component) -> str:
        if (
            component.reference_type != INPUT_REFERENCE_TYPE
            or component.input_type not in KNOWN_INPUT_TYPES
        ):
            raise cls._unknown(
                component,
                reason="jenis Payroll Input tidak bisa dipastikan",
            )

        return component.input_type

    @classmethod
    def _program(cls, component) -> str:
        if component.reference_type != BPJS_REFERENCE_TYPE or not component.program:
            raise cls._unknown(
                component,
                reason="program BPJS tidak bisa dipastikan",
            )

        return component.program.strip().upper()

    @staticmethod
    def _unknown(component, *, reason: str = "") -> PayrollAccountingError:
        # Konteks teknis saja — tidak ada pegawai, tidak ada jumlah.
        context = (
            f"component_type={component.component_type or '—'}, "
            f"source={component.source or '—'}, "
            f"basis={component.basis or '—'}, "
            f"reference_type={component.reference_type or '—'}"
        )

        return PayrollAccountingError(
            (
                "Komponen payroll tidak punya makna akuntansi yang "
                f"dikenal ({context})"
                + (f": {reason}" if reason else "")
                + ". Normalisasi dihentikan; tidak ada yang dijatuhkan "
                "ke kategori lain-lain."
            ),
            code="unknown_component",
        )

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, *, run: RunFacts, employees) -> dict:
        employees = list(employees)

        if not employees:
            raise PayrollAccountingError(
                "Run tidak memuat satu pun pegawai yang dihitung.",
                code="empty_run",
            )

        currency = cls._currency(employees)
        cls._check_lines(run=run, employees=employees)

        controls = _Controls()
        buckets: dict[tuple, Decimal] = defaultdict(lambda: ZERO)

        for index, employee in enumerate(employees, start=1):
            sums = cls._employee(employee)

            cls._reconcile_employee(index=index, employee=employee, sums=sums)

            controls.earning_total += sums.earning
            controls.earning_reduction += sums.reduction
            controls.deduction_total += sums.deduction
            controls.income_tax += sums.tax
            controls.employer_contribution += sums.employer
            controls.net_pay += money(employee.net_pay)
            controls.gross_earning += money(employee.gross_earning)
            controls.total_deduction += money(employee.total_deduction)

            for key, value in sums.buckets.items():
                buckets[key] += value

            buckets[(Semantic.NET_PAY, "", "", *employee.dimensions)] += money(
                employee.net_pay,
            )

        cls._reconcile_run(run=run, controls=controls)

        components = cls._components(run=run, buckets=buckets)
        total_debit, total_credit = cls._sides(components)

        if total_debit != total_credit:
            raise PayrollAccountingError(
                (
                    "Fakta akuntansi payroll tidak seimbang "
                    f"(debit {amount_text(total_debit)}, kredit "
                    f"{amount_text(total_credit)})."
                ),
                code="unbalanced",
            )

        payload = {
            "schema": SCHEMA,
            "run": {
                "id": run.id,
                "document_number": run.document_number,
                "run_type": run.run_type,
                "company_id": run.company_id,
                "period_code": run.period_code,
                "period_start": run.period_start.isoformat(),
                "period_end": run.period_end.isoformat(),
                # PF-0G. Diturunkan dari relasi `corrects_run`; run biasa
                # tetap mengirim nilai netral. Keduanya ikut ke dalam
                # digest lewat blok `run` yang sama seperti sebelumnya —
                # koreksi karena itu tidak pernah punya digest yang sama
                # dengan run yang dikoreksinya.
                "corrects_run_id": run.corrects_run_id,
                "corrects_document_number": run.corrects_document_number,
            },
            "currency": currency,
            "control": {
                "earning_total": amount_text(controls.earning_total),
                "earning_reduction": amount_text(controls.earning_reduction),
                "gross_earning": amount_text(controls.gross_earning),
                "deduction_total": amount_text(controls.deduction_total),
                "total_deduction": amount_text(controls.total_deduction),
                "income_tax": amount_text(controls.income_tax),
                "employer_contribution": amount_text(
                    controls.employer_contribution,
                ),
                "net_pay": amount_text(controls.net_pay),
                "total_debit": amount_text(total_debit),
                "total_credit": amount_text(total_credit),
            },
            "components": components,
        }

        payload["digest"] = digest(payload)

        return payload

    @staticmethod
    def _currency(employees) -> str:
        missing = sum(1 for row in employees if not (row.currency or "").strip())

        if missing:
            raise PayrollAccountingError(
                (
                    f"{missing} baris payroll tidak punya mata uang. "
                    "Akuntansi tidak mengasumsikan mata uang apa pun."
                ),
                code="currency_missing",
            )

        codes = sorted({row.currency.strip().upper() for row in employees})

        if len(codes) > 1:
            raise PayrollAccountingError(
                (
                    "Satu run memuat lebih dari satu mata uang "
                    f"({', '.join(codes)})."
                ),
                code="currency_mixed",
            )

        return codes[0]

    @staticmethod
    def _check_lines(*, run: RunFacts, employees) -> None:
        not_ready = sum(
            1 for row in employees
            if row.status not in ACCOUNTABLE_LINE_STATUSES
        )

        if not_ready:
            raise PayrollAccountingError(
                f"{not_ready} baris payroll belum berstatus dihitung.",
                code="line_not_calculated",
            )

        foreign = sum(1 for row in employees if row.company_id != run.company_id)

        if foreign:
            raise PayrollAccountingError(
                (
                    f"{foreign} baris payroll tidak tercatat pada company "
                    "run ini. Satu kejadian akuntansi hanya milik satu "
                    "company."
                ),
                code="company_mismatch",
            )

        for row in employees:
            if len(row.dimensions) != len(DIMENSIONS):
                raise PayrollAccountingError(
                    "Dimensi baris payroll tidak lengkap.",
                    code="dimension_shape",
                )

    @classmethod
    def _employee(cls, employee: EmployeeFacts) -> _EmployeeSums:
        sums = _EmployeeSums()

        for component in employee.components:
            amount = money(component.amount)
            semantic, detail, program = cls.classify(component)
            kind = component.component_type

            if kind == PayrollComponentType.EARNING:
                sums.earning += amount
            elif kind == PayrollComponentType.DEDUCTION:
                sums.deduction += amount

                if component.basis in REDUCTION_DETAIL_BY_BASIS:
                    sums.reduction += amount

                if component.source == PayrollComponentSource.TAX:
                    sums.tax += amount
            else:
                sums.employer += amount

            sums.buckets[(semantic, detail, program, *employee.dimensions)] += amount

        return sums

    @staticmethod
    def _reconcile_employee(*, index, employee, sums) -> None:
        # Identitas mesin hitung, per pegawai supaya kesalahan yang saling
        # menutup antarpegawai tetap tertangkap. Pesan menyebut urutan
        # baris, bukan pegawainya.
        checks = (
            ("gross_earning", sums.earning - sums.reduction, employee.gross_earning),
            ("total_deduction", sums.deduction - sums.reduction, employee.total_deduction),
            ("net_pay", sums.earning - sums.deduction, employee.net_pay),
            ("tax_amount", sums.tax, employee.tax_amount),
            ("employer_contribution", sums.employer, employee.employer_contribution),
        )

        for name, derived, stored in checks:
            if money(derived) != money(stored):
                raise PayrollAccountingError(
                    (
                        f"Kontrol '{name}' baris payroll ke-{index} tidak "
                        "cocok dengan rincian komponennya. Hitung ulang "
                        "run sebelum dibukukan."
                    ),
                    code="control_mismatch",
                )

    @staticmethod
    def _reconcile_run(*, run: RunFacts, controls: _Controls) -> None:
        if not run.totals:
            return

        pairs = {
            "total_earning": controls.gross_earning,
            "total_deduction": controls.total_deduction,
            "total_tax": controls.income_tax,
            "total_net": controls.net_pay,
            "total_employer_contribution": controls.employer_contribution,
        }

        for name, derived in pairs.items():
            if name not in run.totals:
                continue

            if money(run.totals[name]) != money(derived):
                raise PayrollAccountingError(
                    (
                        f"Total run '{name}' tidak cocok dengan baris "
                        "pegawainya."
                    ),
                    code="control_mismatch",
                )

    @staticmethod
    def _components(*, run: RunFacts, buckets) -> list[dict]:
        rows = []

        for key in sorted(buckets, key=sort_key):
            amount = money(buckets[key])

            if amount == ZERO:
                continue

            semantic, detail, program, *dims = key

            row = {
                "semantic": semantic,
                "detail": detail,
                "program": program,
                "amount": amount_text(amount),
                "reference": run.document_number,
            }
            row.update(dict(zip(DIMENSIONS, dims)))

            rows.append(row)

        return rows

    @staticmethod
    def _sides(components) -> tuple[Decimal, Decimal]:
        debit = ZERO
        credit = ZERO

        for row in components:
            amount = Decimal(row["amount"])

            if row["semantic"] in DEBIT_SEMANTICS:
                debit += amount

            if row["semantic"] in CREDIT_SEMANTICS:
                credit += amount

        return debit, credit


def sort_key(key: tuple) -> tuple:
    """Kunci agregasi → urutan total. `None` selalu sebelum angka."""
    semantic, detail, program, *dims = key

    return (
        semantic,
        detail,
        program,
        *((0, 0) if value is None else (1, value) for value in dims),
    )


def digest(payload: dict) -> str:
    """
    `sha256(json.dumps({schema, run, currency, control, components},
    sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    .encode("utf-8")).hexdigest()`

    Seluruh isi payload kecuali `digest` sendiri. Tidak ada cap waktu
    atau metadata yang berubah-ubah di dalamnya.
    """
    content = {
        key: payload[key]
        for key in ("schema", "run", "currency", "control", "components")
    }

    encoded = json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


# ----------------------------------------------------------------------
# Pemuat
# ----------------------------------------------------------------------


class PayrollAccountingService:
    """Membaca run dari database, lalu menormalisasinya."""

    @classmethod
    def build_payload(cls, *, run) -> dict:
        """
        Payload `payroll.posting/v1` untuk satu run.

        Query tetap: kepala run, baris pegawai, id sumber input & BPJS,
        peta jenis input, peta program BPJS, dan komponen — berapa pun
        pegawainya.
        """
        from apps.payroll.models import (
            BpjsRule,
            PayrollInput,
            PayrollRun,
            PayrollRunComponent,
            PayrollRunEmployee,
        )

        run = (
            PayrollRun.objects
            .select_related("period", "corrects_run")
            .get(pk=run.pk)
        )

        lines = list(
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False, is_excluded=False)
            .order_by("pk")
            .values(
                "pk",
                "status",
                "company_id",
                "currency__code",
                "net_pay",
                "gross_earning",
                "total_deduction",
                "tax_amount",
                "employer_contribution",
                *DIMENSIONS,
            )
        )

        components = (
            PayrollRunComponent.objects
            .filter(
                run_employee__run=run,
                run_employee__is_deleted=False,
                run_employee__is_excluded=False,
                is_deleted=False,
            )
        )

        input_ids = cls._ids(components, INPUT_REFERENCE_TYPE)
        rule_ids = cls._ids(components, BPJS_REFERENCE_TYPE)

        # Baris sumber dibaca **termasuk** yang sudah dihapus lunak:
        # komponennya lahir dari baris itu, dan maknanya tidak hilang
        # karena inputnya dirapikan sesudah run dihitung.
        input_types = {
            str(pk): input_type
            for pk, input_type in (
                PayrollInput.objects
                .filter(pk__in=input_ids)
                .values_list("pk", "input_type")
            )
        } if input_ids else {}

        programs = {
            str(pk): code
            for pk, code in (
                BpjsRule.objects
                .filter(pk__in=rule_ids)
                .values_list("pk", "program__code")
            )
        } if rule_ids else {}

        by_line: dict[int, list[ComponentFacts]] = defaultdict(list)

        rows = (
            components
            .order_by("run_employee_id", "pk")
            .values_list(
                "run_employee_id",
                "component_type",
                "source",
                "basis",
                "amount",
                "reference_type",
                "reference_id",
                "is_taxable",
            )
            .iterator(chunk_size=2000)
        )

        for (
            line_id, kind, source, basis, amount,
            reference_type, reference_id, is_taxable,
        ) in rows:
            by_line[line_id].append(
                ComponentFacts(
                    component_type=kind,
                    source=source,
                    basis=basis,
                    amount=amount,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    is_taxable=is_taxable,
                    input_type=(
                        input_types.get(reference_id, "")
                        if reference_type == INPUT_REFERENCE_TYPE
                        else ""
                    ),
                    program=(
                        programs.get(reference_id) or ""
                        if reference_type == BPJS_REFERENCE_TYPE
                        else ""
                    ),
                ),
            )

        employees = [
            EmployeeFacts(
                status=line["status"],
                company_id=line["company_id"],
                currency=line["currency__code"] or "",
                net_pay=line["net_pay"],
                gross_earning=line["gross_earning"],
                total_deduction=line["total_deduction"],
                tax_amount=line["tax_amount"],
                employer_contribution=line["employer_contribution"],
                dimensions=tuple(line[name] for name in DIMENSIONS),
                components=tuple(by_line.get(line["pk"], ())),
            )
            for line in lines
        ]

        period = run.period

        facts = RunFacts(
            id=run.pk,
            document_number=run.document_number,
            run_type=run.run_type,
            company_id=run.company_id,
            period_code=period.code,
            period_start=period.start_date,
            period_end=period.end_date,
            corrects_run_id=run.corrects_run_id,
            corrects_document_number=(
                run.corrects_run.document_number
                if run.corrects_run_id
                else ""
            ),
            totals={
                "total_earning": run.total_earning,
                "total_deduction": run.total_deduction,
                "total_tax": run.total_tax,
                "total_net": run.total_net,
                "total_employer_contribution": run.total_employer_contribution,
            },
        )

        return PayrollAccountingNormalizer.build(run=facts, employees=employees)

    @staticmethod
    def _ids(components, reference_type: str) -> list[int]:
        ids = set()

        for value in (
            components
            .filter(reference_type=reference_type)
            # Urutan bawaan model dibuang: kolomnya ikut ke SELECT
            # DISTINCT dan membuat id yang sama muncul berkali-kali.
            .order_by()
            .values_list("reference_id", flat=True)
            .distinct()
        ):
            if str(value).isdigit():
                ids.add(int(value))

        return sorted(ids)
