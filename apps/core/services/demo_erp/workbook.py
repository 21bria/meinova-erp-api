"""
Pembaca workbook blueprint — **hanya pustaka standar**.

`openpyxl` bukan dependensi proyek ini, dan perencana tidak boleh
menambah dependensi hanya untuk membaca satu berkas. `.xlsx` adalah zip
berisi XML; yang dibutuhkan di sini cuma teks sel, angka, dan tanggal.

Dua jenis masalah dibedakan dengan sengaja:

* **Workbook rusak** (lembar hilang, kepala kolom berubah, tanggal tidak
  terbaca, ID ganda) → `WorkbookError`. Perintah berhenti; tidak ada
  rencana yang disusun di atas sumber yang tidak bisa dipercaya.
* **Isi bisnis yang janggal** (angka ringkasan tidak cocok, total bulan
  tidak genap) → `Workbook.findings`. Dilaporkan, tidak menghentikan,
  karena workbook memang hanya rujukan.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from .constants import EMPLOYEE_NUMBER_PATTERN, REQUIRED_SHEETS


class WorkbookError(Exception):
    """Workbook tidak bisa dipakai sebagai sumber."""


_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_EXCEL_EPOCH = date(1899, 12, 30)


# ======================================================================
# Pembacaan XML mentah
# ======================================================================


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)

    if letters is None:
        raise WorkbookError(f"Referensi sel tidak sah: {reference!r}")

    index = 0

    for char in letters.group(0):
        index = index * 26 + (ord(char) - ord("A") + 1)

    return index - 1


def _read_raw_sheets(path: Path) -> tuple[dict[str, list[list]], str]:
    """`{nama lembar: baris[kolom]}` + sidik jari isi berkas."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise WorkbookError(f"Sumber tidak bisa dibaca: {path} ({exc})") from exc

    digest = hashlib.sha256(payload).hexdigest()

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise WorkbookError(f"Sumber bukan berkas .xlsx: {path}") from exc

    with archive:
        names = set(archive.namelist())

        try:
            workbook_xml = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            rels_xml = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
        except KeyError as exc:
            raise WorkbookError("Struktur .xlsx tidak lengkap.") from exc

        shared: list[str] = []

        if "xl/sharedStrings.xml" in names:
            for item in ElementTree.fromstring(
                archive.read("xl/sharedStrings.xml")
            ).iter(f"{_MAIN}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{_MAIN}t")))

        targets = {}

        for rel in rels_xml.iter(f"{_PKG_REL}Relationship"):
            target = rel.get("Target", "")
            target = target.lstrip("/")

            if not target.startswith("xl/"):
                target = str(PurePosixPath("xl") / target)

            targets[rel.get("Id")] = target

        sheets: dict[str, list[list]] = {}

        for sheet in workbook_xml.iter(f"{_MAIN}sheet"):
            name = sheet.get("name")
            target = targets.get(sheet.get(f"{_REL}id"))

            if not target or target not in names:
                raise WorkbookError(f"Lembar {name!r} menunjuk berkas yang tidak ada.")

            sheets[name] = _read_sheet(
                ElementTree.fromstring(archive.read(target)),
                shared,
            )

    return sheets, digest


def _read_sheet(root, shared: list[str]) -> list[list]:
    rows: list[list] = []

    for row in root.iter(f"{_MAIN}row"):
        values: dict[int, object] = {}

        for cell in row.iter(f"{_MAIN}c"):
            kind = cell.get("t", "n")
            raw = cell.find(f"{_MAIN}v")

            if kind == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{_MAIN}t"))
                value: object = text
            elif raw is None or raw.text is None:
                continue
            elif kind == "s":
                value = shared[int(raw.text)]
            elif kind in ("str", "e"):
                value = raw.text
            elif kind == "b":
                value = raw.text == "1"
            else:
                value = _number(raw.text)

            if isinstance(value, str):
                value = value.strip()

                if value == "":
                    continue

            values[_column_index(cell.get("r", "A1"))] = value

        if not values:
            continue

        width = max(values) + 1
        rows.append([values.get(i) for i in range(width)])

    return rows


def _number(text: str):
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise WorkbookError(f"Angka tidak sah: {text!r}") from exc

    return int(number) if number == number.to_integral_value() else number


# ======================================================================
# Konversi nilai
# ======================================================================


