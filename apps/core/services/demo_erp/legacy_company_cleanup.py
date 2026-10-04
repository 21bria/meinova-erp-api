"""
Pembuangan company peragaan lama MNI/MMR/MLS — DEMO-1F (28 Sep 2026).

Disetujui eksplisit: tenant peragaan manajemen = GRP/MMN/MIN saja. Yang
dibuang **hanya** baris yang diaudit sebagai milik eksklusif ketiga company
itu (audit DEMO-1F):

    Finance    policy line/rule → policy → mapping → periode → tahun buku → akun
    HR/payroll setelan payroll, go-live cuti, perangkat absensi, kebijakan absensi
    Roster     hari perjalanan, rotasi shift → policy (+tautan tujuan) → crew
    Kalender   relasi libur-company → libur → kalender kerja
    Alur       HR-TR-SITE, HR-LEAVE-SITE, HR-HO-LEAVE (lokasi MMR) + step + fallback
    Organisasi fasilitas → posisi → seksi → cost center → departemen → divisi
    Riwayat    jejak audit ber-company/lokasi lama atau tentang baris yang dibuang
               → lokasi → branch → company (MLS, MMR, lalu MNI)

Master bersama tidak disentuh: kalender/libur GLOBAL, shift, kota/provinsi,
tujuan rotasi, definisi alur global, kebijakan absensi GLOBAL.

**Menolak** (tanpa menulis) bila himpunan company tidak persis
GRP/MMN/MIN + MNI/MMR/MLS, ada pegawai/akun/run/periode payroll/instance
alur di company lama, ada AccountingEvent/Journal di tenant, ada pegawai
EMP yang masih merujuk objek lama, ada authority RBAC ke objek lama, atau
ada baris di luar cakupan yang menunjuk cakupan (dependensi belum diaudit).

**Sesudah membuang**, di transaksi yang sama: (1) setiap model di luar
cakupan harus kehilangan tepat 0 baris — CASCADE tak terduga = gagal;
(2) `SET CONSTRAINTS ALL IMMEDIATE` — FK yatim = gagal. Pemanggil
me-rollback seluruhnya bila ada yang gagal. PROTECT tidak pernah dilewati:
`delete()` biasa, bukan SQL mentah.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from django.apps import apps
from django.db import connection
from django.db.models import Q

from .constants import OWNED_COMPANY_CODES

LEGACY_COMPANY_CODES = ("MNI", "MMR", "MLS")

#: Definisi alur berlingkup lokasi company lama (audit: 0 instance).
LEGACY_WORKFLOW_DEFINITIONS = ("HR-TR-SITE", "HR-LEAVE-SITE", "HR-HO-LEAVE")

#: Urutan pembuangan: anak sebelum induk (PROTECT/SET_NULL diaudit).
ORDER = (
    "workflow.WorkflowStepFallback",
    "workflow.WorkflowStep",
    "workflow.WorkflowDefinition",
    "finance.AccountingPolicyLine",
    "finance.AccountingPolicyRule",
    "finance.AccountingPolicy",
    "finance.AccountMapping",
    "finance.AccountingPeriod",
    "finance.FiscalYear",
    "finance.Account",
    "payroll.PayrollSetting",
    "hr.LeaveGoLive",
    "hr.AttendanceDevice",
    "administration.AttendancePolicy",
    "administration.RosterTravelDay",
    "administration.RosterShiftRotation",
    "administration.RosterPolicy",
    "administration.RosterCrew",
    "administration.HolidayCompany",
    "administration.Holiday",
    "administration.WorkCalendar",
    "administration.Facility",
    "administration.Position",
    "administration.Section",
    "administration.CostCenter",
    "administration.Department",
    "administration.Division",
    "administration.AuditTrail",
    "administration.Location",
    "administration.Branch",
    "administration.Company",
)

AUDIT_COLUMNS = frozenset({"created_by", "updated_by", "deleted_by", "posted_by", "locked_by", "applied_by"})


class LegacyCompanyCleanupRefused(Exception):
    """Preflight menolak atau pemeriksaan pasca-buang gagal."""


@dataclass
class Scope:
    company_ids: list[int]
    location_ids: list[int]
    rows: "OrderedDict[str, set[int]]" = field(default_factory=OrderedDict)

    def count(self) -> dict[str, int]:
        return {label: len(ids) for label, ids in self.rows.items()}


def _m(label):
    return apps.get_model(label)


def _ids(label, q):
    return set(_m(label)._base_manager.filter(q).values_list("pk", flat=True))


def build_scope() -> Scope:
    Company = _m("administration.Company")
    L = sorted(Company._base_manager.filter(code__in=LEGACY_COMPANY_CODES).values_list("pk", flat=True))
    LL = sorted(_m("administration.Location")._base_manager.filter(company_id__in=L).values_list("pk", flat=True))
    by_company = Q(company_id__in=L)
    by_company_or_location = by_company | Q(location_id__in=LL)

    rows: OrderedDict[str, set[int]] = OrderedDict()

    wd = _ids("workflow.WorkflowDefinition",
              Q(code__in=LEGACY_WORKFLOW_DEFINITIONS) & (by_company | Q(location_id__in=LL)))
    ws = _ids("workflow.WorkflowStep", Q(definition_id__in=wd))
    rows["workflow.WorkflowStepFallback"] = _ids("workflow.WorkflowStepFallback", Q(step_id__in=ws))
    rows["workflow.WorkflowStep"] = ws
    rows["workflow.WorkflowDefinition"] = wd

    policies = _ids("finance.AccountingPolicy", by_company)
    rules = _ids("finance.AccountingPolicyRule", Q(policy_id__in=policies))
    rows["finance.AccountingPolicyLine"] = _ids("finance.AccountingPolicyLine", Q(rule_id__in=rules))
    rows["finance.AccountingPolicyRule"] = rules
    rows["finance.AccountingPolicy"] = policies
    rows["finance.AccountMapping"] = _ids("finance.AccountMapping", by_company)
    years = _ids("finance.FiscalYear", by_company)
    rows["finance.AccountingPeriod"] = _ids("finance.AccountingPeriod", Q(fiscal_year_id__in=years))
    rows["finance.FiscalYear"] = years
    rows["finance.Account"] = _ids("finance.Account", by_company)

    rows["payroll.PayrollSetting"] = _ids("payroll.PayrollSetting", by_company)
    rows["hr.LeaveGoLive"] = _ids("hr.LeaveGoLive", by_company)
    rows["hr.AttendanceDevice"] = _ids("hr.AttendanceDevice", by_company_or_location)
    rows["administration.AttendancePolicy"] = _ids("administration.AttendancePolicy", by_company_or_location)

    roster = _ids("administration.RosterPolicy", by_company_or_location)
    rows["administration.RosterTravelDay"] = _ids("administration.RosterTravelDay", Q(policy_id__in=roster))
    rows["administration.RosterShiftRotation"] = _ids("administration.RosterShiftRotation", Q(policy_id__in=roster))
    rows["administration.RosterPolicy"] = roster
    rows["administration.RosterCrew"] = _ids("administration.RosterCrew", by_company_or_location)

    HolidayCompany = _m("administration.HolidayCompany")
    selected = set()
    for holiday_id in HolidayCompany._base_manager.values_list("holiday_id", flat=True).distinct():
        companies = set(HolidayCompany._base_manager.filter(holiday_id=holiday_id).values_list("company_id", flat=True))
        if companies and companies <= set(L):
            selected.add(holiday_id)
    holidays = _ids("administration.Holiday", by_company_or_location | Q(pk__in=selected))
    rows["administration.HolidayCompany"] = _ids("administration.HolidayCompany", by_company | Q(holiday_id__in=holidays))
    rows["administration.Holiday"] = holidays
    rows["administration.WorkCalendar"] = _ids("administration.WorkCalendar", by_company_or_location)

    for label in ("Facility", "Position", "Section", "CostCenter", "Department", "Division"):
        rows[f"administration.{label}"] = _ids(f"administration.{label}", by_company)

    rows["administration.Location"] = set(LL)
    rows["administration.Branch"] = _ids("administration.Branch", by_company)
    rows["administration.Company"] = set(L)

    # Riwayat: ber-company/lokasi lama, atau tentang baris yang dibuang.
    audit_q = by_company_or_location
    for label, ids in rows.items():
        if ids and label != "administration.AuditTrail":
            model = _m(label)
            audit_q |= Q(module=model._meta.app_label, object_type=model._meta.model_name,
                         object_id__in=[str(pk) for pk in ids])
    rows["administration.AuditTrail"] = _ids("administration.AuditTrail", audit_q)

    # Urutan eksekusi.
    ordered = OrderedDict((label, rows.get(label, set())) for label in ORDER)

    return Scope(company_ids=L, location_ids=LL, rows=ordered)


# ======================================================================
# Preflight
# ======================================================================


def preflight(scope: Scope) -> list[str]:
    """Alasan menolak. Kosong = boleh dibuang. Hanya membaca."""
    problems: list[str] = []
    L, LL = scope.company_ids, scope.location_ids
    Company = _m("administration.Company")

    codes = set(Company._base_manager.values_list("code", flat=True))
    expected = set(OWNED_COMPANY_CODES) | set(LEGACY_COMPANY_CODES)
    if codes != expected:
        problems.append(f"COMPANY: himpunan company {sorted(codes)} ≠ {sorted(expected)} yang diaudit.")
    if len(L) != 3:
        problems.append(f"COMPANY: company lama ditemukan {len(L)} (harus 3).")

    if len(scope.rows["workflow.WorkflowDefinition"]) != len(LEGACY_WORKFLOW_DEFINITIONS):
        problems.append("ALUR: definisi alur lama tidak persis tiga yang diaudit.")

    def count(label, q):
        return _m(label)._base_manager.filter(q).count()

    checks = {
        "pegawai di company lama": ("hr.OrganizationAssignment", Q(company_id__in=L) | Q(location_id__in=LL)),
        "pegawai non-EMP di tenant": ("hr.Employee", ~Q(employee_number__regex=r"^EMP\d{3}$")),
        "run payroll company lama": ("payroll.PayrollRun", Q(company_id__in=L)),
        "periode payroll company lama": ("payroll.PayrollPeriod", Q(company_id__in=L)),
        "slip gaji company lama": ("payroll.Payslip", Q(company_id__in=L)),
        "AccountingEvent tenant": ("finance.AccountingEvent", Q()),
        "Journal tenant": ("finance.Journal", Q()),
        "JournalLine tenant": ("finance.JournalLine", Q()),
        "instance alur definisi lama": ("workflow.WorkflowInstance",
                                        Q(definition_id__in=scope.rows["workflow.WorkflowDefinition"])),
        "instance alur company lama": ("workflow.WorkflowInstance", Q(company_id__in=L)),
        "authority RBAC ke company lama": ("accounts.RoleAssignmentAuthority",
                                           Q(resource_type="company", resource_id__in=L)),
        "authority RBAC ke lokasi lama": ("accounts.RoleAssignmentAuthority",
                                          Q(resource_type="location", resource_id__in=LL)),
        "authority RBAC ke departemen lama": ("accounts.RoleAssignmentAuthority",
                                              Q(resource_type="department",
                                                resource_id__in=scope.rows["administration.Department"])),
    }
    for name, (label, q) in checks.items():
        n = count(label, q)
        if n:
            problems.append(f"TRANSAKSI/DEPENDENSI: {name} = {n}.")

    # Riwayat milik objek kanonik tidak pernah ikut.
    canon_audit = _m("administration.AuditTrail")._base_manager.filter(
        pk__in=scope.rows["administration.AuditTrail"], company__code__in=OWNED_COMPANY_CODES,
    ).count()
    if canon_audit:
        problems.append(f"RIWAYAT: {canon_audit} jejak audit ber-company kanonik masuk cakupan.")

    # Pegawai EMP yang masih merujuk objek lama (roster, kalender, organisasi).
    Employment = _m("hr.EmploymentAssignment")
    canonical = Employment._base_manager.filter(employee__employee_number__regex=r"^EMP\d{3}$")
    for fname, label in (("roster_policy", "administration.RosterPolicy"),
                         ("working_calendar", "administration.WorkCalendar")):
        n = canonical.filter(**{f"{fname}_id__in": scope.rows[label]}).count()
        if n:
            problems.append(f"KANONIK: {n} kepegawaian EMP masih merujuk {label} lama ({fname}).")

    # Setiap baris di luar cakupan yang menunjuk cakupan = belum diaudit.
    problems += unexpected_references(scope)

    # Model ber-FK company yang punya baris company lama tapi tidak dicakup.
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        label = model._meta.label
        for f in model._meta.concrete_fields:
            if f.is_relation and f.related_model is Company and label not in scope.rows:
                n = model._base_manager.filter(**{f"{f.attname}__in": L}).count()
                if n:
                    problems.append(f"CAKUPAN: {label}.{f.name} memuat {n} baris company lama — belum diaudit.")

    return problems


def unexpected_references(scope: Scope) -> list[str]:
    problems = []

    for label, ids in scope.rows.items():
        if not ids:
            continue
        model = _m(label)
        for rel in model._meta.get_fields(include_hidden=True):
            if not ((rel.one_to_many or rel.one_to_one) and rel.auto_created and not rel.concrete):
                continue
            related, fname = rel.related_model, rel.field.name
            if related._meta.proxy or not related._meta.managed or fname in AUDIT_COLUMNS:
                continue
            refs = related._base_manager.filter(**{f"{rel.field.attname}__in": ids})
            inside = scope.rows.get(related._meta.label)
            if inside is not None:
                refs = refs.exclude(pk__in=inside)
            if related._meta.auto_created:  # tabel M2M: ikut terbuang bersama induknya
                continue
            n = refs.count()
            if n:
                problems.append(
                    f"DEPENDENSI: {related._meta.label}.{fname} → {label}: {n} baris di luar cakupan "
                    f"({rel.field.remote_field.on_delete.__name__})."
                )

    return problems


# ======================================================================
# Eksekusi
# ======================================================================


def model_counts() -> dict[str, int]:
    counts = {}
    for model in apps.get_models(include_auto_created=True):
        if model._meta.proxy or not model._meta.managed:
            continue
        try:
            counts[model._meta.label] = model._base_manager.count()
        except Exception:  # tabel bukan milik schema ini
            continue
    return counts


def _through_expected(scope: Scope) -> dict[str, int]:
    """Baris M2M yang ikut terbuang karena induknya di cakupan."""
    expected = {}
    for label, ids in scope.rows.items():
        if not ids:
            continue
        for m2m in _m(label)._meta.many_to_many:
            through = m2m.remote_field.through
            if through._meta.auto_created:
                col = f"{m2m.m2m_field_name()}_id"
                expected[through._meta.label] = expected.get(through._meta.label, 0) + \
                    through._base_manager.filter(**{f"{col}__in": ids}).count()
    return expected


def execute(*, log) -> dict[str, int]:
    """Dipanggil di dalam `transaction.atomic()` pemanggil; gagal = lempar."""
    scope = build_scope()
    problems = preflight(scope)

    if problems:
        raise LegacyCompanyCleanupRefused("Pembuangan ditolak:\n  - " + "\n  - ".join(problems))

    expected = {label: len(ids) for label, ids in scope.rows.items()}
    for label, n in _through_expected(scope).items():
        expected[label] = expected.get(label, 0) + n

    before = model_counts()
    deleted: dict[str, int] = {}

    for label, ids in scope.rows.items():
        if not ids:
            continue
        model = _m(label)
        if label == "finance.Account":
            # Akun anak (parent PROTECT) lebih dulu, bertahap sampai habis.
            remaining = set(ids)
            while remaining:
                leaves = remaining - set(
                    model._base_manager.filter(parent_id__in=remaining).values_list("parent_id", flat=True)
                )
                if not leaves:
                    raise LegacyCompanyCleanupRefused("Akun lama membentuk siklus parent.")
                model._base_manager.filter(pk__in=leaves).delete()
                remaining -= leaves
            deleted[label] = len(ids)
        else:
            model._base_manager.filter(pk__in=ids).delete()
            deleted[label] = len(ids)
        log(f"   {label:40} {deleted[label]}")

    after = model_counts()
    unexpected = []
    for label, n in before.items():
        lost = n - after.get(label, 0)
        if lost != expected.get(label, 0):
            unexpected.append(f"{label}: berkurang {lost}, diharapkan {expected.get(label, 0)}")

    if unexpected:
        raise LegacyCompanyCleanupRefused(
            "Jumlah baris di luar dugaan (CASCADE tak terduga?):\n  - " + "\n  - ".join(unexpected)
        )

    # FK Django di PostgreSQL DEFERRABLE INITIALLY DEFERRED: paksa diperiksa sekarang.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")

    return deleted


def remaining_legacy() -> dict[str, int]:
    """Sisa baris company lama di model mana pun (verifikasi akhir)."""
    Company = _m("administration.Company")
    L = list(Company._base_manager.filter(code__in=LEGACY_COMPANY_CODES).values_list("pk", flat=True))
    found = {"administration.Company": len(L)}
    if not L:
        return found
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        for f in model._meta.concrete_fields:
            if f.is_relation and f.related_model is Company:
                n = model._base_manager.filter(**{f"{f.attname}__in": L}).count()
                if n:
                    found[f"{model._meta.label}.{f.name}"] = n
    return found
