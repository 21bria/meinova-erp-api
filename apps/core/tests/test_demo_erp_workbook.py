"""
Kontrak dataset Meinova ERP yang **tidak butuh basis data**: pembacaan
workbook, pemetaan murni, dan pagar perintah yang harus menolak sebelum
satu kueri pun jalan.

Yang butuh tenant ada di `test_demo_erp_contract`.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.core.services.demo_erp import constants, mapping
from apps.core.services.demo_erp.planner import PAYROLL_FIELDS, planned_people
from apps.core.services.demo_erp.workbook import WorkbookError, load_workbook


SOURCE = Path(settings.BASE_DIR) / constants.DEFAULT_SOURCE
PACKAGE = Path(settings.BASE_DIR) / "apps/core/services/demo_erp"
COMMAND = Path(settings.BASE_DIR) / "apps/core/management/commands/seed_demo_erp.py"


def rewrite_workbook(target: Path, replacements: dict[str, str]) -> Path:
    """Salinan workbook dengan teks XML diganti — untuk workbook rusak."""
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(target, "w") as out:
        for item in source.infolist():
            payload = source.read(item.filename)

            if item.filename.startswith("xl/") and item.filename.endswith(".xml"):
                text = payload.decode("utf-8")

                for old, new in replacements.items():
                    text = text.replace(old, new)

                payload = text.encode("utf-8")

            out.writestr(item, payload)

    return target


class WorkbookParsingTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = load_workbook(SOURCE)

    def test_reads_every_sheet(self):
        wb = self.workbook

        self.assertEqual(len(wb.companies), 3)
        self.assertEqual(len(wb.employees), 40)
        self.assertEqual(wb.employee_ids, [f"EMP{i:03d}" for i in range(1, 41)])
        self.assertEqual(len(wb.contracts), 12)
        self.assertEqual(len(wb.roster_assignments), 40)
        self.assertEqual(len(wb.leaves), 10)
        self.assertEqual(len(wb.attendance), 12)
        self.assertEqual(len(wb.payroll), 12)
        self.assertEqual(len(wb.finance_postings), 6)
        self.assertEqual(len(wb.scopes), 9)

    def test_hr_hierarchy_is_read_as_written(self):
        expected = {
            "EMP002": "EMP001",
            "EMP040": "EMP002",
            "EMP020": "EMP002",
            "EMP017": "EMP040",
            "EMP013": "EMP040",
            "EMP014": "EMP013",
            "EMP037": "EMP020",
            "EMP031": "EMP017",
        }

        for employee_id, manager in expected.items():
            with self.subTest(employee_id):
                self.assertEqual(self.workbook.employee(employee_id).reports_to, manager)

    def test_known_workbook_defects_are_findings_not_fixes(self):
        findings = "\n".join(self.workbook.findings)

        self.assertIn("Net Pay 8050000", findings)
        self.assertIn("melapor lintas company", findings)
        # Nilai workbook tidak diubah pembaca.
        row = next(r for r in self.workbook.payroll if r.employee_id == "EMP009")
        self.assertEqual(int(row.net_pay), 8050000)

    def test_same_file_same_fingerprint(self):
        self.assertEqual(load_workbook(SOURCE).sha256, self.workbook.sha256)


class MalformedWorkbookTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_rejected(self, replacements, message):
        path = rewrite_workbook(self.tmp / "broken.xlsx", replacements)

        with self.assertRaisesRegex(WorkbookError, message):
            load_workbook(path)

    def test_missing_sheet(self):
        self.assert_rejected({'name="12_Role_Data_Scope"': 'name="12_Other"'}, "12_Role_Data_Scope")

    def test_changed_header(self):
        self.assert_rejected({">Reports To<": ">Manager<"}, "kepala kolom")

    def test_duplicate_employee_id(self):
        self.assert_rejected({"EMP040<": "EMP039<"}, "ganda")

    def test_unreadable_date(self):
        self.assert_rejected({">2026-03-28<": ">28/03/2026<"}, "tanggal tidak terbaca")

    def test_not_an_xlsx(self):
        path = self.tmp / "plain.xlsx"
        path.write_text("bukan zip")

        with self.assertRaisesRegex(WorkbookError, "bukan berkas .xlsx"):
            load_workbook(path)

    def test_missing_file(self):
        with self.assertRaisesRegex(WorkbookError, "tidak ditemukan"):
            load_workbook(self.tmp / "none.xlsx")


class CommandGuardTests(SimpleTestCase):
    """Penolakan yang terjadi sebelum kueri pertama."""

    def call(self, *args):
        call_command("seed_demo_erp", *args, stdout=open("/dev/null", "w"))

    def test_mode_is_mandatory(self):
        with self.assertRaisesRegex(CommandError, "--dry-run atau --apply"):
            self.call("--tenant=demo", f"--source={SOURCE}")

    def test_apply_refuses_while_notification_email_is_on(self):
        with self.settings(NOTIFICATION_EMAIL_ENABLED=True):
            with self.assertRaisesRegex(CommandError, "NOTIFICATION_EMAIL_ENABLED=False"):
                self.call("--tenant=demo", f"--source={SOURCE}", "--apply")

    def test_reset_apply_is_enabled_but_still_guarded(self):
        """DEMO-1C: --reset --apply diizinkan, tapi pagar surel tetap berlaku."""
        with self.settings(NOTIFICATION_EMAIL_ENABLED=True):
            with self.assertRaisesRegex(CommandError, "NOTIFICATION_EMAIL_ENABLED=False"):
                self.call("--tenant=demo", f"--source={SOURCE}", "--apply", "--reset")

    def test_rehearse_needs_apply(self):
        with self.assertRaisesRegex(CommandError, "--rehearse hanya berarti bersama --apply"):
            self.call("--tenant=demo", f"--source={SOURCE}", "--dry-run", "--rehearse")

    def test_missing_tenant(self):
        with self.assertRaisesRegex(CommandError, "--tenant wajib"):
            self.call(f"--source={SOURCE}", "--dry-run")

    def test_public_schema_is_refused(self):
        with self.assertRaisesRegex(CommandError, "public ditolak"):
            self.call("--tenant=public", f"--source={SOURCE}", "--dry-run")

    def test_tenant_outside_allow_list_is_refused(self):
        with self.assertRaisesRegex(CommandError, "tidak diizinkan"):
            self.call("--tenant=kw-prod", f"--source={SOURCE}", "--dry-run")


class MappingContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = load_workbook(SOURCE)

    def test_ownership_keys_are_deterministic(self):
        first = planned_people(self.workbook)
        second = planned_people(load_workbook(SOURCE))

        self.assertEqual(first, second)

        usernames = [p.username for p in first.values()]
        self.assertEqual(len(usernames), len(set(usernames)))

        for employee_id, person in first.items():
            with self.subTest(employee_id):
                self.assertRegex(employee_id, constants.EMPLOYEE_NUMBER_PATTERN)
                self.assertTrue(person.username.startswith(constants.USERNAME_PREFIX))
                self.assertTrue(
                    mapping.employee_note(person.row).startswith(f"[DEMO-ERP:{employee_id}]")
                )

    def test_owned_and_protected_company_codes_are_disjoint(self):
        self.assertFalse(
            set(constants.OWNED_COMPANY_CODES) & set(constants.PROTECTED_COMPANY_CODES)
        )
        self.assertEqual(
            {row.code for row in self.workbook.companies},
            set(constants.OWNED_COMPANY_CODES),
        )

    def test_position_does_not_create_application_roles(self):
        """Position ≠ Role: role hanya dari lembar 12, dan hanya kode yang ada."""
        grants = mapping.scope_grants(self.workbook)
        canonical = {
            "EMPLOYEE", "HR-MANAGER", "HR-ADMIN", "FINANCE-MANAGER", "KTT",
            "ADMIN-DEPARTMENT", "BOD", "EXECUTIVE",
        }
        granted = {g.role for gs in grants.values() for g in gs} | {mapping.BASE_GRANT.role}

        self.assertLessEqual(granted, canonical)

        positions = {row.position.upper() for row in self.workbook.employees}
        self.assertFalse(granted & positions)

        scoped = {row.employee_id for row in self.workbook.scopes}
        self.assertLessEqual(set(grants), scoped)

        # Mengganti nama jabatan tidak mengubah role siapa pun.
        renamed = dataclasses.replace(
            self.workbook,
            employees=[
                dataclasses.replace(row, position="System Administrator")
                for row in self.workbook.employees
            ],
        )
        self.assertEqual(mapping.scope_grants(renamed), grants)

    def test_locality_is_not_a_classification(self):
        row = self.workbook.employee("EMP009")
        other = dataclasses.replace(row, locality="Non-local")

        self.assertEqual(mapping.employee_group(row), mapping.employee_group(other))
        self.assertEqual(mapping.job_level(row), mapping.job_level(other))
        self.assertNotIn(mapping.employee_group(other), {"EXPAT", "LOCAL"})

        for model in apps.get_models():
            with self.subTest(model._meta.label):
                self.assertNotIn(
                    "locality",
                    {f.name for f in model._meta.get_fields()},
                )

    def test_job_levels_map_to_existing_codes_only(self):
        existing = {"STAFF", "SUP", "SPV", "MGR", "GM", "DIR"}

        for row in self.workbook.employees:
            with self.subTest(row.employee_id):
                self.assertIn(mapping.job_level(row), existing)

        self.assertEqual(mapping.job_level(self.workbook.employee("EMP001")), "DIR")
        self.assertEqual(mapping.job_level(self.workbook.employee("EMP002")), "GM")
        self.assertEqual(mapping.job_level(self.workbook.employee("EMP006")), "MGR")

    def test_roster_codes_keep_canonical_semantics(self):
        self.assertEqual(
            mapping.SCHEDULE["RST-6-2"].roster_policy, "ROSTER-SAGEA-MINE-6-2-2-SHIFT"
        )
        self.assertEqual(mapping.SCHEDULE["RST-8-2"].roster_policy, "ROSTER-SAGEA MINE-8-2")
        self.assertIn("42 hari kerja / 14", mapping.SCHEDULE["RST-6-2"].semantics)
        self.assertIn("56 hari kerja / 14", mapping.SCHEDULE["RST-8-2"].semantics)

        # Locality tidak memilih roster: dua pegawai lokal, dua policy berbeda.
        by_employee = {r.employee_id: r.policy_code for r in self.workbook.roster_assignments}
        local = [r.employee_id for r in self.workbook.employees if r.locality == "Local"]
        self.assertGreater(len({by_employee[e] for e in local}), 1)

    def test_substitutes_keep_unit_and_manager(self):
        """Pengganti B4 memperagakan alur yang sama: unit, atasan, company sama."""
        for request_id, (substitute, reason) in mapping.SCENARIO_SUBSTITUTES.items():
            with self.subTest(request_id):
                row = next(r for r in self.workbook.leaves if r.request_id == request_id)
                original = self.workbook.employee(row.employee_id)
                other = self.workbook.employee(substitute)

                self.assertEqual(mapping.scenario_employee(row), substitute)
                # Berhak cuti tahunan menurut aturan Join Date DEMO-1B: tetap, atau
                # kontrak tanpa masa kontrak di dataset (masuk 2025-01-01).
                dated = {c.employee_id for c in self.workbook.contracts}
                self.assertTrue(other.employment == "Permanent" or substitute not in dated)
                self.assertEqual(
                    (other.company, other.department, other.location, other.reports_to),
                    (original.company, original.department, original.location, original.reports_to),
                )
                self.assertTrue(reason)

    def test_payroll_results_are_engine_outputs(self):
        for name, klass in PAYROLL_FIELDS.items():
            with self.subTest(name):
                if name == "Basic Salary":
                    self.assertTrue(klass.startswith("SUMBER"))
                else:
                    self.assertTrue(klass.startswith("HASIL MESIN"))


class SalaryMatrixTests(SimpleTestCase):
    """DEMO-1C: gaji seluruh pegawai, deterministik, jangkar workbook menang."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = load_workbook(SOURCE)

    def test_every_employee_gets_a_salary_and_anchors_win(self):
        anchors = {row.employee_id: row.basic_salary for row in self.workbook.payroll}

        for row in self.workbook.employees:
            with self.subTest(row.employee_id):
                amount, basis = mapping.basic_salary(row, self.workbook)

                self.assertGreater(amount, 0)

                if row.employee_id in anchors:
                    self.assertEqual(amount, anchors[row.employee_id])
                    self.assertIn("workbook", basis)
                else:
                    self.assertIn("matriks", basis)

    def test_matrix_is_deterministic_and_ordered_by_level(self):
        first = [mapping.basic_salary(r, self.workbook) for r in self.workbook.employees]
        second = [mapping.basic_salary(r, load_workbook(SOURCE)) for r in self.workbook.employees]

        self.assertEqual(first, second)

        m = {tier: amount for tier, (amount, _) in mapping.SALARY_MATRIX.items()}
        self.assertLess(m["STAFF/Non-Staff"], m["STAFF/Staff"])
        self.assertLess(m["STAFF/Staff"], m["STAFF/Officer"])
        self.assertLessEqual(m["STAFF/Officer"], m["SUP"])
        self.assertLess(m["SUP"], m["MGR"])
        self.assertLess(m["MGR"], m["GM"])
        self.assertLess(m["GM"], m["DIR"])

    def test_matrix_anchors_match_workbook(self):
        anchors = {row.employee_id: row.basic_salary for row in self.workbook.payroll}

        self.assertEqual(mapping.SALARY_MATRIX["SUP"][0], anchors["EMP013"])
        self.assertEqual(mapping.SALARY_MATRIX["STAFF/Officer"][0], anchors["EMP017"])
        self.assertEqual(mapping.SALARY_MATRIX["STAFF/Staff"][0], anchors["EMP030"])
        self.assertEqual(mapping.SALARY_MATRIX["STAFF/Non-Staff"][0], anchors["EMP024"])

    def test_overtime_eligibility_not_widened(self):
        for row in self.workbook.employees:
            with self.subTest(row.employee_id):
                eligible = mapping.overtime_eligible(row)

                if row.ho_site == "HO" or mapping.job_level(row) in ("MGR", "GM", "DIR"):
                    self.assertFalse(eligible)

    def test_showcase_is_the_workbook_payroll_population(self):
        self.assertEqual(
            mapping.SHOWCASE_EMPLOYEES, {row.employee_id for row in self.workbook.payroll}
        )
        self.assertEqual(
            mapping.intentional_absences(self.workbook), {("EMP009", "2026-08"): 1}
        )

    def test_lv001_moves_inside_september(self):
        row = next(r for r in self.workbook.leaves if r.request_id == "LV-001")
        start, end = mapping.scenario_dates(row)

        self.assertEqual((start.month, end.month), (9, 9))
        self.assertEqual((end - start).days + 1, row.days)
        self.assertNotEqual((start, end), (row.start, row.end))