def _as_date(value, where: str) -> date:
    if isinstance(value, int):
        return _EXCEL_EPOCH + timedelta(days=value)

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass

    raise WorkbookError(f"{where}: tanggal tidak terbaca ({value!r}).")


def _as_int(value, where: str) -> int:
    if isinstance(value, int):
        return value

    raise WorkbookError(f"{where}: bilangan bulat diharapkan ({value!r}).")


def _as_money(value, where: str) -> Decimal:
    if isinstance(value, (int, Decimal)):
        return Decimal(value)

    raise WorkbookError(f"{where}: nominal diharapkan ({value!r}).")


def _as_text(value, where: str, *, required: bool = True) -> str:
    if value is None or value == "":
        if required:
            raise WorkbookError(f"{where}: kolom wajib kosong.")

        return ""

    return str(value).strip()


def _as_ref(value) -> str | None:
    """`-` dan kosong = tidak ada rujukan."""
    text = "" if value is None else str(value).strip()

    return None if text in ("", "-") else text


# ======================================================================
# Baris bertipe
# ======================================================================


@dataclass(frozen=True)
class CompanyRow:
    code: str
    name: str
    entity_type: str
    parent: str | None
    coverage: str
    business_scope: str
    status: str


@dataclass(frozen=True)
class OrgUnitRow:
    company: str
    code: str
    name: str
    location: str
    reports_to_unit: str | None
    head_role: str
    ho_site: str


@dataclass(frozen=True)
class EmployeeRow:
    employee_id: str
    name: str
    company: str
    department: str
    location: str
    position: str
    level: str
    employment: str
    ho_site: str
    locality: str
    reports_to: str | None
    status: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    @property
    def last_name(self) -> str:
        return " ".join(self.name.split()[1:])


@dataclass(frozen=True)
class ContractRow:
    employee_id: str
    name: str
    employment: str
    start: date
    end: date
    alert: str
    action_route: str
    expected_action: str


@dataclass(frozen=True)
class CalendarPolicyRow:
    code: str
    name: str
    applies_to: str
    pattern: str
    start: str
    end: str
    off_pattern: str
    use_case: str


@dataclass(frozen=True)
class RosterAssignmentRow:
    employee_id: str
    policy_code: str
    effective_from: date
    notes: str


@dataclass(frozen=True)
class LeaveRow:
    request_id: str
    employee_id: str
    leave_type: str
    start: date
    end: date
    days: int
    status: str
    approval_route: str
    scenario: str


@dataclass(frozen=True)
class AttendanceRow:
    period: str
    employee_id: str
    ho_site: str
    roster: str
    present: int
    absent: int
    leave_permit: int
    off: int
    ot_hours: int
    night_hours: int
    scenario: str


@dataclass(frozen=True)
class PayrollRow:
    period: str
    employee_id: str
    company: str
    basic_salary: Decimal
    fixed_allowance: Decimal
    overtime: Decimal
    employer_benefit: Decimal
    gross_cost: Decimal
    employee_deduction: Decimal
    net_pay: Decimal
    scenario: str


@dataclass(frozen=True)
class FinancePostingRow:
    period: str
    company: str
    event_type: str
    source: str
    semantic: str
    side: str
    aggregation: str
    status: str


@dataclass(frozen=True)
class ScenarioRow:
    scenario_id: str
    module: str
    action: str
    expected: str
    priority: str


@dataclass(frozen=True)
class ScopeRow:
    employee_id: str
    name: str
    role_position: str
    scope_type: str
    company_scope: tuple[str, ...]
    location_scope: str
    purpose: str


@dataclass
class Workbook:
    source: str
    sha256: str
    summary: dict[str, object]
    companies: list[CompanyRow]
    org_units: list[OrgUnitRow]
    employees: list[EmployeeRow]
    contracts: list[ContractRow]
    calendar_policies: list[CalendarPolicyRow]
    roster_assignments: list[RosterAssignmentRow]
    leaves: list[LeaveRow]
    attendance: list[AttendanceRow]
    payroll: list[PayrollRow]
    finance_postings: list[FinancePostingRow]
    scenarios: list[ScenarioRow]
    scopes: list[ScopeRow]
    findings: list[str] = field(default_factory=list)

    def employee(self, employee_id: str) -> EmployeeRow:
        for row in self.employees:
            if row.employee_id == employee_id:
                return row

        raise KeyError(employee_id)

    @property
    def employee_ids(self) -> list[str]:
        return [row.employee_id for row in self.employees]


