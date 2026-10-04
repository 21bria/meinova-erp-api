"""
Perencana dataset Meinova ERP — **hanya membaca**.

Menyusun apa yang akan ditulis DEMO-1B, apa yang menghalanginya, dan
keputusan apa yang masih harus diambil manusia. Tidak ada satu pun
tulisan di sini; perintahnya menjalankan perencana di dalam transaksi
PostgreSQL `READ ONLY`, jadi tulisan yang tidak sengaja pun ditolak
database.

Tiga jenis temuan, dan bedanya penting:

* **blocker** — DEMO-1B tidak boleh jalan (kode company terlindung,
  baris asing, role tidak ada, riwayat Finance POSTED saat reset, …).
* **decision** — jalannya ada, tapi pilihan itu milik pemilik bisnis
  (tanggal masuk yang tidak ada di workbook, reset payroll FINALIZED).
* **warning** — keterbatasan yang sudah diketahui dan diterima,
  dilaporkan supaya tidak terbaca sebagai hasil yang salah.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from . import mapping, ownership
from .constants import (
    ATTENDANCE_BATCH,
    ATTENDANCE_EXTERNAL_PREFIX,
    DOCUMENT_NOTE_PREFIX,
    FISCAL_YEAR,
    OWNED_COMPANY_CODES,
    PROTECTED_COMPANY_CODES,
    REFERENCE_DATE,
)
from .guards import Fingerprint, protected_snapshot
from .organization import build_dataset
from .workbook import EmployeeRow, Workbook


# ======================================================================
# Rencana
# ======================================================================


@dataclass
class Plan:
    tenant: str
    source: str
    source_sha256: str
    reset: bool
    sections: dict[str, list[dict]] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    protected: dict[str, Fingerprint] = field(default_factory=dict)

    def add(self, section: str, row: dict) -> None:
        self.sections.setdefault(section, []).append(row)

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["protected"] = {
            name: {"count": value.count, "sha256": value.sha256}
            for name, value in sorted(self.protected.items())
        }

        return payload

    def digest(self) -> str:
        """Sidik jari rencana: sha256 JSON kanonik `as_dict()`."""
        encoded = json.dumps(self.as_dict(), default=str, sort_keys=True).encode()

        return hashlib.sha256(encoded).hexdigest()


# ======================================================================
# Rencana orang (dipakai beberapa bagian)
# ======================================================================


@dataclass(frozen=True)
class PlannedPerson:
    row: EmployeeRow
    company: str
    location: str
    department: str
    position: str
    job_level: str
    group: str
    username: str
    roles: tuple[str, ...]


def planned_people(workbook: Workbook) -> dict[str, PlannedPerson]:
    grants = mapping.scope_grants(workbook)
    people = {}

    for row in workbook.employees:
        roles = [mapping.BASE_GRANT.role] + [g.role for g in grants.get(row.employee_id, [])]

        people[row.employee_id] = PlannedPerson(
            row=row,
            company=row.company,
            location=mapping.location_code(row.location),
            department=mapping.department_code(row),
            position=mapping.position_code(row),
            job_level=mapping.job_level(row),
            group=mapping.employee_group(row),
            username=mapping.username(row),
            roles=tuple(roles),
        )

    return people


# ======================================================================
# Entry
# ======================================================================


def build_plan(workbook: Workbook, *, tenant: str, reset: bool) -> Plan:
    plan = Plan(
        tenant=tenant,
        source=workbook.source,
        source_sha256=workbook.sha256,
        reset=reset,
        findings=list(workbook.findings),
    )

    people = planned_people(workbook)
    report = ownership.inspect()

    for message in report.foreign:
        plan.blockers.append(f"Kepemilikan: {message}")

    _organization(plan, workbook)
    _employees(plan, workbook, people)
    _access(plan, workbook, people)
    _schedules(plan, workbook, people)
    _contracts(plan, workbook)
    _leaves(plan, workbook, people)
    _attendance(plan, workbook)
    _payroll(plan, workbook, people)
    _identity(plan, people)
    _finance(plan, workbook)
    _reset(plan, report)

    plan.protected = protected_snapshot()

    return plan


# ======================================================================
# Organisasi
# ======================================================================


def _organization(plan: Plan, workbook: Workbook) -> None:
    from apps.administration.models import (
        Company,
        CompanyType,
        CostCenter,
        Department,
        Division,
        JobCategory,
        JobLevel,
        Location,
        LocationType,
        Position,
    )
    from apps.administration.models.references.geography import City, Country, Province

    dataset = build_dataset(workbook)

    # DEMO-1F: tenant peragaan manajemen = persis GRP/MMN/MIN. Company lain
    # (termasuk MNI/MMR/MLS yang sudah dibuang) = blocker; yang belum ada
    # dibuat seed sendiri.
    for other in Company.objects.exclude(code__in=OWNED_COMPANY_CODES).order_by("code"):
        plan.blockers.append(
            f"Company non-kanonik {other.code} ({other.name}) ada di tenant — himpunan "
            f"peragaan harus persis {', '.join(OWNED_COMPANY_CODES)}."
        )

    for row in dataset.companies:
        if row["code"] in PROTECTED_COMPANY_CODES:
            plan.blockers.append(
                f"Dataset menyebut company terlindung {row['code']}. "
                "seed_organization() mencari Company hanya dengan kode dan akan "
                "menimpanya."
            )

        if row["code"] not in OWNED_COMPANY_CODES:
            plan.blockers.append(f"Company {row['code']} bukan milik dataset ini.")

        existing = Company.objects.filter(code=row["code"]).first()
        status = "NEW" if existing is None else (
            "EXISTS (milik dataset)" if ownership.is_owned_company(existing) else "CONFLICT"
        )

        plan.add("organization.company", {
            "code": row["code"],
            "name": row["name"],
            "type": row["company_type"],
            "parent": row["parent"],
            "ownership_marker": row["email"],
            "status": status,
        })

    def need(model, codes, label, field_name="code"):
        present = set(
            model.objects.filter(**{f"{field_name}__in": codes, "is_deleted": False})
            .values_list(field_name, flat=True)
        )

        for code in sorted(set(codes) - present):
            plan.blockers.append(f"Referensi {label} {code!r} tidak ada di tenant.")

    need(CompanyType, [r["company_type"] for r in dataset.companies], "CompanyType")
    need(LocationType, [r["location_type"] for r in dataset.locations], "LocationType")
    need(JobCategory, [r["job_category"] for r in dataset.positions], "JobCategory")
    need(JobLevel, [r["job_level"] for r in dataset.positions], "JobLevel")

    for model, key, label in (
        (Country, "country", "Country"),
        (Province, "province", "Province"),
        (City, "city", "City"),
    ):
        codes = {r[key] for r in dataset.companies + dataset.locations if r.get(key)}
        present = set(model.objects.filter(code__in=codes).values_list("code", flat=True))

        for code in sorted(codes - present):
            plan.warnings.append(
                f"Geografi {label} {code!r} tidak ada; seed_organization() "
                "mengosongkannya (bukan kegagalan)."
            )

    def status_of(model, company, code):
        if not Company.objects.filter(code=company).exists():
            return "NEW"

        exists = model.objects.filter(
            company__code=company, code=code, is_deleted=False
        ).exists()

        return "EXISTS" if exists else "NEW"

    for row in dataset.locations:
        plan.add("organization.location", {
            "company": row["company"], "code": row["code"], "name": row["name"],
            "type": row["location_type"], "status": status_of(Location, row["company"], row["code"]),
        })

    for company, _branch, location, code, name in dataset.divisions:
        plan.add("organization.division", {
            "company": company, "location": location, "code": code, "name": name,
            "status": status_of(Division, company, code),
        })

    for company, _branch, location, division, code, name in dataset.departments:
        plan.add("organization.department", {
            "company": company, "location": location, "division": division,
            "code": code, "name": name, "status": status_of(Department, company, code),
        })

    for company, _branch, location, _division, department, code, name in dataset.cost_centers:
        plan.add("organization.cost_center", {
            "company": company, "department": department, "code": code, "name": name,
            "status": status_of(CostCenter, company, code),
        })

    for row in dataset.positions:
        plan.add("organization.position", {
            "company": row["company"], "code": row["code"], "name": row["name"],
            "department": row["department"], "job_level": row["job_level"],
            "job_category": row["job_category"], "is_manager": row["is_manager"],
            "reports_to": row["reports_to"], "headcount": row["headcount"],
            "status": status_of(Position, row["company"], row["code"]),
        })

    for (company, code), reason in sorted(mapping.EXCLUDED_UNITS.items()):
        plan.add("organization.excluded", {"company": company, "code": code, "reason": reason})

    _reference_side_effects(plan)


def _reference_side_effects(plan: Plan) -> None:
    """
    `seed_organization()` selalu menegaskan ulang referensi organisasi
    (upsert) dan menarik jenis lokasi usang. Dilaporkan per nilai: yang
    identik hanya menyentuh `updated_at`; yang berbeda adalah perubahan
    master dan harus diputuskan.
    """
    from apps.administration.models import Location
    from apps.administration.models.references.organization import LocationType
    from apps.administration.seeds.reference.organization import (
        OBSOLETE_LOCATION_TYPES,
        ORGANIZATION_REFERENCE_DATA,
    )

    drift = []
    identical = 0

    for model, rows in ORGANIZATION_REFERENCE_DATA.items():
        existing = {row.code: row for row in model.objects.all()}

        for code, name, sort_order in rows:
            row = existing.get(code)

            if row is None:
                drift.append(f"{model.__name__} {code}: akan DIBUAT")
            elif (
                row.name != name
                or getattr(row, "sort_order", sort_order) != sort_order
                or row.is_deleted
                or not row.is_active
            ):
                drift.append(
                    f"{model.__name__} {code}: akan DIUBAH "
                    f"({row.name!r}/{getattr(row, 'sort_order', None)}/"
                    f"deleted={row.is_deleted}/active={row.is_active} → "
                    f"{name!r}/{sort_order}/aktif)"
                )
            else:
                identical += 1

    for code in OBSOLETE_LOCATION_TYPES:
        row = LocationType.objects.filter(code=code, is_deleted=False).first()

        if row and not Location.objects.filter(location_type=row, is_deleted=False).exists():
            drift.append(f"LocationType {code}: akan DITARIK (soft delete)")

    plan.add("organization.reference_side_effects", {
        "identical_rows_reasserted": identical,
        "value_changes": drift,
    })

    if drift:
        plan.decisions.append(
            "seed_organization() akan mengubah referensi organisasi bersama: "
            + "; ".join(drift)
        )


# ======================================================================
# Pegawai
# ======================================================================


def _employees(plan: Plan, workbook: Workbook, people: dict[str, PlannedPerson]) -> None:
    from apps.administration.models import (
        ContractType,
        EmployeeGroup,
        EmploymentStatus,
        EmploymentType,
    )
    from apps.hr.models import Employee

    contracts = {row.employee_id: row for row in workbook.contracts}

    for model, codes, label in (
        (EmploymentType, set(mapping.EMPLOYMENT_TYPE.values()), "EmploymentType"),
        (EmploymentStatus, set(mapping.EMPLOYMENT_STATUS.values()), "EmploymentStatus"),
        (ContractType, {mapping.CONTRACT_TYPE}, "ContractType"),
        (EmployeeGroup, {p.group for p in people.values()}, "EmployeeGroup"),
    ):
        present = set(
            model.objects.filter(code__in=codes, is_deleted=False).values_list("code", flat=True)
        )

        for code in sorted(codes - present):
            plan.blockers.append(f"Master {label} {code!r} tidak ada.")

    for employee_id, person in people.items():
        row = person.row

        for key, table in (("employment", mapping.EMPLOYMENT_TYPE), ("status", mapping.EMPLOYMENT_STATUS)):
            if getattr(row, key) not in table:
                plan.blockers.append(f"{employee_id}: {key} {getattr(row, key)!r} tidak terpetakan.")

        contract = contracts.get(employee_id)
        existing = Employee.objects.filter(employee_number=employee_id, is_deleted=False).first()

        plan.add("employees", {
            "employee_number": employee_id,
            "name": row.name,
            "company": person.company,
            "location": person.location,
            "department": person.department,
            "cost_center": f"{person.company}-{person.department}",
            "position": person.position,
            "job_level": person.job_level,
            "workbook_level": row.level,
            "employee_group": person.group,
            "employment_type": mapping.EMPLOYMENT_TYPE.get(row.employment),
            "employment_status": mapping.EMPLOYMENT_STATUS.get(row.status),
            "contract_type": mapping.CONTRACT_TYPE if contract else None,
            "contract_start": contract.start if contract else None,
            "contract_end": contract.end if contract else None,
            "reports_to": row.reports_to,
            "username": person.username,
            "notes_marker": mapping.employee_note(row),
            "locality": f"{row.locality} (rujukan saja, tidak dipetakan)",
            "status": "NEW" if existing is None else (
                "EXISTS (milik dataset)" if ownership.is_owned_employee(existing) else "CONFLICT"
            ),
            "write_path": "EmployeeService.create → OrganizationService / EmploymentService (full_clean)",
        })

        if contract and row.employment != "Contract":
            plan.blockers.append(
                f"{employee_id}: baris kontrak untuk pegawai {row.employment}; "
                "tipe tanpa requires_contract tidak boleh membawa masa kontrak."
            )

    plan.warnings.append(
        "Join Date (keputusan DEMO-1B §1): kontrak = Contract Start dataset; tetap dan "
        "kontrak tanpa masa kontrak = 2025-01-01. Pegawai kontrak sejak 2026 belum "
        "berhak cuti tahunan (ANNUAL-STD 12 bulan) — mesin cuti tidak diubah."
    )


# ======================================================================
# Akun, role, cakupan
# ======================================================================


def _access(plan: Plan, workbook: Workbook, people: dict[str, PlannedPerson]) -> None:
    from apps.accounts.models import Role, User

    grants = mapping.scope_grants(workbook)
    roles_needed = {mapping.BASE_GRANT.role} | {g.role for gs in grants.values() for g in gs}
    active_roles = set(
        Role.objects.filter(code__in=roles_needed, is_active=True, is_deleted=False)
        .values_list("code", flat=True)
    )

    for code in sorted(roles_needed - active_roles):
        plan.blockers.append(f"Role {code} tidak ada/aktif. Role baru tidak dibuat.")

    usernames = [p.username for p in people.values()]

    for name in sorted({u for u in usernames if usernames.count(u) > 1}):
        plan.blockers.append(f"Username ganda hasil pemetaan: {name}")

    # DEMO-1E: alamat akun = LOGIN_ALIASES. Unik di antara pegawai dataset dan
    # tidak dipegang akun lain di tenant (`User.email` unik).
    missing_alias = sorted(set(people) - set(mapping.LOGIN_ALIASES))
    for employee_id in missing_alias:
        plan.blockers.append(f"{employee_id}: tidak punya alias login (mapping.LOGIN_ALIASES).")

    emails = {e: mapping.user_email(p.row) for e, p in people.items() if e not in missing_alias}
    values = list(emails.values())
    for address in sorted({a for a in values if values.count(a) > 1}):
        plan.blockers.append(f"Alamat akun ganda hasil pemetaan: {address}")

    ours = {p.username for p in people.values()}
    for other in User.objects.filter(email__in=[a.lower() for a in values] + values).exclude(username__in=ours):
        plan.blockers.append(f"Alamat {other.email} sudah dipakai akun {other.username} (bukan dataset).")

    for employee_id, person in people.items():
        user = User.objects.filter(username=person.username).first()
        row_grants = [mapping.BASE_GRANT] + grants.get(employee_id, [])

        plan.add("access", {
            "employee_number": employee_id,
            "position": person.row.position,
            "username": person.username,
            "email": emails.get(employee_id),
            "user_status": "NEW" if user is None else "EXISTS",
            "grants": [
                {
                    "role": g.role,
                    "mode": g.mode,
                    "level": g.level,
                    "authorities": [f"{t}:{k}" if k else t for t, k in g.authorities],
                    "note": g.note,
                }
                for g in row_grants
            ],
            "write_path": "grant_role(user, role, mode=, level=, authorities=)",
        })

    for row in workbook.scopes:
        if row.scope_type in mapping.UNSUPPORTED_SCOPE_TYPES:
            plan.warnings.append(
                f"{row.employee_id} {row.role_position}: cakupan {row.scope_type} "
                f"tidak didukung — {mapping.UNSUPPORTED_SCOPE_TYPES[row.scope_type]} "
                "Hanya EMPLOYEE (own) yang diberikan."
            )

        if row.scope_type == "MULTI_COMPANY":
            plan.warnings.append(
                f"{row.employee_id}: cakupan data {'+'.join(row.company_scope)} "
                "didukung (authority explicit), tapi sebagai approver resolver "
                "hanya membaca penempatan sendiri — ia tidak akan terpilih untuk "
                "dokumen company lain. Keterbatasan yang diketahui."
            )

    plan.warnings.append(
        "Running Documents: WORKFLOW_MONITOR_ROLES (HR-ADMIN, HR-MANAGER) melihat "
        "seluruh instance tenant. HR Manager MMN akan melihat dokumen MIN di layar "
        "itu. Keterbatasan yang diketahui, tidak diperbaiki."
    )


# ======================================================================
# Kalender / roster
# ======================================================================


def _schedules(plan: Plan, workbook: Workbook, people: dict[str, PlannedPerson]) -> None:
    from django.apps import apps as django_apps

    from apps.administration.models import RosterPolicy, RosterShiftRotation, Shift, WorkCalendar

    from . import roster_policy as roster_source

    # DEMO-1F: policy roster = milik MMN dari sumber; master global yang
    # dirujuknya harus ada (kode hilang = blocker, bukan FK karangan).
    for kind, codes in roster_source.reference_codes().items():
        if kind == "City":
            for key in sorted(codes):
                try:
                    roster_source.resolve_city(key)
                except LookupError as exc:
                    plan.blockers.append(f"Roster policy MMN: {exc}")
            continue
        model = django_apps.get_model("administration", kind)
        found = set(model.objects.filter(code__in=codes, is_deleted=False).values_list("code", flat=True))
        for missing in sorted(codes - found):
            plan.blockers.append(f"Roster policy MMN: master {kind} {missing!r} tidak ada.")

    for code, target in mapping.SCHEDULE.items():
        policy = None

        if target.roster_policy:
            if target.roster_policy not in roster_source.BY_CODE:
                plan.blockers.append(f"Roster policy {target.roster_policy!r} tidak ada di sumber.")
            policy = RosterPolicy.objects.filter(
                company__code=roster_source.COMPANY, code=target.roster_policy, is_deleted=False,
            ).select_related("company", "location").first()

        if target.working_calendar and not WorkCalendar.objects.filter(
            code=target.working_calendar, is_deleted=False, is_active=True, company__isnull=True
        ).exists():
            plan.blockers.append(f"Kalender GLOBAL {target.working_calendar!r} tidak ada.")

        if target.shift and not Shift.objects.filter(
            code=target.shift, is_deleted=False, is_active=True
        ).exists():
            plan.blockers.append(f"Shift {target.shift!r} tidak ada/aktif.")

        rotation = []

        if target.roster_policy:
            rotation = [(shift, days) for _, shift, days in roster_source.ROTATION]

        plan.add("schedule.mapping", {
            "workbook_code": code,
            "roster_policy": target.roster_policy,
            "cycle": (
                f"{roster_source.BY_CODE[target.roster_policy].cycle_work_days}/"
                f"{roster_source.BY_CODE[target.roster_policy].cycle_off_days}"
                if target.roster_policy in roster_source.BY_CODE else None
            ),
            "policy_owner": (
                f"{roster_source.COMPANY}/{roster_source.LOCATION}"
                + (" (ada)" if policy else " (dibuat dari sumber)")
                if target.roster_policy else None
            ),
            "rotation": [f"{shift}×{days}" for shift, days in rotation],
            "working_calendar": target.working_calendar,
            "shift": target.shift,
            "semantics": target.semantics,
            "note": target.note,
        })

    for row in workbook.roster_assignments:
        person = people[row.employee_id]
        target = mapping.SCHEDULE[row.policy_code]

        plan.add("schedule.assignment", {
            "employee_number": row.employee_id,
            "workbook_code": row.policy_code,
            "roster_policy": target.roster_policy,
            "roster_cycle_start": row.effective_from if target.roster_policy else None,
            "working_calendar": target.working_calendar,
            "shift": target.shift,
            "employee_group": person.group,
            "write_path": (
                "RosterSetupService / RosterGenerationService"
                if target.roster_policy else "EmploymentService (calendar + shift)"
            ),
        })

    if any(mapping.SCHEDULE[r.policy_code].roster_policy for r in workbook.roster_assignments):
        plan.warnings.append(
            "Policy roster 42/14 dan 56/14 milik MMN/SAGEA-MINE dari sumber dataset "
            "(DEMO-1F; salinan persis policy MMR yang dipakai sebelumnya)."
        )

    plan.warnings.append(
        "Kode roster workbook bersemantik hari (6/2, 8/2, 12 jam siang-malam); "
        "ERP bersemantik 42/14 dan 56/14 dengan rotasi tiga shift 8 jam. Semantik "
        "ERP dipertahankan (H7); angka bulanan workbook tidak akan tereproduksi."
    )


# ======================================================================
# Kontrak
# ======================================================================


def _contracts(plan: Plan, workbook: Workbook) -> None:
    """
    Label peringatan dihitung ERP dari tanggal akhir — tidak disimpan.
    Bucket diambil dari `expiry_status()` laporan Contract Expiry itu
    sendiri, satu-satunya tempat ambangnya diputuskan.
    """
    from apps.reports.api.hr.contract_expiry.statuses import expiry_status

    for row in workbook.contracts:
        days = (row.end - REFERENCE_DATE).days
        bucket = expiry_status(days)

        plan.add("contracts", {
            "employee_number": row.employee_id,
            "contract_start": row.start,
            "contract_end": row.end,
            "days_at_reference": days,
            "workbook_alert": row.alert,
            "erp_report_bucket": bucket,
            "stored": "contract_start/contract_end saja; label diturunkan",
            "action_route": f"{row.action_route} (rujukan; alur nyata HR-EMPLOYEE-ACTION)",
        })


# ======================================================================
# Cuti / izin (B4)
# ======================================================================


def _leaves(plan: Plan, workbook: Workbook, people: dict[str, PlannedPerson]) -> None:
    from apps.administration.models import EmployeeGroup
    from apps.workflow.services.definition_service import WorkflowDefinitionResolver

    groups = {g.code: g.pk for g in EmployeeGroup.objects.filter(is_deleted=False)}

    for row in workbook.leaves:
        actor_id = mapping.scenario_employee(row)
        person = people[actor_id]
        start, end = mapping.scenario_dates(row)
        row_dates = (start, end)
        kind, code = mapping.LEAVE_KIND[row.leave_type]
        erp_status, path = mapping.LEAVE_STATUS[row.status]
        schedule = mapping.SCHEDULE[
            next(r.policy_code for r in workbook.roster_assignments if r.employee_id == actor_id)
        ]

        issues: list[str] = []
        supported = True

        if row.request_id in mapping.SCENARIO_DATES:
            issues.append(f"Tanggal dipindah {start}..{end}: {mapping.SCENARIO_DATES[row.request_id][2]}")
            unscheduled = _unscheduled_days(actor_id, start, end)

            if unscheduled:
                plan.blockers.append(
                    f"{row.request_id}: tanggal pengganti tidak semuanya hari kerja terjadwal "
                    f"{actor_id}: {unscheduled}"
                )

        if kind == "attendance_permission" and row.start != row.end:
            issues.append("Izin kehadiran hanya satu tanggal per dokumen.")
            supported = False

        if kind == "attendance_permission" and erp_status == "recorded":
            issues.append("Izin kehadiran tidak punya status RECORDED.")
            supported = False

        if schedule.roster_policy is None:
            weekend = [
                (start + timedelta(days=i)).isoformat()
                for i in range((end - start).days + 1)
                if (start + timedelta(days=i)).weekday() >= 5
            ]

            if weekend:
                issues.append(
                    f"Jatuh di akhir pekan kalender kantor ({', '.join(weekend)}) — "
                    "di luar jadwal; izin butuh allow_outside_shift, cuti bernilai 0 hari."
                )
                plan.warnings.append(
                    f"{row.request_id} ({row.employee_id}): tanggal di luar jadwal "
                    f"kantor ({', '.join(weekend)}). Dijalankan dengan "
                    "allow_outside_shift + alasan (kolom sah), atau diganti tanggal kerja."
                )

        if row.request_id in mapping.SCENARIO_SUBSTITUTES:
            issues.append(f"Pengganti (B4): {mapping.SCENARIO_SUBSTITUTES[row.request_id][1]}")

        route: list[dict] = []
        definition_code = None

        if erp_status != "recorded":
            definition = WorkflowDefinitionResolver.match(
                module="hr",
                document_type="leave_request" if kind == "leave" else "attendance_permission",
                # Company/lokasi dataset belum ada: sentinel yang tidak
                # sama dengan PK mana pun — alur bercakupan company/lokasi
                # lain memang tidak boleh cocok, persis seperti nanti.
                company=f"new:{person.company}",
                branch=f"new:{person.company}/DEFAULT",
                location=f"new:{person.company}/{person.location}",
                employee_group=groups.get(person.group),
            )

            if definition is None:
                issues.append("Tidak ada definisi alur yang cocok — pengajuan akan gagal.")
                supported = False
            else:
                definition_code = definition.code
                route = predict_route(definition, person, people)

                if any(step["status"] == "UNRESOLVED" for step in route):
                    issues.append(
                        "Ada step wajib tanpa approver: submit akan ditolak "
                        "(CONFIGURATION ERROR). Skenario TIDAK DIDUKUNG apa adanya (B4)."
                    )
                    supported = False

        plan.add("leave", {
            "scenario_key": row.request_id,
            "note_marker": f"{DOCUMENT_NOTE_PREFIX}{row.request_id}]",
            "employee_number": actor_id,
            "workbook_employee": row.employee_id,
            "model": kind,
            "type": code,
            "start": row_dates[0],
            "end": row_dates[1],
            "workbook_days": row.days,
            "days": "diturunkan LeaveDayCalculator (tidak disalin)",
            "workbook_status": row.status,
            "erp_status": erp_status,
            "path": path,
            "workbook_route": row.approval_route,
            "definition": definition_code,
            "predicted_route": route,
            "supported": supported,
            "issues": issues,
        })

    rows = plan.sections.get("leave", [])

    for entry in rows:
        if entry["supported"]:
            continue

        covering = [
            other["scenario_key"] for other in rows
            if other["supported"]
            and other["model"] == entry["model"]
            and other["erp_status"] == entry["erp_status"]
        ]
        entry["alternative"] = (
            f"Fitur yang sama ({entry['model']} {entry['erp_status']}) sudah "
            f"diperagakan oleh {', '.join(covering)}; skenario ini dilewati di DEMO-1B."
            if covering else
            "Tidak ada skenario pengganti yang setara — butuh keputusan."
        )
        plan.warnings.append(
            f"{entry['scenario_key']} ({entry['employee_number']}) tidak didukung apa "
            f"adanya: {' '.join(entry['issues'])} → {entry['alternative']}"
        )

        if not covering:
            plan.decisions.append(
                f"{entry['scenario_key']}: tidak didukung dan tidak ada pengganti setara."
            )


def _unscheduled_days(employee_id: str, start, end) -> list[str]:
    """Hari tanpa jadwal kerja, bila pegawainya sudah ada. Belum ada = []."""
    from apps.hr.api.attendance.schedule import scheduled_work_days
    from apps.hr.models import Employee

    employee = Employee.objects.filter(employee_number=employee_id, is_deleted=False).first()

    if employee is None:
        return []

    days = scheduled_work_days(employee, start, end)

    return [
        (start + timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
        if start + timedelta(days=i) not in days
    ]


def predict_route(definition, subject: PlannedPerson, people: dict[str, PlannedPerson]) -> list[dict]:
    """
    **Prakiraan**, bukan resolusi. Mesin (`resolve_approvers`) yang
    memutuskan saat submit di DEMO-1B; ini hanya membaca definisinya
    dan memasangkan pemegang role yang **direncanakan** menurut
    penempatan mereka sendiri — cara resolver mencari pemegang role.
    Tipe step yang tidak bisa diprakirakan dilaporkan apa adanya.
    """
    steps = definition.steps.filter(is_deleted=False, is_active=True).order_by("sequence")
    route = []
    previous: set[str] = set()

    def holders(role_code: str, scope: str) -> list[str]:
        found = []

        for employee_id, person in people.items():
            if employee_id == subject.row.employee_id or role_code not in person.roles:
                continue

            if person.company != subject.company:
                continue

            if scope == "location" and person.location != subject.location:
                continue

            if scope == "department" and person.department != subject.department:
                continue

            # Dataset ini tidak membuat Section: pemegang role bercakupan
            # section tidak mungkin ditemukan resolver.
            if scope == "section":
                continue

            found.append(employee_id)

        return sorted(found)

    for step in steps:
        entry = {
            "sequence": step.sequence,
            "type": step.approver_type,
            "scope": step.approver_scope,
            "role": step.approver_role.code if step.approver_role_id else None,
            "required": step.is_required,
            "condition": bool(step.condition),
            "approvers": [],
            "via": "primary",
            "status": "",
        }

        found: list[str] = []

        if step.approver_type == "manager":
            current = subject.row

            for _ in range(max(step.level or 1, 1)):
                current = people[current.reports_to].row if current.reports_to else None

                if current is None:
                    break

            found = [current.employee_id] if current is not None else []
        elif step.approver_type == "role" and step.approver_role_id:
            found = holders(step.approver_role.code, step.approver_scope)
        elif step.approver_type == "department_head":
            found = sorted(
                employee_id for employee_id, person in people.items()
                if employee_id != subject.row.employee_id
                and person.company == subject.company
                and person.department == subject.department
                and mapping.is_manager_position(person.row)
            )
        else:
            entry["status"] = "ENGINE"

        if not found and entry["status"] != "ENGINE":
            for role, scope in step.fallback_chain():
                found = holders(role.code, scope)

                if found:
                    entry["via"] = f"fallback {role.code}@{scope}"
                    break

        entry["approvers"] = found

        if entry["status"] == "ENGINE":
            pass
        elif entry["condition"]:
            entry["status"] = "CONDITIONAL"
        elif not found:
            entry["status"] = "UNRESOLVED" if step.is_required else "SKIPPED"
        elif set(found) <= previous:
            entry["status"] = "SKIPPED (sudah terwakili)"
        else:
            entry["status"] = "RESOLVED"

        previous |= set(found)
        route.append(entry)

    return route


# ======================================================================
# Presensi
# ======================================================================

ATTENDANCE_FIELDS = {
    "Period": "KUNCI",
    "Employee ID": "KUNCI",
    "HO/Site": "DITURUNKAN (lokasi penempatan)",
    "Roster": "DITURUNKAN (policy/kalender pegawai)",
    "Present": "DITURUNKAN (tap → hitung → penutupan)",
    "Absent": "DITURUNKAN (penutupan hari terjadwal tanpa tap)",
    "Leave/Permit": "DITURUNKAN (dokumen cuti/izin)",
    "Off": "DITURUNKAN (roster/kalender)",
    "OT Hours": "SUMBER = dokumen lembur (EmployeeOvertime); bukti = overtime_minutes",
    "Night Hours": "RUJUKAN SAJA — tidak diimplementasikan, diabaikan",
    "Scenario": "RUJUKAN SAJA",
}


def _attendance(plan: Plan, workbook: Workbook) -> None:
    for name, klass in ATTENDANCE_FIELDS.items():
        plan.add("attendance.fields", {"field": name, "class": klass})

    cutoff = REFERENCE_DATE - timedelta(days=1)

    plan.add("attendance.generation", {
        "window": f"2026-08-01 .. {cutoff.isoformat()}",
        "external_id_prefix": ATTENDANCE_EXTERNAL_PREFIX,
        "raw_tap_batch": ATTENDANCE_BATCH,
        "path": (
            "tap CSV → ImportPipelineService → EmployeeAttendanceService → "
            "AttendanceClosingService.close(employees=<milik dataset>) → recalculate"
        ),
        "employees": "seluruh pegawai milik dataset yang presensinya berlaku (bukan BOARD)",
        "note": (
            "September berhenti sehari sebelum tanggal acuan; tap masa depan tidak "
            "dikarang. Angka bulanan workbook hanya rujukan."
        ),
    })

    for row in workbook.attendance:
        plan.add("attendance.reference", {
            "period": row.period, "employee_number": row.employee_id, "roster": row.roster,
            "present": row.present, "absent": row.absent, "leave_permit": row.leave_permit,
            "off": row.off, "ot_hours": row.ot_hours,
            "night_hours": f"{row.night_hours} (diabaikan)",
            "use": "pembanding di laporan verifikasi, tidak ditulis",
        })


# ======================================================================
# Payroll
# ======================================================================

PAYROLL_FIELDS = {
    "Basic Salary": "SUMBER → PayrollAssignment.basic_salary",
    "Fixed Allowance": "HASIL MESIN (template per hari hadir / % gaji pokok); tidak disalin",
    "Overtime": "HASIL MESIN dari dokumen lembur; tidak disalin",
    "Employer Benefit": "HASIL MESIN (BPJS pemberi kerja); tidak disalin",
    "Gross Cost": "HASIL MESIN; tidak disalin",
    "Employee Deduction": "HASIL MESIN (BPJS pegawai + PPh21); tidak disalin",
    "Net Pay": "HASIL MESIN; nilai workbook keliru (memasukkan Employer Benefit)",
}


def _payroll(plan: Plan, workbook: Workbook, people: dict[str, PlannedPerson]) -> None:
    from apps.administration.models import Currency
    from apps.payroll.models import (
        AllowanceTemplate,
        DeductionTemplate,
        OvertimeGroup,
        PayrollGroup,
    )

    for name, klass in PAYROLL_FIELDS.items():
        plan.add("payroll.fields", {"field": name, "class": klass})

    salaries: dict[str, set] = {}

    for row in workbook.payroll:
        salaries.setdefault(row.employee_id, set()).add(row.basic_salary)

    for employee_id in sorted(set(people) - set(salaries)):
        salaries[employee_id] = {mapping.basic_salary(people[employee_id].row, workbook)[0]}

        if row.company != people[row.employee_id].company:
            plan.blockers.append(
                f"09[{row.period}/{row.employee_id}]: company {row.company} ≠ "
                f"penempatan {people[row.employee_id].company}."
            )

    for code, model in (
        ("MONTHLY", PayrollGroup),
        ("STANDARD", AllowanceTemplate),
        ("STANDARD", DeductionTemplate),
    ):
        if not model.objects.filter(code=code, is_deleted=False).exists():
            plan.blockers.append(f"{model.__name__} {code} tidak ada.")

    if not Currency.objects.filter(code="IDR", is_deleted=False).exists():
        plan.blockers.append("Currency IDR tidak ada.")

    shift_ot = OvertimeGroup.objects.filter(code="SHIFT", is_deleted=False).exists()

    for employee_id in sorted(salaries):
        values = salaries[employee_id]
        person = people[employee_id]

        if len(values) != 1:
            plan.blockers.append(f"{employee_id}: gaji pokok berbeda antar periode {sorted(values)}.")

        site = mapping.overtime_eligible(person.row)

        plan.add("payroll.assignment", {
            "employee_number": employee_id,
            "position": person.row.position,
            "job_level": person.job_level,
            "company": person.company,
            "basic_salary": min(values),
            "salary_basis": mapping.basic_salary(person.row, workbook)[1],
            "tax_status": "TK/0 (asumsi; workbook tanpa status perkawinan)",
            "currency": "IDR",
            "payroll_group": "MONTHLY",
            "allowance_template": "STANDARD",
            "deduction_template": "STANDARD",
            "overtime_eligible": site,
            "overtime_group": "SHIFT" if site and shift_ot else None,
            "write_path": "PayrollAssignment lewat service HR (full_clean)",
        })

    for tier, (amount, basis) in mapping.SALARY_MATRIX.items():
        plan.add("payroll.salary_matrix", {"tier": tier, "basic_salary": amount, "basis": basis})

    companies = sorted({person.company for person in people.values()})

    for company in companies:
        for period in sorted({row.period for row in workbook.payroll}):
            approvers = {
                role: sorted(
                    e for e, p in people.items()
                    if p.company == company and role in p.roles
                )
                for role in ("HR-MANAGER", "FINANCE-MANAGER")
            }

            plan.add("payroll.run", {
                "company": company,
                "period": period,
                "payroll_group": "MONTHLY",
                "run_type": "regular",
                "business_key": f"{company}/MONTHLY/{period}/regular",
                "note_marker": f"{DOCUMENT_NOTE_PREFIX}PAY-{company}-{period}]",
                "lifecycle": "create → generate → calculate → submit (PAY-RUN-STD) → approve → finalize",
                "stops_at": "finalize → PAYROLL_POSTED → jurnal DRAFT (tidak diposting, B3)",
                "predicted_approvers": approvers,
            })

            for role, holders in approvers.items():
                if not holders:
                    plan.warnings.append(
                        f"PAY-RUN-STD {company} {period}: tidak ada pemegang {role}@company — run "
                        "bisa dihitung (baseline) tapi submit akan ditolak mesin di tahap transaksi."
                    )

        for row in workbook.payroll:
            if people[row.employee_id].company == company:
                plan.add("payroll.reference", {
                    "period": row.period, "employee_number": row.employee_id,
                    "basic": row.basic_salary, "allowance": row.fixed_allowance,
                    "overtime": row.overtime, "employer_benefit": row.employer_benefit,
                    "gross_cost": row.gross_cost, "deduction": row.employee_deduction,
                    "net_pay": row.net_pay, "use": "pembanding saja",
                })

    plan.warnings.append(
        "Gerbang payroll HR-DEMO-5 tetap terbuka (working_days, lembur HO, "
        "TEMPORARY_OUT, PayrollPermissionRule). Tidak diperbaiki di tahap ini."
    )


# ======================================================================
# Finance bootstrap
# ======================================================================


def _identity(plan: Plan, people: dict[str, PlannedPerson]) -> None:
    """
    DEMO-1E: tabel identitas menutup seluruh populasi, dan setiap kode
    master yang dirujuknya ada di tenant. Kode yang hilang = blocker —
    FK tidak pernah dikarang.
    """
    from django.apps import apps as django_apps

    from . import identity

    table = identity.BY_EMPLOYEE

    for employee_id in sorted(set(people) - set(table)):
        plan.blockers.append(f"{employee_id}: tidak ada di tabel identitas.")

    for employee_id in sorted(set(table) - set(people)):
        plan.blockers.append(f"{employee_id}: ada di tabel identitas tapi bukan populasi workbook.")

    labels = {
        "Gender": "administration.Gender", "Religion": "administration.Religion",
        "MaritalStatus": "administration.MaritalStatus", "BloodType": "administration.BloodType",
        "Nationality": "administration.Nationality", "Province": "administration.Province",
        "City": "administration.City", "District": "administration.District",
        "Village": "administration.Village", "Bank": "administration.Bank",
        "FamilyRelationship": "administration.FamilyRelationship",
        "Education": "administration.Education", "Degree": "administration.Degree",
        "StudyField": "administration.StudyField",
    }

    for kind, codes in sorted(identity.reference_codes().items()):
        model = django_apps.get_model(labels[kind])
        qs = model.objects.filter(code__in=codes)
        if any(f.name == "is_deleted" for f in model._meta.fields):
            qs = qs.filter(is_deleted=False)
        found = set(qs.values_list("code", flat=True))

        for code in sorted(codes - found):
            plan.blockers.append(f"Identitas: master {kind} {code!r} tidak ada di tenant.")

    nik = [i.nik for i in table.values()]
    if len(set(nik)) != len(nik):
        plan.blockers.append("Identitas: NIK ganda di tabel.")

    for employee_id, i in sorted(table.items()):
        if employee_id not in people:
            continue
        plan.add("identity", {
            "employee_number": employee_id,
            "gender": i.gender,
            "birth": f"{i.birth_place}, {i.birth_date}",
            "religion": i.religion,
            "marital": i.marital_status,
            "domicile": i.village,
            "relatives": len(i.relatives),
            "education": i.education.level,
            "bank": i.bank,
            "tax_status_derived": identity.derived_tax_status(i),
            "tax_status_payroll": "TK/0",
        })

    mismatch = sorted(
        e for e, i in table.items()
        if e in people and identity.derived_tax_status(i) != "TK/0"
    )
    if mismatch:
        plan.warnings.append(
            f"Status pajak: {len(mismatch)} pegawai berstatus PTKP turunan ≠ TK/0 "
            f"({', '.join(mismatch)}). PayrollAssignment tetap TK/0 — mengubahnya mengubah "
            "PPh 21 dan net pay baseline; menunggu persetujuan (DEMO-1E §E)."
        )


def _finance(plan: Plan, workbook: Workbook) -> None:
    from apps.administration.models import Company
    from apps.finance.models import (
        Account,
        AccountingPolicy,
        AccountMapping,
        FiscalYear,
    )
    from apps.finance.seeds import chart_of_accounts, policies

    template_codes = [row[0] for row in chart_of_accounts.TEMPLATE]
    rule_count = len(policies.RULES)
    line_count = sum(len(rule[4]) for rule in policies.RULES)

    for code in OWNED_COMPANY_CODES:
        company = Company.objects.filter(code=code).first()
        probe = company if company is not None else Company(code=code)

        existing_accounts = (
            set(
                Account.objects.filter(company=company, is_deleted=False)
                .values_list("code", flat=True)
            )
            if company is not None else set()
        )

        fiscal_exists = company is not None and FiscalYear.objects.filter(
            company=company, is_deleted=False,
            start_date__year__lte=FISCAL_YEAR, end_date__year__gte=FISCAL_YEAR,
        ).exists()

        mapping_codes = [policies.mapping_code(probe, key) for key in policies.MAPPING_ACCOUNTS]
        policy_code = policies.policy_code(probe)

        mapping_taken = set(
            AccountMapping.objects.filter(code__in=mapping_codes, is_deleted=False)
            .exclude(company__code=code)
            .values_list("code", flat=True)
        )
        policy_taken = AccountingPolicy.objects.filter(
            code=policy_code, is_deleted=False
        ).exclude(company__code=code).exists()

        for taken in sorted(mapping_taken):
            plan.blockers.append(f"Kode pemetaan {taken} sudah dipakai company lain.")

        if policy_taken:
            plan.blockers.append(f"Kode kebijakan {policy_code} sudah dipakai company lain.")

        plan.add("finance.bootstrap", {
            "company": code,
            "command": (
                f"seed_finance --company={code} --only=coa; "
                f"--only=fiscal --year={FISCAL_YEAR}; --only=policy"
            ),
            "chart_of_accounts": (
                f"{len(set(template_codes) - existing_accounts)} akun baru dari template "
                f"({len(template_codes)} baris), lewat AccountService.create"
            ),
            "fiscal_year": (
                "sudah ada" if fiscal_exists
                else f"FY{FISCAL_YEAR} + 12 periode OPEN lewat FiscalYearService"
            ),
            "account_mappings": f"{len(mapping_codes)} ({mapping_codes[0]} … )",
            "accounting_policy": (
                f"{policy_code}: {rule_count} aturan, {line_count} baris, auto_post=False"
            ),
            "gl_codes_in_demo_seed": "nol — akun berasal dari template & pemetaan milik Finance",
        })

    _finance_expectations(plan, workbook)

    plan.add("finance.bootstrap_scope", {
        "excluded_step": "dimensions",
        "reason": (
            "seed_dimensions() berlaku se-tenant dan memperbarui baris yang ada. "
            "Dimensi yang ada sudah cukup; langkah ini tidak dijalankan."
        ),
        "why_mni_mmr_mls_untouched": (
            "seed_chart_of_accounts/_retire_legacy/_seed_mappings memfilter "
            "company=<company yang disebut>; seed_fiscal_years hanya iterasi "
            "companies yang diberikan; kode kebijakan/pemetaan diturunkan dari "
            "kode company. Dibuktikan ulang lewat sidik jari finance.* sesudah apply."
        ),
    })


#: Makna akuntansi di lembar 10 → kunci peran pemetaan yang ada di
#: kebijakan `PAYROLL_POSTED`. Kunci peran, **bukan** kode akun: akunnya
#: diputuskan `AccountMapping` milik Finance.
POSTING_SEMANTICS = {
    "Salary & Wages Expense": (
        "SALARY_EXPENSE", "ALLOWANCE_EXPENSE", "OVERTIME_EXPENSE",
        "EMPLOYER_SOCIAL_EXPENSE", "EMPLOYER_BENEFIT_EXPENSE",
    ),
    "Payroll Payable": ("PAYROLL_PAYABLE",),
    "Employee Deduction Payable": (
        "INCOME_TAX_PAYABLE", "SOCIAL_SECURITY_PAYABLE", "OTHER_DEDUCTION_PAYABLE",
    ),
}


def _finance_expectations(plan: Plan, workbook: Workbook) -> None:
    for row in workbook.finance_postings:
        keys = POSTING_SEMANTICS.get(row.semantic)

        if keys is None:
            plan.warnings.append(f"10: makna {row.semantic!r} tidak punya padanan peran.")

        plan.add("finance.expectation", {
            "period": row.period,
            "company": row.company,
            "event_type": row.event_type,
            "workbook_semantic": f"{row.semantic} ({row.side})",
            "mapping_keys": list(keys or ()),
            "workbook_status": row.status,
            "seeded_state": (
                "PAYROLL_POSTED → jurnal DRAFT (B3). Posting = aksi manajemen "
                "terpisah lewat FIN-JOURNAL-STD + finance.post_journal."
            ),
        })

    paid = {(row.period, row.company) for row in workbook.payroll}
    posted = {(row.period, row.company) for row in workbook.finance_postings}

    for period, company in sorted(paid - posted):
        plan.warnings.append(
            f"10_Finance_Posting tidak punya baris {company} {period}, padahal lembar 09 "
            "punya payroll-nya. Finalize tetap menerbitkan kejadian untuk run itu."
        )


# ======================================================================
# Reset
# ======================================================================


def _reset(plan: Plan, report: ownership.OwnershipReport) -> None:
    plan.add("reset.scope", {
        "owned_companies": report.owned_companies,
        "owned_employee_count": len(report.owned_employee_ids),
        "owned_rows": report.owned_counts,
        "protected_prefixes": "HO/SGA/LOK/BOD/TRL + company MNI/MMR/MLS tidak pernah masuk cakupan",
    })

    posted = ownership.posted_history()

    if plan.reset and posted:
        plan.blockers.append(
            "Reset ditolak: riwayat Finance milik dataset ini sudah diposting "
            f"({'; '.join(posted)}). Tidak ada pembalikan otomatis, tidak ada "
            "penghapusan jurnal POSTED (B3)."
        )
    elif posted:
        plan.warnings.append(
            "Riwayat Finance POSTED ada di company milik dataset; --reset akan menolak."
        )

    from apps.payroll.models import PayrollRun
    from apps.payroll.models.choices import PayrollRunStatus

    counts = report.owned_counts
    maintenance = [
        name for name in ("finance.journal", "finance.accounting_event")
        if counts.get(name)
    ]

    if PayrollRun.objects.filter(
        company__code__in=OWNED_COMPANY_CODES, status=PayrollRunStatus.FINALIZED, is_deleted=False,
    ).exists():
        maintenance.append("payroll.run FINALIZED")

    if plan.reset and maintenance:
        plan.decisions.append(
            "Reset baseline berisi baris yang tidak bisa dibongkar lewat service "
            f"({', '.join(maintenance)}): jurnal DRAFT hasil proyeksi terkunci sumbernya "
            "dan run FINALIZED tidak bisa dibatalkan. Butuh persetujuan jalur "
            "pemeliharaan seperti finance_reset/uat_cleanup, terbatas pada company "
            "milik dataset."
        )