class ApprovedBaselineTests(SimpleTestCase):
    """
    DEMO-1D: keputusan DEMO-1C yang disetujui hidup di sumber seed, bukan
    hanya di database `demo`. Mengubah salah satunya harus disengaja.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = load_workbook(SOURCE)

    def test_population_is_emp001_to_emp040(self):
        self.assertEqual(
            [row.employee_id for row in self.workbook.employees],
            [f"EMP{n:03d}" for n in range(1, 41)],
        )

    def test_approved_substitutes(self):
        self.assertEqual(
            {key: substitute for key, (substitute, _) in mapping.SCENARIO_SUBSTITUTES.items()},
            {"LV-001": "EMP010", "LV-004": "EMP036", "LV-006": "EMP029"},
        )

    def test_approved_lv001_dates(self):
        start, end, _ = mapping.SCENARIO_DATES["LV-001"]

        self.assertEqual((start.isoformat(), end.isoformat()), ("2026-09-09", "2026-09-12"))

    def test_lv008_is_skipped_not_forced(self):
        from apps.core.services.demo_erp.apply import UNSUPPORTED_SCENARIOS

        self.assertEqual(set(UNSUPPORTED_SCENARIOS), {"LV-008"})


class IdentitySourceTests(SimpleTestCase):
    """DEMO-1E: identitas EMP001–EMP040 hidup di sumber seed, deterministik."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = load_workbook(SOURCE)

    def test_identity_table_covers_exactly_the_population(self):
        from apps.core.services.demo_erp import identity

        self.assertEqual(
            [i.employee_id for i in identity.IDENTITIES],
            [f"EMP{n:03d}" for n in range(1, 41)],
        )
        self.assertEqual(set(identity.BY_EMPLOYEE), set(planned_people(self.workbook)))

    def test_seed_source_never_names_legacy_or_trial_employees(self):
        from apps.core.services.demo_erp import identity, reset

        numbers = (
            set(planned_people(self.workbook))
            | set(identity.BY_EMPLOYEE)
            | set(reset.dataset_target().numbers)
            | {row.reports_to for row in self.workbook.employees if row.reports_to}
        )

        for number in numbers:
            with self.subTest(number):
                self.assertRegex(number, constants.EMPLOYEE_NUMBER_PATTERN)
                self.assertFalse(number.startswith(constants.PROTECTED_EMPLOYEE_PREFIXES))

    def test_identity_is_deterministic(self):
        import importlib

        from apps.core.services.demo_erp import identity

        def render(module):
            return [
                (i.nik, i.tax_number, i.passport_number, i.mobile, i.phone, i.emergency_phone,
                 i.account_number, i.bpjs_kesehatan, i.bpjs_ketenagakerjaan,
                 module.derived_tax_status(i),
                 (i.emergency_contact.relationship, i.emergency_contact.full_name))
                for i in module.IDENTITIES
            ]

        first = render(identity)
        self.assertEqual(first, render(importlib.reload(identity)))

    def test_nik_is_unique_synthetic_and_encodes_birth(self):
        from apps.core.services.demo_erp import identity

        niks = [i.nik for i in identity.IDENTITIES]
        self.assertEqual(len(set(niks)), 40)

        for i in identity.IDENTITIES:
            with self.subTest(i.employee_id):
                self.assertRegex(i.nik, r"^99\d{14}$")  # provinsi 99 tidak ada
                day = int(i.nik[6:8])
                self.assertEqual(day - (40 if i.gender == "F" else 0), i.birth_date.day)
                self.assertEqual(i.nik[8:12], i.birth_date.strftime("%m%y"))
                self.assertEqual(i.tax_number, i.nik)

    def test_contact_and_account_identifiers_are_unique(self):
        from apps.core.services.demo_erp import identity

        rows = {row.employee_id: row for row in self.workbook.employees}
        columns = {
            "work_email": [mapping.user_email(rows[i.employee_id]) for i in identity.IDENTITIES],
            "personal_email": [
                i.personal_email(rows[i.employee_id].first_name, rows[i.employee_id].last_name)
                for i in identity.IDENTITIES
            ],
            "mobile": [i.mobile for i in identity.IDENTITIES],
            "account": [(i.bank, i.account_number) for i in identity.IDENTITIES],
            "bpjs_kesehatan": [i.bpjs_kesehatan for i in identity.IDENTITIES],
            "bpjs_ketenagakerjaan": [i.bpjs_ketenagakerjaan for i in identity.IDENTITIES],
        }

        for name, values in columns.items():
            with self.subTest(name):
                self.assertEqual(len(set(values)), 40)

        for email in columns["personal_email"]:
            self.assertTrue(email.endswith(".example"), email)

    def test_login_email_is_a_unique_readable_inbox_alias(self):
        """DEMO-1E: User.email = work_email = brya.seran+<alias>@gmail.com, alias tetap."""
        from apps.hr.seeds.demo_accounts import DEMO_EMAIL_ALIASES, demo_address

        rows = {row.employee_id: row for row in self.workbook.employees}
        aliases = mapping.LOGIN_ALIASES

        self.assertEqual(sorted(aliases), [f"EMP{n:03d}" for n in range(1, 41)])
        self.assertEqual(len(set(aliases.values())), 40)

        for employee_id, alias in aliases.items():
            with self.subTest(employee_id):
                self.assertRegex(alias, r"^[a-z]+(\.[a-z0-9]+)?$")
                address = mapping.user_email(rows[employee_id])
                self.assertEqual(address, demo_address(alias))
                self.assertRegex(address, r"^brya\.seran\+[a-z0-9.]+@gmail\.com$")
                self.assertFalse(address.endswith(constants.COMPANY_EMAIL_DOMAIN))

        # Alias HR-DEMO lama yang juga dipakai di sini — akun lamanya sudah
        # dibuang dari `demo` (DEMO-1D); dipatok supaya tumpang tindih baru
        # tidak masuk diam-diam.
        self.assertEqual(
            set(aliases.values()) & set(DEMO_EMAIL_ALIASES.values()),
            {"supervisor", "ktt", "surveyor"},
        )

    def test_hierarchy_is_a_single_tree(self):
        rows = {row.employee_id: row for row in self.workbook.employees}
        roots = [e for e, row in rows.items() if not row.reports_to]

        self.assertEqual(roots, ["EMP001"])

        for employee_id in rows:
            seen, current = set(), employee_id
            while rows[current].reports_to:
                self.assertNotIn(current, seen, f"siklus di {employee_id}")
                seen.add(current)
                current = rows[current].reports_to
                self.assertIn(current, rows)

    def test_domicile_follows_workbook_locality(self):
        from apps.core.services.demo_erp import identity

        for row in self.workbook.employees:
            i = identity.BY_EMPLOYEE[row.employee_id]
            with self.subTest(row.employee_id):
                if row.ho_site == "HO":
                    self.assertIn(i.city, {"31.71", "31.73", "31.74", "31.75", "32.75", "32.76", "36.74"})
                elif row.locality == "Local":
                    self.assertEqual(i.city, "82.02")  # Halmahera Tengah
                else:
                    self.assertNotEqual(i.province, "82")

    def test_emergency_contact_is_a_recorded_relative(self):
        from apps.core.services.demo_erp import identity

        for i in identity.IDENTITIES:
            with self.subTest(i.employee_id):
                self.assertIn(i.emergency_contact, i.relatives)
                self.assertEqual(
                    i.emergency_contact.relationship, "SPOUSE" if i.marital_status == "M" else "PARENT",
                )

    def test_payroll_tax_status_stays_tk0_until_approved(self):
        """DEMO-1E §E: status turunan dilaporkan, tidak diterapkan diam-diam."""
        from apps.core.services.demo_erp import apply, identity

        self.assertEqual(apply.TAX_STATUS, "TK/0")
        derived = {i.employee_id: identity.derived_tax_status(i) for i in identity.IDENTITIES}
        self.assertEqual(sum(1 for v in derived.values() if v != "TK/0"), 18)
        self.assertTrue(all(v == "TK/0" for e, v in derived.items() if identity.BY_EMPLOYEE[e].gender == "F"))