# ======================================================================
# Pembacaan per lembar
# ======================================================================


def _table(sheets, name: str, headers: tuple[str, ...]) -> list[list]:
    """Baris data di bawah baris kepala yang **persis** `headers`."""
    rows = sheets.get(name)

    if rows is None:
        raise WorkbookError(f"Lembar {name!r} tidak ada.")

    for index, row in enumerate(rows):
        head = tuple((row + [None] * len(headers))[: len(headers)])

        if head == headers:
            body = []

            for data in rows[index + 1:]:
                data = (data + [None] * len(headers))[: len(headers)]

                if all(value is None for value in data):
                    continue

                body.append(data)

            return body

    raise WorkbookError(
        f"Lembar {name!r}: kepala kolom tidak ditemukan. "
        f"Diharapkan {list(headers)}."
    )


def load_workbook(path: str | Path) -> Workbook:
    path = Path(path)

    if not path.is_file():
        raise WorkbookError(f"Sumber tidak ditemukan: {path}")

    sheets, digest = _read_raw_sheets(path)

    missing = [name for name in REQUIRED_SHEETS if name not in sheets]

    if missing:
        raise WorkbookError(f"Lembar wajib tidak ada: {', '.join(missing)}")

    workbook = Workbook(
        source=str(path),
        sha256=digest,
        summary=_summary(sheets),
        companies=_companies(sheets),
        org_units=_org_units(sheets),
        employees=_employees(sheets),
        contracts=_contracts(sheets),
        calendar_policies=_calendar_policies(sheets),
        roster_assignments=_roster_assignments(sheets),
        leaves=_leaves(sheets),
        attendance=_attendance(sheets),
        payroll=_payroll(sheets),
        finance_postings=_finance_postings(sheets),
        scenarios=_scenarios(sheets),
        scopes=_scopes(sheets),
    )

    validate(workbook)

    return workbook


def _summary(sheets) -> dict[str, object]:
    """Pasangan KPI → nilai. Hanya rujukan; tidak pernah disimpan."""
    result: dict[str, object] = {}

    for row in sheets["00_Demo_Summary"][2:]:
        cells = row + [None] * 8

        for key_index in (3, 5):
            key, value = cells[key_index], cells[key_index + 1]

            if key and value is not None:
                result[str(key)] = value

    return result


def _companies(sheets) -> list[CompanyRow]:
    body = _table(
        sheets,
        "01_Companies",
        ("Code", "Entity Name", "Entity Type", "Parent", "Coverage",
         "Business Scope", "Status"),
    )

    return [
        CompanyRow(
            code=_as_text(r[0], "01_Companies.Code"),
            name=_as_text(r[1], "01_Companies.Entity Name"),
            entity_type=_as_text(r[2], "01_Companies.Entity Type"),
            parent=_as_ref(r[3]),
            coverage=_as_text(r[4], "01_Companies.Coverage", required=False),
            business_scope=_as_text(r[5], "01_Companies.Business Scope", required=False),
            status=_as_text(r[6], "01_Companies.Status"),
        )
        for r in body
    ]


def _org_units(sheets) -> list[OrgUnitRow]:
    body = _table(
        sheets,
        "02_Org_Structure",
        ("Company", "Org Code", "Department / Unit", "Location",
         "Reports To Unit", "Head Role", "HO/Site"),
    )

    return [
        OrgUnitRow(
            company=_as_text(r[0], "02.Company"),
            code=_as_text(r[1], "02.Org Code"),
            name=_as_text(r[2], "02.Department / Unit"),
            location=_as_text(r[3], "02.Location"),
            reports_to_unit=_as_ref(r[4]),
            head_role=_as_text(r[5], "02.Head Role", required=False),
            ho_site=_as_text(r[6], "02.HO/Site"),
        )
        for r in body
    ]


