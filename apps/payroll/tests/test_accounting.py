"""
Normalisasi akuntansi payroll (PF-0C), tanpa database.

`SimpleTestCase` disengaja, sama seperti `test_calculation.py`: inti
normalisasi menerima dataclass dan tidak boleh menerbitkan query.
Pemuatnya (`PayrollAccountingService.build_payload`) diuji bersama
wiring finalize di PF-0D, yang memang butuh tenant.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from apps.payroll.models import EARNINGS_REDUCTION_BASES
from apps.payroll.services import accounting
from apps.payroll.services.accounting import (
    BPJS_REFERENCE_TYPE,
    DIMENSIONS,
    INPUT_REFERENCE_TYPE,
    REDUCTION_DETAIL_BY_BASIS,
    ComponentFacts,
    EmployeeFacts,
    PayrollAccountingError,
    PayrollAccountingNormalizer,
    RunFacts,
    Semantic,
)


def D(value):
    """Decimal dari teks — tidak pernah lewat float."""
    return Decimal(str(value))


RUN = RunFacts(
    id=41,
    document_number="PAY-2026-00041",
    run_type="regular",
    company_id=1,
    period_code="2026-08",
    period_start=date(2026, 8, 1),
    period_end=date(2026, 8, 31),
)

# branch, location, division, department, section, cost_center
DIMS_A = (1, 10, 100, 1000, 10000, 100000)
DIMS_B = (1, 10, 100, 1000, 10000, 100001)


def basic(amount):
    return ComponentFacts("earning", "basic", "fixed", D(amount))


def allowance(amount, taxable=True):
    return ComponentFacts(
        "earning", "allowance_template", "fixed", D(amount),
        reference_type="payroll.allowance_template_line", reference_id="3",
        is_taxable=taxable,
    )


def overtime(amount):
    return ComponentFacts("earning", "overtime", "fixed", D(amount))


def input_row(amount, input_type, side="earning", pk="7"):
    return ComponentFacts(
        side, "input", "fixed", D(amount),
        reference_type=INPUT_REFERENCE_TYPE, reference_id=pk,
        input_type=input_type,
    )


def absence(amount, source="attendance", basis="per_absent_day"):
    return ComponentFacts("deduction", source, basis, D(amount))


def tax(amount):
    return ComponentFacts(
        "deduction", "tax", "pph21_progressive", D(amount),
        reference_type="payroll.deduction_template_line", reference_id="9",
    )


def bpjs(amount, program="JHT", employer=False):
    return ComponentFacts(
        "employer_contribution" if employer else "deduction",
        "bpjs", "percent_of_resolved_base", D(amount),
        reference_type=BPJS_REFERENCE_TYPE, reference_id="5",
        program=program,
    )


def template_deduction(amount, employer=False):
    return ComponentFacts(
        "employer_contribution" if employer else "deduction",
        "deduction_template", "fixed", D(amount),
        reference_type="payroll.deduction_template_line", reference_id="11",
    )


def employee(components, *, dims=DIMS_A, currency="IDR", company=1,
             status="calculated", **overrides):
    """Baris pegawai yang kontrolnya konsisten dengan komponennya."""
    earning = sum((c.amount for c in components if c.component_type == "earning"), D(0))
    deduction = sum((c.amount for c in components if c.component_type == "deduction"), D(0))
    reduction = sum(
        (c.amount for c in components
         if c.component_type == "deduction" and c.basis in REDUCTION_DETAIL_BY_BASIS),
        D(0),
    )
    tax_amount = sum((c.amount for c in components if c.source == "tax"), D(0))
    employer = sum(
        (c.amount for c in components if c.component_type == "employer_contribution"),
        D(0),
    )

    values = {
        "status": status,
        "company_id": company,
        "currency": currency,
        "net_pay": earning - deduction,
        "gross_earning": earning - reduction,
        "total_deduction": deduction - reduction,
        "tax_amount": tax_amount,
        "employer_contribution": employer,
        "dimensions": dims,
        "components": tuple(components),
    }
    values.update(overrides)

    return EmployeeFacts(**values)


def build(*employees, run=RUN):
    return PayrollAccountingNormalizer.build(run=run, employees=employees)


def rows(payload, semantic):
    return [row for row in payload["components"] if row["semantic"] == semantic]


def only(payload, semantic):
    found = rows(payload, semantic)
    assert len(found) == 1, found
    return found[0]


class ClassificationTest(SimpleTestCase):
    def classify(self, component):
        return PayrollAccountingNormalizer.classify(component)

    def test_basic_salary(self):
        self.assertEqual(self.classify(basic(1)), (Semantic.BASIC_SALARY, "", ""))

    def test_allowance(self):
        self.assertEqual(
            self.classify(allowance(1)), (Semantic.ALLOWANCE, "TAXABLE", ""),
        )
        self.assertEqual(
            self.classify(allowance(1, taxable=False)),
            (Semantic.ALLOWANCE, "NON_TAXABLE", ""),
        )

    def test_overtime_source(self):
        self.assertEqual(self.classify(overtime(1)), (Semantic.OVERTIME, "", ""))

    def test_overtime_input(self):
        self.assertEqual(
            self.classify(input_row(1, "overtime")),
            (Semantic.OVERTIME, "INPUT", ""),
        )

    def test_allowance_input(self):
        self.assertEqual(
            self.classify(input_row(1, "allowance")),
            (Semantic.ALLOWANCE, "INPUT", ""),
        )

    def test_other_earning_inputs(self):
        for input_type in ("incentive", "reimbursement", "adjustment"):
            with self.subTest(input_type):
                self.assertEqual(
                    self.classify(input_row(1, input_type)),
                    (Semantic.OTHER_EARNING, input_type.upper(), ""),
                )

    def test_absence_is_earning_reduction(self):
        self.assertEqual(
            self.classify(absence(1)),
            (Semantic.EARNING_REDUCTION, "ABSENCE", ""),
        )

    def test_unpaid_leave_is_earning_reduction(self):
        for source in ("leave", "deduction_template"):
            with self.subTest(source):
                self.assertEqual(
                    self.classify(absence(1, source=source, basis="per_unpaid_leave_day")),
                    (Semantic.EARNING_REDUCTION, "UNPAID_LEAVE", ""),
                )

    def test_reduction_inputs(self):
        self.assertEqual(
            self.classify(input_row(1, "unpaid_leave", side="deduction")),
            (Semantic.EARNING_REDUCTION, "INPUT_UNPAID_LEAVE", ""),
        )
        self.assertEqual(
            self.classify(input_row(1, "attendance", side="deduction")),
            (Semantic.EARNING_REDUCTION, "INPUT_ATTENDANCE", ""),
        )

    def test_tax(self):
        self.assertEqual(
            self.classify(tax(1)), (Semantic.EMPLOYEE_INCOME_TAX, "", ""),
        )

    def test_employee_bpjs_carries_program(self):
        self.assertEqual(
            self.classify(bpjs(1, program="jkn")),
            (Semantic.EMPLOYEE_SOCIAL_DEDUCTION, "", "JKN"),
        )

    def test_employer_bpjs_carries_program(self):
        self.assertEqual(
            self.classify(bpjs(1, program="JKK", employer=True)),
            (Semantic.EMPLOYER_SOCIAL_CONTRIBUTION, "", "JKK"),
        )

    def test_other_employee_deduction(self):
        self.assertEqual(
            self.classify(template_deduction(1)),
            (Semantic.OTHER_EMPLOYEE_DEDUCTION, "TEMPLATE", ""),
        )
        self.assertEqual(
            self.classify(input_row(1, "deduction", side="deduction")),
            (Semantic.OTHER_EMPLOYEE_DEDUCTION, "DEDUCTION", ""),
        )

    def test_other_employer_contribution(self):
        self.assertEqual(
            self.classify(template_deduction(1, employer=True)),
            (Semantic.OTHER_EMPLOYER_CONTRIBUTION, "TEMPLATE", ""),
        )

    def test_deduction_side_adjustment(self):
        self.assertEqual(
            self.classify(input_row(1, "adjustment", side="deduction")),
            (Semantic.OTHER_EMPLOYEE_DEDUCTION, "ADJUSTMENT", ""),
        )

    def test_reduction_bases_match_calculation_engine(self):
        self.assertEqual(
            set(REDUCTION_DETAIL_BY_BASIS), set(EARNINGS_REDUCTION_BASES),
        )


class FailClosedTest(SimpleTestCase):
    UNKNOWN = [
        ComponentFacts("earning", "tax", "fixed", D(1)),
        ComponentFacts("earning", "bpjs", "fixed", D(1)),
        ComponentFacts("earning", "attendance", "fixed", D(1)),
        ComponentFacts("deduction", "basic", "fixed", D(1)),
        ComponentFacts("deduction", "attendance", "fixed", D(1)),
        ComponentFacts("deduction", "tax", "per_absent_day", D(1)),
        ComponentFacts("employer_contribution", "input", "fixed", D(1)),
        ComponentFacts("employer_contribution", "tax", "fixed", D(1)),
        ComponentFacts("mystery", "basic", "fixed", D(1)),
        # Input tanpa jenis yang bisa dipastikan.
        ComponentFacts("earning", "input", "fixed", D(1),
                       reference_type=INPUT_REFERENCE_TYPE, input_type=""),
        ComponentFacts("earning", "input", "fixed", D(1),
                       reference_type="", input_type="incentive"),
        ComponentFacts("earning", "input", "fixed", D(1),
                       reference_type=INPUT_REFERENCE_TYPE, input_type="bonus_x"),
        # BPJS tanpa program.
        ComponentFacts("deduction", "bpjs", "percent_of_resolved_base", D(1),
                       reference_type=BPJS_REFERENCE_TYPE, program=""),
    ]

    def test_unknown_combinations_raise(self):
        for component in self.UNKNOWN:
            with self.subTest(component):
                with self.assertRaises(PayrollAccountingError) as caught:
                    PayrollAccountingNormalizer.classify(component)

                self.assertEqual(caught.exception.error_code, "unknown_component")
                message = " ".join(caught.exception.messages)
                self.assertIn(f"component_type={component.component_type}", message)
                self.assertIn(f"source={component.source}", message)
                self.assertIn(f"basis={component.basis}", message)

    def test_unknown_component_stops_the_whole_payload(self):
        with self.assertRaises(PayrollAccountingError):
            build(employee([basic(100), ComponentFacts("earning", "tax", "fixed", D(5))]))


class PayloadTest(SimpleTestCase):
    def test_net_pay_is_derived_from_lines(self):
        payload = build(
            employee([basic(1000), tax(50), bpjs(20)]),
            employee([basic(500)]),
        )

        self.assertEqual(only(payload, Semantic.NET_PAY)["amount"], "1430.00")
        self.assertEqual(payload["control"]["net_pay"], "1430.00")

    def test_same_bucket_aggregates_across_employees(self):
        payload = build(*(employee([basic(1000)]) for _ in range(3)))

        self.assertEqual(only(payload, Semantic.BASIC_SALARY)["amount"], "3000.00")

    def test_different_cost_centers_stay_separate(self):
        payload = build(
            employee([basic(1000)], dims=DIMS_A),
            employee([basic(700)], dims=DIMS_B),
        )

        found = rows(payload, Semantic.BASIC_SALARY)
        self.assertEqual(
            [(row["cost_center_id"], row["amount"]) for row in found],
            [(100000, "1000.00"), (100001, "700.00")],
        )

    def test_different_departments_stay_separate(self):
        other = (1, 10, 100, 2000, 10000, 100000)
        payload = build(
            employee([basic(1000)], dims=DIMS_A),
            employee([basic(700)], dims=other),
        )

        self.assertEqual(
            [row["department_id"] for row in rows(payload, Semantic.BASIC_SALARY)],
            [1000, 2000],
        )

    def test_every_frozen_dimension_splits_the_bucket(self):
        for position, name in enumerate(DIMENSIONS):
            with self.subTest(name):
                changed = list(DIMS_A)
                changed[position] += 5
                payload = build(
                    employee([basic(1000)], dims=DIMS_A),
                    employee([basic(1000)], dims=tuple(changed)),
                )

                found = rows(payload, Semantic.BASIC_SALARY)
                self.assertEqual(len(found), 2)
                self.assertEqual(
                    sorted(row[name] for row in found),
                    sorted([DIMS_A[position], changed[position]]),
                )

    def test_missing_dimension_is_null_and_sorted_first(self):
        payload = build(
            employee([basic(1)], dims=DIMS_A),
            employee([basic(2)], dims=(1, 10, 100, 1000, 10000, None)),
        )

        self.assertEqual(
            [row["cost_center_id"] for row in rows(payload, Semantic.BASIC_SALARY)],
            [None, 100000],
        )

    def test_zero_buckets_are_dropped(self):
        payload = build(
            employee([
                basic(1000),
                allowance(0),
                input_row(50, "incentive", pk="1"),
                input_row(-50, "incentive", pk="2"),
            ]),
        )

        semantics = {row["semantic"] for row in payload["components"]}
        self.assertEqual(semantics, {Semantic.BASIC_SALARY, Semantic.NET_PAY})

    def test_negative_input_is_kept_signed_and_deterministic(self):
        first = build(employee([basic(1000), input_row(-150, "adjustment")]))
        second = build(employee([basic(1000), input_row(-150, "adjustment")]))

        row = only(first, Semantic.OTHER_EARNING)
        self.assertEqual((row["detail"], row["amount"]), ("ADJUSTMENT", "-150.00"))
        self.assertEqual(only(first, Semantic.NET_PAY)["amount"], "850.00")
        self.assertEqual(first, second)
        self.assertEqual(
            first["control"]["total_debit"], first["control"]["total_credit"],
        )

    def test_negative_input_nets_within_its_bucket(self):
        payload = build(employee([
            basic(1000),
            input_row(300, "incentive", pk="1"),
            input_row(-100, "incentive", pk="2"),
        ]))

        self.assertEqual(only(payload, Semantic.OTHER_EARNING)["amount"], "200.00")

    def test_row_contract(self):
        payload = build(employee([basic(1000)]))

        for row in payload["components"]:
            self.assertEqual(
                set(row),
                {"semantic", "detail", "program", "amount", "reference", *DIMENSIONS},
            )
            self.assertEqual(row["reference"], "PAY-2026-00041")

        self.assertEqual(
            set(payload),
            {"schema", "run", "currency", "control", "components", "digest"},
        )
        self.assertEqual(payload["schema"], "payroll.posting/v1")
        self.assertIsNone(payload["run"]["corrects_run_id"])
        self.assertEqual(payload["run"]["corrects_document_number"], "")
        self.assertEqual(payload["run"]["period_end"], "2026-08-31")

    def test_payload_is_json_serialisable_without_floats(self):
        payload = build(employee([basic("1000.10"), tax("33.33")]))
        text = json.dumps(payload)

        def no_floats(value):
            if isinstance(value, float):
                raise AssertionError(value)
            if isinstance(value, dict):
                for item in value.values():
                    no_floats(item)
            if isinstance(value, list):
                for item in value:
                    no_floats(item)

        no_floats(json.loads(text))
        self.assertEqual(payload["control"]["income_tax"], "33.33")


class CurrencyTest(SimpleTestCase):
    def test_single_currency_is_reported(self):
        payload = build(employee([basic(1)], currency="usd"))
        self.assertEqual(payload["currency"], "USD")

    def test_missing_currency_fails(self):
        with self.assertRaises(PayrollAccountingError) as caught:
            build(employee([basic(1)]), employee([basic(1)], currency=""))

        self.assertEqual(caught.exception.error_code, "currency_missing")

    def test_mixed_currency_fails(self):
        with self.assertRaises(PayrollAccountingError) as caught:
            build(employee([basic(1)]), employee([basic(1)], currency="USD"))

        self.assertEqual(caught.exception.error_code, "currency_mixed")


class ControlTest(SimpleTestCase):
    def full_employee(self):
        return employee([
            basic(10000),
            allowance(1500),
            overtime(400),
            input_row(250, "incentive"),
            absence(333.33),
            absence(666.67, source="leave", basis="per_unpaid_leave_day"),
            input_row(100, "unpaid_leave", side="deduction", pk="8"),
            tax(420.50),
            bpjs(200, program="JHT"),
            bpjs(100, program="JKN"),
            bpjs(370, program="JHT", employer=True),
            template_deduction(75),
            template_deduction(60, employer=True),
        ])

    def test_controls_follow_calculation_semantics(self):
        control = build(self.full_employee())["control"]

        self.assertEqual(control["earning_total"], "12150.00")
        # Hanya basis ketidakhadiran; input unpaid_leave tetap potongan
        # biasa di mesin hitung.
        self.assertEqual(control["earning_reduction"], "1000.00")
        self.assertEqual(control["gross_earning"], "11150.00")
        self.assertEqual(control["deduction_total"], "1895.50")
        self.assertEqual(control["total_deduction"], "895.50")
        self.assertEqual(control["income_tax"], "420.50")
        self.assertEqual(control["employer_contribution"], "430.00")
        self.assertEqual(control["net_pay"], "10254.50")

    def test_journal_semantics_balance(self):
        payload = build(self.full_employee(), employee([basic(5000), tax(100)], dims=DIMS_B))
        control = payload["control"]

        # Debit = E + C, Kredit = D + C + N.
        self.assertEqual(control["total_debit"], "17580.00")
        self.assertEqual(control["total_credit"], "17580.00")

        debit = sum(
            Decimal(row["amount"]) for row in payload["components"]
            if row["semantic"] in accounting.DEBIT_SEMANTICS
        )
        credit = sum(
            Decimal(row["amount"]) for row in payload["components"]
            if row["semantic"] in accounting.CREDIT_SEMANTICS
        )
        self.assertEqual(debit, credit)

    def test_tax_is_not_double_counted(self):
        payload = build(employee([basic(1000), tax(100)]))
        control = payload["control"]

        self.assertEqual(control["deduction_total"], "100.00")
        self.assertEqual(control["total_credit"], "1000.00")
        self.assertEqual(len(rows(payload, Semantic.EMPLOYEE_INCOME_TAX)), 1)

    def test_employer_contribution_does_not_touch_net_pay(self):
        payload = build(employee([basic(1000), bpjs(40, employer=True)]))

        self.assertEqual(only(payload, Semantic.NET_PAY)["amount"], "1000.00")
        self.assertEqual(payload["control"]["total_debit"], "1040.00")
        self.assertEqual(payload["control"]["total_credit"], "1040.00")

    def test_employee_control_mismatch_fails(self):
        for field in (
            "net_pay", "gross_earning", "total_deduction",
            "tax_amount", "employer_contribution",
        ):
            with self.subTest(field):
                good = employee([basic(1000), tax(10), bpjs(5, employer=True)])
                bad = replace(good, **{field: getattr(good, field) + D("0.01")})

                with self.assertRaises(PayrollAccountingError) as caught:
                    build(bad)

                self.assertEqual(caught.exception.error_code, "control_mismatch")
                self.assertNotIn(str(bad.net_pay), " ".join(caught.exception.messages))

    def test_run_total_mismatch_fails(self):
        run = replace(RUN, totals={
            "total_earning": D("1000.00"),
            "total_deduction": D("0.00"),
            "total_tax": D("0.00"),
            "total_net": D("999.00"),
            "total_employer_contribution": D("0.00"),
        })

        with self.assertRaises(PayrollAccountingError) as caught:
            build(employee([basic(1000)]), run=run)

        self.assertEqual(caught.exception.error_code, "control_mismatch")

    def test_matching_run_totals_pass(self):
        run = replace(RUN, totals={
            "total_earning": D("1000.00"),
            "total_deduction": D("10.00"),
            "total_tax": D("10.00"),
            "total_net": D("990.00"),
            "total_employer_contribution": D("0.00"),
        })

        build(employee([basic(1000), tax(10)]), run=run)

    def test_line_not_calculated_fails(self):
        with self.assertRaises(PayrollAccountingError) as caught:
            build(employee([basic(1)], status="error"))

        self.assertEqual(caught.exception.error_code, "line_not_calculated")

    def test_company_mismatch_fails(self):
        for company in (2, None):
            with self.subTest(company):
                with self.assertRaises(PayrollAccountingError) as caught:
                    build(employee([basic(1)], company=company))

                self.assertEqual(caught.exception.error_code, "company_mismatch")

    def test_empty_run_fails(self):
        with self.assertRaises(PayrollAccountingError):
            build()


class DeterminismTest(SimpleTestCase):
    def employees(self):
        return [
            employee([bpjs(10, program="JKN"), basic(900), tax(5)], dims=DIMS_B),
            employee([allowance(50), basic(1000), bpjs(12, program="JHT")], dims=DIMS_A),
        ]

    def test_order_is_canonical_regardless_of_input_order(self):
        forward = build(*self.employees())
        backward = build(*reversed(self.employees()))

        self.assertEqual(forward["components"], backward["components"])
        keys = [
            (row["semantic"], row["detail"], row["program"],
             *(row[name] for name in DIMENSIONS))
            for row in forward["components"]
        ]
        self.assertEqual(keys, sorted(keys, key=accounting.sort_key))

    def test_digest_is_stable(self):
        first = build(*self.employees())
        second = build(*reversed(self.employees()))

        self.assertEqual(first["digest"], second["digest"])
        self.assertRegex(first["digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(first["digest"], accounting.digest(first))

    def test_digest_formula(self):
        payload = build(*self.employees())
        import hashlib

        content = {key: payload[key] for key in
                   ("schema", "run", "currency", "control", "components")}
        expected = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        self.assertEqual(payload["digest"], expected)

    def test_amount_change_changes_digest(self):
        base = build(employee([basic(1000)]))
        changed = build(employee([basic("1000.01")]))

        self.assertNotEqual(base["digest"], changed["digest"])

    def test_dimension_change_changes_digest(self):
        base = build(employee([basic(1000)], dims=DIMS_A))
        changed = build(employee([basic(1000)], dims=DIMS_B))

        self.assertNotEqual(base["digest"], changed["digest"])

    def test_run_identity_change_changes_digest(self):
        base = build(employee([basic(1000)]))
        changed = build(
            employee([basic(1000)]),
            run=replace(RUN, period_end=date(2026, 8, 30)),
        )

        self.assertNotEqual(base["digest"], changed["digest"])


class PrivacyTest(SimpleTestCase):
    FORBIDDEN_KEYS = {
        "employee", "employee_id", "employee_number", "name", "full_name",
        "bank", "bank_account", "account_number", "npwp", "tax_number",
        "bpjs_number", "membership_number", "nik", "code",
    }

    def payload(self):
        return build(
            employee([basic(1000), bpjs(10, employer=True), tax(5)]),
            employee([basic(2000), template_deduction(20)], dims=DIMS_B),
        )

    def walk_keys(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from self.walk_keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from self.walk_keys(item)

    def test_no_identifying_keys(self):
        keys = set(self.walk_keys(self.payload()))

        self.assertFalse(keys & self.FORBIDDEN_KEYS, keys & self.FORBIDDEN_KEYS)

    def test_no_individual_amounts_when_aggregated(self):
        payload = build(
            employee([basic(1000)]),
            employee([basic(2000)]),
        )
        text = json.dumps(payload)

        self.assertNotIn('"1000.00"', text)
        self.assertNotIn('"2000.00"', text)


class SourceGuardTest(SimpleTestCase):
    """Payroll tidak mengenal akun maupun model Finance."""

    source = Path(accounting.__file__).read_text(encoding="utf-8")

    def test_no_account_code_literals(self):
        literals = [
            token.string
            for token in tokenize.generate_tokens(io.StringIO(self.source).readline)
            if token.type == tokenize.STRING
        ]
        offenders = [
            text for text in literals
            if re.fullmatch(r"[rbuRBU]?['\"]\d{3,}['\"]", text)
        ]

        self.assertEqual(offenders, [])

        for code in ("6100", "6110", "6120", "2130", "2140", "2150", "2160"):
            self.assertNotIn(code, self.source)

    def test_no_finance_imports_or_journal_writes(self):
        tree = ast.parse(self.source)
        modules = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)

        self.assertFalse([name for name in modules if "finance" in name], modules)

        for needle in (
            "apps.finance", "AccountMapping", "finance.Account",
            "JournalLine", "Journal(", "AccountingEvent",
        ):
            self.assertNotIn(needle, self.source)
