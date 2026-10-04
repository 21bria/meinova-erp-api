"""
Aplikasi Reports — laporan lintas modul, READ ONLY.

Dipisah dari modul sumbernya dengan sengaja. Laporan manajemen membaca
Attendance, Leave, Overtime, Roster, dan Employee sekaligus; menaruhnya
di salah satu modul membuat empat modul lain menjadi ketergantungan
yang tidak kelihatan dari struktur berkasnya.

Tidak ada endpoint tulis di seluruh cabang ini.
"""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/",
        include("apps.reports.api.hr.urls"),
    ),
]