def _employees(sheets) -> list[EmployeeRow]:
    body = _table(
        sheets,
        "03_Employees",
        ("Employee ID", "Name", "Company", "Department", "Location", "Position",
         "Level", "Employment", "HO/Site", "Locality", "Reports To", "Status"),
    )

    rows = []

    for r in body:
        where = f"03_Employees[{r[0]}]"

        rows.append(
            EmployeeRow(
                employee_id=_as_text(r[0], f"{where}.Employee ID"),
                name=_as_text(r[1], f"{where}.Name"),
                company=_as_text(r[2], f"{where}.Company"),
                department=_as_text(r[3], f"{where}.Department"),
                location=_as_text(r[4], f"{where}.Location"),
                position=_as_text(r[5], f"{where}.Position"),
                level=_as_text(r[6], f"{where}.Level"),
                employment=_as_text(r[7], f"{where}.Employment"),
                ho_site=_as_text(r[8], f"{where}.HO/Site"),
                locality=_as_text(r[9], f"{where}.Locality"),
                reports_to=_as_ref(r[10]),
                status=_as_text(r[11], f"{where}.Status"),
            )
        )

    return rows


def _contracts(sheets) -> list[ContractRow]:
    body = _table(
        sheets,
        "04_Contracts_Action",
        ("Employee ID", "Name", "Employment", "Start Date", "End Date",
         "Alert", "Action Route", "Expected Action"),
    )

    return [
        ContractRow(
            employee_id=_as_text(r[0], "04.Employee ID"),
            name=_as_text(r[1], "04.Name"),
            employment=_as_text(r[2], "04.Employment"),
            start=_as_date(r[3], f"04[{r[0]}].Start Date"),
            end=_as_date(r[4], f"04[{r[0]}].End Date"),
            alert=_as_text(r[5], "04.Alert", required=False),
            action_route=_as_text(r[6], "04.Action Route", required=False),
            expected_action=_as_text(r[7], "04.Expected Action", required=False),
        )
        for r in body
    ]


def _calendar_policies(sheets) -> list[CalendarPolicyRow]:
    body = _table(
        sheets,
        "05_Calendar_Roster",
        ("Policy Code", "Policy Name", "Applies To", "Pattern", "Start", "End",
         "Off Pattern", "Use Case"),
    )

    return [
        CalendarPolicyRow(*(_as_text(v, "05", required=False) for v in r))
        for r in body
    ]


def _roster_assignments(sheets) -> list[RosterAssignmentRow]:
    body = _table(
        sheets,
        "06_Roster_Assignment",
        ("Employee ID", "Policy Code", "Effective From", "Notes"),
    )

    return [
        RosterAssignmentRow(
            employee_id=_as_text(r[0], "06.Employee ID"),
            policy_code=_as_text(r[1], f"06[{r[0]}].Policy Code"),
            effective_from=_as_date(r[2], f"06[{r[0]}].Effective From"),
            notes=_as_text(r[3], "06.Notes", required=False),
        )
        for r in body
    ]


def _leaves(sheets) -> list[LeaveRow]:
    body = _table(
        sheets,
        "07_Leave_Workflow",
        ("Request ID", "Employee ID", "Leave Type", "Start", "End", "Days",
         "Status", "Approval Route", "Scenario"),
    )

    return [
        LeaveRow(
            request_id=_as_text(r[0], "07.Request ID"),
            employee_id=_as_text(r[1], f"07[{r[0]}].Employee ID"),
            leave_type=_as_text(r[2], f"07[{r[0]}].Leave Type"),
            start=_as_date(r[3], f"07[{r[0]}].Start"),
            end=_as_date(r[4], f"07[{r[0]}].End"),
            days=_as_int(r[5], f"07[{r[0]}].Days"),
            status=_as_text(r[6], f"07[{r[0]}].Status"),
            approval_route=_as_text(r[7], "07.Approval Route", required=False),
            scenario=_as_text(r[8], "07.Scenario", required=False),
        )
        for r in body
    ]


def _attendance(sheets) -> list[AttendanceRow]:
    body = _table(
        sheets,
        "08_Attendance_2M",
        ("Period", "Employee ID", "HO/Site", "Roster", "Present", "Absent",
         "Leave/Permit", "Off", "OT Hours", "Night Hours", "Scenario"),
    )

    rows = []

    for r in body:
        where = f"08[{r[0]}/{r[1]}]"

        rows.append(
            AttendanceRow(
                period=_as_text(r[0], f"{where}.Period"),
                employee_id=_as_text(r[1], f"{where}.Employee ID"),
                ho_site=_as_text(r[2], f"{where}.HO/Site"),
                roster=_as_text(r[3], f"{where}.Roster"),
                present=_as_int(r[4], f"{where}.Present"),
                absent=_as_int(r[5], f"{where}.Absent"),
                leave_permit=_as_int(r[6], f"{where}.Leave/Permit"),
                off=_as_int(r[7], f"{where}.Off"),
                ot_hours=_as_int(r[8], f"{where}.OT Hours"),
                night_hours=_as_int(r[9], f"{where}.Night Hours"),
                scenario=_as_text(r[10], f"{where}.Scenario", required=False),
            )
        )

    return rows


