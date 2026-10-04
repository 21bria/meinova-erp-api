"""
Sepuluh skenario trial Attendance Permission, dijalankan ujung ke ujung
pada tenant `demo`.

Data uji dibuat dengan awalan `UATP-` dan **dihapus lagi di akhir**,
berhasil maupun gagal. Tenant demo dipakai orang untuk hal lain; UAT
yang meninggalkan pegawai karangan membuat setiap laporan headcount
sesudahnya salah tanpa ada yang tahu sebabnya.

Shift-nya dibuat sendiri (08:00–17:00 dan 20:00–05:00) karena angka di
spesifikasi terikat pada jam itu — memakai shift demo yang kebetulan
10:00–18:00 berarti menguji angka yang berbeda lalu menyebutnya lulus.

**Tidak satu angka pun dihitung di sini.** Yang dibandingkan nilai dari
API dengan nilai yang ditulis spesifikasi.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from django_tenants.utils import schema_context  # noqa: E402

API = os.environ.get("UAT_API", "http://demo.localhost:8000")
USER = os.environ.get("UAT_USER", "admin")
PASS = os.environ.get("UAT_PASS", "")

if not PASS:
    sys.exit("UAT_PASS environment variable is required.")

WALL = ZoneInfo("Asia/Jakarta")
TRIAL = date(2026, 9, 8)          # Selasa
PREFIX = "UATP-"

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


def eq(label, actual, expected):
    check(label, actual == expected, f"dapat {actual!r}, harap {expected!r}")


def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL)


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------

TOKEN = ""


def call(path, method="GET", body=None):
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"null")
        except Exception:
            return exc.code, {"raw": raw.decode(errors="replace")}


def unwrap(payload):
    return payload.get("data", payload) if isinstance(payload, dict) else payload


# ----------------------------------------------------------------------
# Panggung
# ----------------------------------------------------------------------

def build():
    from apps.administration.models import Company, Location, WorkCalendar
    from apps.administration.models.references.hr_attendance import Shift
    from apps.hr.models import Employee, EmploymentAssignment, OrganizationAssignment

    company = Company.objects.filter(is_deleted=False).order_by("id").first()
    location = Location.objects.filter(company=company, is_deleted=False).order_by("id").first()

    # Kebijakan kehadiran khusus UAT, **nol toleransi**.
    #
    # Tenant demo memberi kelonggaran 1 menit lewat `ATT-STD`
    # (`late_tolerance_minutes=1`, dihitung dari toleransi), jadi
    # keterlambatan 120 menit tercatat 119. Itu konfigurasi hidup yang
    # sah — dan justru karena itu angka di spesifikasi tidak bisa
    # diuji terhadapnya: yang diuji jadi kebijakan tenant, bukan mesin
    # hitungnya.
    #
    # Skornya 6 (company + location), mengalahkan `ATT-STD` yang 0.
    from apps.administration.models import AttendancePolicy

    AttendancePolicy.objects.get_or_create(
        code=f"{PREFIX}ZERO",
        defaults=dict(
            company=company, location=location,
            name="UAT zero tolerance",
            late_tolerance_minutes=0,
            late_counts_from_tolerance=True,
            early_leave_tolerance_minutes=0,
        ),
    )

    calendar, _ = WorkCalendar.objects.get_or_create(
        code=f"{PREFIX}CAL",
        defaults=dict(
            company=company, name="UAT Mon-Fri",
            monday=True, tuesday=True, wednesday=True,
            thursday=True, friday=True, saturday=False, sunday=False,
        ),
    )

    day, _ = Shift.objects.get_or_create(
        code=f"{PREFIX}DAY",
        defaults=dict(name="UAT Day 08-17", start_time=time(8, 0),
                      end_time=time(17, 0), crosses_midnight=False),
    )
    night, _ = Shift.objects.get_or_create(
        code=f"{PREFIX}NIGHT",
        defaults=dict(name="UAT Night 20-05", start_time=time(20, 0),
                      end_time=time(5, 0), crosses_midnight=True),
    )

    made = {}
    for key, shift in (("day", day), ("night", night)):
        for i in range(1, 7):
            number = f"{PREFIX}{key[:1].upper()}{i:02d}"
            emp = Employee.objects.filter(employee_number=number).first()
            if emp is None:
                emp = Employee.objects.create(
                    employee_number=number,
                    first_name="UAT", last_name=f"{key.title()} {i}",
                )
                OrganizationAssignment.objects.create(
                    employee=emp, company=company, location=location,
                    organization_effective_date=date(2020, 1, 6),
                )
                EmploymentAssignment.objects.create(
                    employee=emp, join_date=date(2020, 1, 6),
                    working_calendar=calendar, shift=shift,
                )
            made[f"{key}{i}"] = Employee.objects.get(pk=emp.pk)

    return made, day, night


def teardown():
    from apps.administration.models import WorkCalendar
    from apps.administration.models.references.hr_attendance import Shift
    from apps.hr.models import (
        AttendancePermission, Employee, EmployeeAttendance,
        EmploymentAssignment, OrganizationAssignment,
    )
    from apps.workflow.models import WorkflowInstance

    emps = Employee.objects.filter(employee_number__startswith=PREFIX)
    ids = [str(p) for p in AttendancePermission.objects.filter(employee__in=emps).values_list("pk", flat=True)]

    WorkflowInstance.objects.filter(
        module="hr", document_type="attendance_permission", object_id__in=ids,
    ).delete()
    AttendancePermission.objects.filter(employee__in=emps).delete()
    EmployeeAttendance.objects.filter(employee__in=emps).delete()
    EmploymentAssignment.objects.filter(employee__in=emps).delete()
    OrganizationAssignment.objects.filter(employee__in=emps).delete()
    emps.delete()
    Shift.objects.filter(code__startswith=PREFIX).delete()
    WorkCalendar.objects.filter(code__startswith=PREFIX).delete()

    from apps.administration.models import AttendancePolicy
    AttendancePolicy.objects.filter(code__startswith=PREFIX).delete()


# ----------------------------------------------------------------------

def permission(employee, kind, *, start=None, end=None, approved=True, status=None):
    from apps.hr.api.attendance_permission.services import AttendancePermissionService
    from apps.hr.models import AttendancePermissionStatus

    row = AttendancePermissionService.create(data={
        "employee": employee, "permission_type": kind, "date": TRIAL,
        "start_time": start, "end_time": end, "reason": "UAT",
    })

    target = status or (
        AttendancePermissionStatus.APPROVED if approved
        else AttendancePermissionStatus.DRAFT
    )

    if target != AttendancePermissionStatus.DRAFT:
        AttendancePermissionService._set_status(permission=row, status=target)
        AttendancePermissionService.recalculate_attendance(permission=row)

    row.refresh_from_db()
    return row


def attendance(employee, *, shift, check_in=None, check_out=None, status=None, crosses=False):
    from apps.hr.api.attendance.services import EmployeeAttendanceService

    end_day = TRIAL + timedelta(days=1) if crosses else TRIAL

    data = {
        "employee": employee, "work_date": TRIAL, "shift": shift,
        "scheduled_check_in": at(TRIAL, shift.start_time.hour, shift.start_time.minute),
        "scheduled_check_out": at(end_day, shift.end_time.hour, shift.end_time.minute),
        "check_in": check_in, "check_out": check_out,
    }
    if status:
        data["status"] = status

    return EmployeeAttendanceService.create(data=data)


def run():
    global TOKEN

    status, auth = call("/api/accounts/auth/login/", "POST",
                        {"username": USER, "password": PASS})
    TOKEN = (auth or {}).get("access", "")
    check("Login API", bool(TOKEN), f"status {status}")
    if not TOKEN:
        return

    with schema_context("demo"):
        from apps.hr.models import AttendanceStatus, AttendancePermissionStatus, AttendancePermissionType as T

        emps, day, night = build()

        # 01 — hadir normal
        a = attendance(emps["day1"], shift=day, check_in=at(TRIAL, 7, 55), check_out=at(TRIAL, 17, 5))
        eq("S01 hadir normal: tanpa telat", a.late_minutes, 0)
        eq("S01 hadir normal: tanpa penanda izin", a.permission_state, "")

        # 02 — telat tanpa izin
        a = attendance(emps["day2"], shift=day, check_in=at(TRIAL, 10, 0), check_out=at(TRIAL, 17, 0))
        eq("S02 telat tanpa izin: menit telat", a.late_minutes, 120)
        eq("S02 telat tanpa izin: tanpa izin", a.unauthorized_late_minutes, 120)
        eq("S02 telat tanpa izin: klasifikasi", a.permission_state, "unauthorized")

        # 03 — telat dengan izin
        permission(emps["day3"], T.LATE_ARRIVAL, end=time(10, 0))
        a = attendance(emps["day3"], shift=day, check_in=at(TRIAL, 9, 55), check_out=at(TRIAL, 17, 0))
        eq("S03 telat berizin: menit telat utuh", a.late_minutes, 115)
        eq("S03 telat berizin: dimaafkan", a.excused_late_minutes, 115)
        eq("S03 telat berizin: klasifikasi", a.permission_state, "excused")

        # 04 — KRITIS: datang melewati batas izin
        p4 = permission(emps["day4"], T.LATE_ARRIVAL, end=time(10, 0))
        a4 = attendance(emps["day4"], shift=day, check_in=at(TRIAL, 10, 30), check_out=at(TRIAL, 17, 0))
        eq("S04 KRITIS: late_minutes", a4.late_minutes, 150)
        eq("S04 KRITIS: excused", a4.excused_late_minutes, 120)
        eq("S04 KRITIS: unauthorized", a4.unauthorized_late_minutes, 30)
        eq("S04 KRITIS: klasifikasi", a4.permission_state, "partial")

        # 05 — pulang cepat berizin
        permission(emps["day5"], T.EARLY_LEAVE, start=time(15, 0))
        a = attendance(emps["day5"], shift=day, check_in=at(TRIAL, 8, 0), check_out=at(TRIAL, 15, 5))
        eq("S05 pulang cepat berizin: dimaafkan", a.excused_early_leave_minutes, 115)
        eq("S05 pulang cepat berizin: tanpa izin", a.unauthorized_early_leave_minutes, 0)

        # 06 — keluar sementara
        permission(emps["day6"], T.TEMPORARY_OUT, start=time(13, 0), end=time(15, 0))
        a = attendance(emps["day6"], shift=day, check_in=at(TRIAL, 8, 0), check_out=at(TRIAL, 17, 0))
        eq("S06 keluar sementara: menit izin", a.permission_minutes, 120)
        eq("S06 keluar sementara: presensi utuh", a.status, AttendanceStatus.PRESENT)

        # 07 — izin sehari
        permission(emps["night1"], T.FULL_DAY)
        a = attendance(emps["night1"], shift=night, status=AttendanceStatus.ABSENT, crosses=True)
        eq("S07 izin sehari: ada izin", a.is_excused_absence, True)
        eq("S07 izin sehari: bukan mangkir", a.is_unauthorized_absence, False)

        # 08 — izin ditolak
        permission(emps["night2"], T.LATE_ARRIVAL, end=time(22, 0),
                   status=AttendancePermissionStatus.REJECTED)
        a = attendance(emps["night2"], shift=night, check_in=at(TRIAL, 22, 0),
                       check_out=at(TRIAL + timedelta(days=1), 5, 0), crosses=True)
        eq("S08 izin ditolak: tidak memaafkan", a.excused_late_minutes, 0)
        eq("S08 izin ditolak: klasifikasi", a.permission_state, "unauthorized")

        # 09 — izin masih berjalan
        permission(emps["night3"], T.LATE_ARRIVAL, end=time(22, 0),
                   status=AttendancePermissionStatus.SUBMITTED)
        a = attendance(emps["night3"], shift=night, check_in=at(TRIAL, 21, 0),
                       check_out=at(TRIAL + timedelta(days=1), 5, 0), crosses=True)
        eq("S09 izin berjalan: belum memaafkan", a.excused_late_minutes, 0)
        eq("S09 izin berjalan: badge menunggu", a.permission_state, "pending")

        # 10 — KRITIS: shift malam melewati tengah malam
        p10 = permission(emps["night4"], T.TEMPORARY_OUT, start=time(23, 30), end=time(1, 0))
        eq("S10 KRITIS: durasi izin lintas tengah malam", p10.duration_minutes, 90)
        a10 = attendance(emps["night4"], shift=night, check_in=at(TRIAL, 20, 0),
                         check_out=at(TRIAL + timedelta(days=1), 5, 0), crosses=True)
        eq("S10 KRITIS: menit izin di presensi", a10.permission_minutes, 90)

        # --- kontrak API yang dibaca layar ------------------------------
        code, payload = call(f"/api/hr/attendance-permissions/{p4.pk}/")
        detail = unwrap(payload)

        check("Detail API 200", code == 200, f"status {code}")
        check("Detail membawa blok `shift`", isinstance(detail.get("shift"), dict))
        check("Detail membawa blok `attendance`", isinstance(detail.get("attendance"), dict))
        check("Detail membawa blok `approval` (None sebelum diajukan)", "approval" in detail)
        check("Detail membawa `conflicts`", isinstance(detail.get("conflicts"), list))

        att = detail.get("attendance") or {}
        eq("Detail S04: late_minutes dari backend", att.get("late_minutes"), 150)
        eq("Detail S04: excused dari backend", att.get("excused_late_minutes"), 120)
        eq("Detail S04: unauthorized dari backend", att.get("unauthorized_late_minutes"), 30)

        code, payload = call("/api/hr/attendance-permissions/?page_size=50")
        listed = unwrap(payload)
        listed = listed.get("results", listed) if isinstance(listed, dict) else listed

        check("Daftar API 200", code == 200, f"status {code}")
        mine = [r for r in listed if str(r.get("employee_number", "")).startswith(PREFIX)]
        check("Daftar memuat izin UAT", len(mine) >= 6, f"{len(mine)} baris")

        if mine:
            r = mine[0]
            check("Daftar punya `time_window`", "time_window" in r)
            check("Daftar punya `current_approver`", "current_approver" in r)
            check("Daftar tidak membawa blok berat `attendance`", r.get("attendance") is None)
            check("Daftar tidak membawa blok berat `approval`", r.get("approval") is None)


try:
    with schema_context("demo"):
        teardown()
    run()
finally:
    with schema_context("demo"):
        teardown()

    ok = sum(1 for _, o, _ in results if o)
    bad = [r for r in results if not r[1]]
    print("")
    print(f"Hasil: {ok} PASS, {len(bad)} FAIL")
    for label, _, detail in bad:
        print(f"  - {label} ({detail})")

    sys.exit(1 if bad else 0)
