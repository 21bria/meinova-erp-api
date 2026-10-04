"""
Reports → HR.

Satu berkas per keluarga laporan. Attendance/Leave/Overtime/Roster/
Travel Report menyusul di sini, bukan di modul HR-nya: yang membedakan
laporan dari layar transaksi adalah ia **hanya membaca**, dan memisahkan
rutenya membuat batas itu terlihat dari daftar URL saja.
"""

from django.urls import include, path


urlpatterns = [
    path(
        "",
        include("apps.reports.api.hr.period_summary.urls"),
    ),
    path(
        "",
        include("apps.reports.api.hr.employee_reporting_audit.urls"),
    ),
    path(
        "",
        include("apps.reports.api.hr.manpower_summary.urls"),
    ),
    path(
        "",
        include("apps.reports.api.hr.contract_expiry.urls"),
    ),
    path(
        "",
        include("apps.reports.api.hr.manpower_movement.urls"),
    ),
]