def _payroll(sheets) -> list[PayrollRow]:
    body = _table(
        sheets,
        "09_Payroll_2M",
        ("Period", "Employee ID", "Company", "Basic Salary", "Fixed Allowance",
         "Overtime", "Employer Benefit", "Gross Cost", "Employee Deduction",
         "Net Pay", "Scenario"),
    )

    rows = []

    for r in body:
        where = f"09[{r[0]}/{r[1]}]"

        rows.append(
            PayrollRow(
                period=_as_text(r[0], f"{where}.Period"),
                employee_id=_as_text(r[1], f"{where}.Employee ID"),
                company=_as_text(r[2], f"{where}.Company"),
                basic_salary=_as_money(r[3], f"{where}.Basic Salary"),
                fixed_allowance=_as_money(r[4], f"{where}.Fixed Allowance"),
                overtime=_as_money(r[5], f"{where}.Overtime"),
                employer_benefit=_as_money(r[6], f"{where}.Employer Benefit"),
                gross_cost=_as_money(r[7], f"{where}.Gross Cost"),
                employee_deduction=_as_money(r[8], f"{where}.Employee Deduction"),
                net_pay=_as_money(r[9], f"{where}.Net Pay"),
                scenario=_as_text(r[10], f"{where}.Scenario", required=False),
            )
        )

    return rows


def _finance_postings(sheets) -> list[FinancePostingRow]:
    body = _table(
        sheets,
        "10_Finance_Posting",
        ("Period", "Company", "Event Type", "Source", "Accounting Semantic",
         "Dr/Cr", "Aggregation / Dimension", "Status"),
    )

    return [
        FinancePostingRow(*(_as_text(v, "10", required=False) for v in r))
        for r in body
    ]


def _scenarios(sheets) -> list[ScenarioRow]:
    body = _table(
        sheets,
        "11_Demo_Test_Scenarios",
        ("Scenario ID", "Module", "Action", "Expected Result", "Priority"),
    )

    return [
        ScenarioRow(*(_as_text(v, "11", required=False) for v in r))
        for r in body
    ]


def _scopes(sheets) -> list[ScopeRow]:
    body = _table(
        sheets,
        "12_Role_Data_Scope",
        ("Employee ID", "Name", "Role / Position", "Scope Type",
         "Company Scope", "Location Scope", "Purpose"),
    )

    return [
        ScopeRow(
            employee_id=_as_text(r[0], "12.Employee ID"),
            name=_as_text(r[1], "12.Name"),
            role_position=_as_text(r[2], "12.Role / Position"),
            scope_type=_as_text(r[3], "12.Scope Type"),
            company_scope=tuple(
                part.strip()
                for part in _as_text(r[4], "12.Company Scope").split(",")
                if part.strip()
            ),
            location_scope=_as_text(r[5], "12.Location Scope", required=False),
            purpose=_as_text(r[6], "12.Purpose", required=False),
        )
        for r in body
    ]


# ======================================================================
# Validasi
# ======================================================================


