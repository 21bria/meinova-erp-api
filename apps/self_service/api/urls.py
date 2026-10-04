from django.urls import path

from apps.self_service.api.avatar import SelfAvatarView
from apps.self_service.api.punch import SelfAttendancePunchView
from apps.self_service.api.views import (
    SelfAttendancePermissionRequestView,
    SelfAttendanceView,
    SelfContextView,
    SelfLeaveRequestView,
    SelfProfileView,
    SelfScheduleView,
    SelfWorkspaceView,
)


app_name = "self_service"

urlpatterns = [
    # Tidak ada satu pun rute ber-parameter identitas di berkas ini, dan
    # itu bukan kebetulan: `/api/me/profile/<employee_id>/` adalah bentuk
    # yang membuat `/me` berhenti berarti "saya".
    path("", SelfContextView.as_view(), name="context"),

    # Foto pegawai yang sedang login. Tanpa pengenal apa pun di rutenya,
    # dan itu bagian dari penjagaannya — bukan kerapian.
    path("avatar/", SelfAvatarView.as_view(), name="avatar"),

    path("profile/", SelfProfileView.as_view(), name="profile"),

    # Ringkasan hari kerja. Rutenya pun tanpa parameter — lihat
    # catatan di atas.
    path("workspace/", SelfWorkspaceView.as_view(), name="workspace"),

    # Presensi per periode. Parameternya rentang dan halaman; tidak ada
    # yang menyebut pegawai, di rutenya maupun di query string-nya.
    path("attendance/", SelfAttendanceView.as_view(), name="attendance"),

    # Tap kehadiran untuk diri sendiri. Hanya POST, tanpa id di rute;
    # body yang menyebut pegawai ditolak. Mati bawaannya
    # (`ATTENDANCE_SELF_PUNCH_ENABLED`) dan gagal tertutup selama
    # pemeriksaan wajibnya belum terpasang.
    path(
        "attendance/punch/",
        SelfAttendancePunchView.as_view(),
        name="attendance-punch",
    ),

    # Jadwal shift sendiri. Parameternya rentang saja (`month`, atau
    # `start`/`end`) — sama seperti presensi, tidak ada yang menyebut
    # pegawai.
    path("schedule/", SelfScheduleView.as_view(), name="schedule"),

    # Pengajuan pribadi. Hanya POST, tanpa id di rute, dan body yang
    # menyebut pegawai ditolak — subjeknya selalu akun yang login.
    path(
        "leave-requests/",
        SelfLeaveRequestView.as_view(),
        name="leave-requests",
    ),
    path(
        "attendance-permissions/",
        SelfAttendancePermissionRequestView.as_view(),
        name="attendance-permissions",
    ),
]