class CanonicalCompanySetTests(SimpleTestCase):
    """DEMO-1F: peragaan manajemen = persis GRP/MMN/MIN; roster milik MMN."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = load_workbook(SOURCE)

    def test_seed_dataset_builds_exactly_the_canonical_companies(self):
        from apps.core.services.demo_erp.legacy_company_cleanup import LEGACY_COMPANY_CODES
        from apps.core.services.demo_erp.organization import build_dataset

        dataset = build_dataset(self.workbook)
        codes = sorted(row["code"] for row in dataset.companies)

        self.assertEqual(codes, sorted(constants.OWNED_COMPANY_CODES))
        self.assertEqual(sorted(constants.OWNED_COMPANY_CODES), ["GRP", "MIN", "MMN"])
        # Baris dict memakai kunci "company"; baris tuple (divisi, department,
        # cost center) menaruh kode company di indeks 0.
        sections = {
            "branches": dataset.branches, "locations": dataset.locations,
            "divisions": dataset.divisions, "departments": dataset.departments,
            "positions": dataset.positions, "cost_centers": dataset.cost_centers,
        }
        for name, rows in sections.items():
            with self.subTest(name):
                self.assertTrue(rows)
                companies = {row["company"] if isinstance(row, dict) else row[0] for row in rows}
                self.assertLessEqual(companies, set(constants.OWNED_COMPANY_CODES))
                self.assertFalse(companies & set(LEGACY_COMPANY_CODES))

    def test_seed_source_does_not_import_the_legacy_organization_seed(self):
        for path in sorted(PACKAGE.glob("*.py")) + [COMMAND]:
            with self.subTest(path.name):
                text = path.read_text()
                self.assertNotIn("seeds.demo.organization", text)
                self.assertNotIn("seed_demo_organization", text)

    def test_mmn_roster_policies_pin_the_previous_mmr_semantics(self):
        from apps.core.services.demo_erp import roster_policy as source

        self.assertEqual((source.COMPANY, source.LOCATION), ("MMN", "SAGEA-MINE"))
        self.assertEqual(
            [(p.code, p.cycle_work_days, p.cycle_off_days, p.is_default) for p in source.POLICIES],
            [("ROSTER-SAGEA-MINE-6-2-2-SHIFT", 42, 14, True), ("ROSTER-SAGEA MINE-8-2", 56, 14, False)],
        )
        self.assertEqual(source.ROTATION, ((1, "SHIFT-1", 7), (2, "SHIFT-3", 7), (3, "SHIFT-2", 7)))
        self.assertEqual(source.URGENT_PURPOSES, ("SICK", "DUTY", "DEMOB"))
        self.assertEqual(
            {k: source.COMMON[k] for k in (
                "roster_start_basis", "default_travel_out_days", "default_travel_in_days",
                "travel_day_mode", "travel_in_counts_as_roster_day", "credit_enabled", "credit_rounding",
            )},
            {"roster_start_basis": "site_arrival", "default_travel_out_days": 1, "default_travel_in_days": 1,
             "travel_day_mode": "fixed", "travel_in_counts_as_roster_day": True, "credit_enabled": True,
             "credit_rounding": "floor"},
        )
        self.assertEqual([len(p.travel_days) for p in source.POLICIES], [6, 2])

    def test_every_roster_employee_resolves_an_mmn_policy_from_source(self):
        from apps.core.services.demo_erp import roster_policy as source

        rostered = [
            row for row in self.workbook.roster_assignments
            if mapping.SCHEDULE[row.policy_code].roster_policy
        ]

        self.assertEqual(len(rostered), 16)
        for row in rostered:
            with self.subTest(row.employee_id):
                self.assertIn(mapping.SCHEDULE[row.policy_code].roster_policy, source.BY_CODE)
                self.assertEqual(self.workbook.employee(row.employee_id).company, source.COMPANY)


class NoHardcodedAccountTests(SimpleTestCase):
    def test_demo_seed_mentions_no_gl_account_code(self):
        from apps.finance.seeds.chart_of_accounts import TEMPLATE

        account_codes = {row[0] for row in TEMPLATE}
        sources = sorted(PACKAGE.glob("*.py")) + [COMMAND]

        for path in sources:
            with self.subTest(path.name):
                # Tahun di literal tanggal (tanggal lahir identitas) bukan kode akun.
                text = re.sub(r"date\(\d{4},", "date(", path.read_text())
                tokens = set(re.findall(r"(?<!\d)\d{4}(?!\d)", text))
                self.assertFalse(
                    tokens & account_codes,
                    f"{path.name} menyebut kode akun {sorted(tokens & account_codes)}",
                )