def validate(workbook: Workbook) -> None:
    """
    Kesalahan struktur → `WorkbookError`; kejanggalan bisnis →
    `workbook.findings`. Aturannya ditulis sebagai pemeriksaan, bukan
    perbaikan: tidak ada nilai workbook yang diubah di sini.
    """
    errors: list[str] = []
    findings = workbook.findings

    ids = workbook.employee_ids
    duplicates = sorted({x for x in ids if ids.count(x) > 1})

    if duplicates:
        errors.append(f"Employee ID ganda: {', '.join(duplicates)}")

    for employee_id in ids:
        if not re.match(EMPLOYEE_NUMBER_PATTERN, employee_id):
            errors.append(f"Employee ID tidak sesuai pola EMP###: {employee_id}")

    known = set(ids)
    company_codes = {row.code for row in workbook.companies}

    for row in workbook.companies:
        if row.parent and row.parent not in company_codes:
            errors.append(f"01: induk {row.parent} untuk {row.code} tidak ada.")

    for row in workbook.employees:
        if row.company not in company_codes:
            errors.append(f"{row.employee_id}: company {row.company} tidak ada di 01.")

        if row.reports_to and row.reports_to not in known:
            errors.append(
                f"{row.employee_id}: Reports To {row.reports_to} tidak ada."
            )

        if row.reports_to == row.employee_id:
            errors.append(f"{row.employee_id}: melapor ke dirinya sendiri.")

    by_id = {row.employee_id: row for row in workbook.employees}

    for row in workbook.employees:
        seen = [row.employee_id]
        current = row

        while current.reports_to and current.reports_to in by_id:
            if current.reports_to in seen:
                errors.append(
                    "Garis pelaporan berputar: "
                    + " → ".join(seen + [current.reports_to])
                )
                break

            seen.append(current.reports_to)
            current = by_id[current.reports_to]

    for label, rows in (
        ("04", workbook.contracts),
        ("06", workbook.roster_assignments),
        ("07", workbook.leaves),
        ("08", workbook.attendance),
        ("09", workbook.payroll),
        ("12", workbook.scopes),
    ):
        for row in rows:
            if row.employee_id not in known:
                errors.append(f"{label}: pegawai {row.employee_id} tidak ada di 03.")

    request_ids = [row.request_id for row in workbook.leaves]

    for request_id in sorted({x for x in request_ids if request_ids.count(x) > 1}):
        errors.append(f"07: Request ID ganda {request_id}")

    for row in workbook.contracts:
        if row.end < row.start:
            errors.append(f"04[{row.employee_id}]: End Date sebelum Start Date.")

    for row in workbook.leaves:
        if row.end < row.start:
            errors.append(f"07[{row.request_id}]: End sebelum Start.")

    policy_codes = {row.code for row in workbook.calendar_policies}

    for row in workbook.roster_assignments:
        if row.policy_code not in policy_codes:
            errors.append(
                f"06[{row.employee_id}]: kode {row.policy_code} tidak ada di 05."
            )

    if errors:
        raise WorkbookError(
            "Workbook tidak lolos validasi:\n  - " + "\n  - ".join(errors)
        )

    _business_findings(workbook, findings, by_id)


def _business_findings(workbook: Workbook, findings: list[str], by_id) -> None:
    for row in workbook.employees:
        manager = by_id.get(row.reports_to) if row.reports_to else None

        if manager and manager.company != row.company:
            findings.append(
                f"{row.employee_id} ({row.company}) melapor lintas company ke "
                f"{manager.employee_id} ({manager.company})."
            )

    summary_employees = workbook.summary.get("Employees")

    if summary_employees is not None and summary_employees != len(workbook.employees):
        findings.append(
            f"00_Demo_Summary menyebut {summary_employees} pegawai; lembar 03 "
            f"berisi {len(workbook.employees)}. Ringkasan diperlakukan rujukan."
        )

    contract_ids = {row.employee_id for row in workbook.contracts}

    for row in workbook.employees:
        if row.employment == "Contract" and row.employee_id not in contract_ids:
            findings.append(
                f"{row.employee_id}: Contract tanpa baris 04 — masa kontrak tidak "
                "diisi (sah menurut model, tidak muncul di laporan kedaluwarsa)."
            )

    for row in workbook.payroll:
        expected_net = (
            row.basic_salary + row.fixed_allowance + row.overtime
            - row.employee_deduction
        )

        if row.net_pay != expected_net:
            findings.append(
                f"09[{row.period}/{row.employee_id}]: Net Pay {row.net_pay} ≠ "
                f"Basic+Allowance+OT−Deduction {expected_net} (selisih "
                f"{row.net_pay - expected_net}, = Employer Benefit). Nilai workbook "
                "rujukan saja; mesin payroll yang menghitung."
            )

    for row in workbook.attendance:
        year, month = (int(part) for part in row.period.split("-"))
        days = (date(year + month // 12, month % 12 + 1, 1) - date(year, month, 1)).days
        total = row.present + row.absent + row.leave_permit + row.off

        if total != days:
            findings.append(
                f"08[{row.period}/{row.employee_id}]: Present+Absent+Leave+Off = "
                f"{total}, bulan itu {days} hari. Angka bulanan diturunkan ERP."
            )
