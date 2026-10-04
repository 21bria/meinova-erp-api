"""Cetakan rencana untuk terminal. Isinya sama dengan `Plan.as_dict()`."""

from __future__ import annotations

from .guards import EXCLUDED_DIGEST_COLUMNS
from .planner import Plan


def _row(values: dict, keys: tuple[str, ...]) -> str:
    return " | ".join(str(values.get(key, "")) for key in keys)


TABLES = {
    "organization.company": ("code", "name", "type", "parent", "ownership_marker", "status"),
    "organization.location": ("company", "code", "name", "type", "status"),
    "organization.division": ("company", "location", "code", "name", "status"),
    "organization.department": ("company", "location", "division", "code", "name", "status"),
    "organization.cost_center": ("company", "department", "code", "status"),
    "organization.position": (
        "company", "code", "name", "department", "job_level", "job_category",
        "is_manager", "reports_to", "headcount", "status",
    ),
    "organization.excluded": ("company", "code", "reason"),
    "employees": (
        "employee_number", "company", "location", "department", "cost_center", "position",
        "job_level", "workbook_level", "employee_group", "employment_type",
        "contract_end", "reports_to", "username", "status",
    ),
    "schedule.mapping": (
        "workbook_code", "roster_policy", "cycle", "policy_owner", "rotation",
        "working_calendar", "shift", "semantics",
    ),
    "schedule.assignment": (
        "employee_number", "workbook_code", "roster_policy", "roster_cycle_start",
        "working_calendar", "shift", "employee_group",
    ),
    "contracts": (
        "employee_number", "contract_end", "days_at_reference", "workbook_alert",
        "erp_report_bucket",
    ),
    "attendance.fields": ("field", "class"),
    "attendance.generation": ("window", "external_id_prefix", "raw_tap_batch", "path", "note"),
    "payroll.fields": ("field", "class"),
    "payroll.salary_matrix": ("tier", "basic_salary", "basis"),
    "payroll.assignment": (
        "employee_number", "position", "job_level", "company", "basic_salary", "payroll_group",
        "allowance_template", "deduction_template", "overtime_eligible", "overtime_group",
        "salary_basis",
    ),
    "payroll.run": ("business_key", "note_marker", "stops_at", "predicted_approvers"),
    "finance.bootstrap": (
        "company", "chart_of_accounts", "fiscal_year", "account_mappings",
        "accounting_policy",
    ),
    "finance.expectation": (
        "period", "company", "workbook_semantic", "mapping_keys", "workbook_status",
    ),
    "finance.bootstrap_scope": ("excluded_step", "reason", "why_mni_mmr_mls_untouched"),
    "organization.reference_side_effects": ("identical_rows_reasserted", "value_changes"),
    "reset.scope": ("owned_companies", "owned_employee_count", "protected_prefixes"),
}


def render(plan: Plan, *, digest: str) -> list[str]:
    lines = [
        "=" * 72,
        "SEED DEMO ERP — RENCANA (mode kering, transaksi READ ONLY)",
        "=" * 72,
        f"Tenant        : {plan.tenant}",
        f"Sumber        : {plan.source}",
        f"Sumber sha256 : {plan.source_sha256}",
        f"Reset diminta : {'ya' if plan.reset else 'tidak'}",
        f"Rencana sha256: {digest}",
        "",
    ]

    for section, keys in TABLES.items():
        rows = plan.sections.get(section, [])

        if not rows:
            continue

        lines.append(f"## {section} ({len(rows)})")
        lines.append("   " + " | ".join(keys))

        for row in rows:
            lines.append("   " + _row(row, keys))

        lines.append("")

    lines.append(f"## access ({len(plan.sections.get('access', []))})")

    for row in plan.sections.get("access", []):
        grants = "; ".join(
            f"{g['role']}[{g['mode']}{'@' + g['level'] if g['level'] else ''}"
            f"{' ' + ','.join(g['authorities']) if g['authorities'] else ''}]"
            for g in row["grants"]
        )
        lines.append(f"   {row['employee_number']} {row['username']:<20} {grants}")

    lines.append("")
    lines.append(f"## leave ({len(plan.sections.get('leave', []))})")

    for row in plan.sections.get("leave", []):
        lines.append(
            f"   {row['scenario_key']} {row['employee_number']} {row['model']}:{row['type']} "
            f"{row['start']}..{row['end']} {row['workbook_status']}→{row['erp_status']} "
            f"def={row['definition']} supported={row['supported']}"
        )
        lines.append(f"      workbook : {row['workbook_route']}")

        for step in row["predicted_route"]:
            lines.append(
                f"      #{step['sequence']} {step['type']}"
                f"{'/' + step['role'] if step['role'] else ''}@{step['scope']} "
                f"→ {','.join(step['approvers']) or '-'} [{step['status']}; {step['via']}]"
            )

        for issue in row["issues"]:
            lines.append(f"      ! {issue}")

    lines.append("")
    lines.append("## reset.owned_rows")

    for row in plan.sections.get("reset.scope", []):
        for name, count in row["owned_rows"].items():
            lines.append(f"   {name:<28} {count}")

    lines.append("")
    lines.append(
        "## protected fingerprints — sha256(json.dumps(list(QS.order_by('pk')"
        ".values_list(*kolom)), default=str, sort_keys=True)); kolom tanpa "
        f"{', '.join(sorted(EXCLUDED_DIGEST_COLUMNS))}"
    )

    for name, value in sorted(plan.protected.items()):
        lines.append(f"   {name:<32} {value.count:>7}  {value.sha256}")

    for title, items in (
        ("WORKBOOK FINDINGS", plan.findings),
        ("WARNINGS (keterbatasan diketahui)", plan.warnings),
        ("DECISIONS (butuh persetujuan sebelum DEMO-1B)", plan.decisions),
        ("BLOCKERS", plan.blockers),
    ):
        lines.append("")
        lines.append(f"## {title} ({len(items)})")

        for item in items:
            lines.append(f"   - {item}")

    lines.append("")

    return lines
