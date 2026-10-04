"""
Fondasi endpoint Self Service.

Isi payload-nya sengaja **seminimal mungkin** di stage ini: yang diuji
fondasinya — resolver, permission, dan pendaftaran URL — bukan bentuk
akhir profilnya. Profil lengkap punya kontraknya sendiri
(`SelfProfileSerializer`, Stage 4) dan foto punya resolusinya sendiri
(Stage 3); keduanya menempel di sini tanpa mengubah kelas mana pun.
"""

from rest_framework.views import APIView

from apps.core.responses.api import success_response
from apps.self_service.api.exception_handler import (
    self_service_exception_handler,
)
from apps.self_service.api.profile import SelfProfileSerializer
from apps.self_service.api.serializers import SelfIdentitySerializer
from apps.self_service.api.workspace import SelfWorkspaceSerializer
from apps.self_service.permissions import IsSelfServiceEmployee
from apps.self_service.services import CurrentEmployeeService
from apps.self_service.services.attendance import SelfAttendanceService
from apps.self_service.services.workspace import SelfWorkspaceService


class SelfServiceAPIView(APIView):
    """
    Induk seluruh endpoint `/api/me/*`.

    Turunannya membaca `self.employee` dan **tidak pernah** membaca
    identitas dari `request.query_params`, `kwargs`, atau body. Tidak ada
    jalur yang menerimanya, jadi tidak ada jalur yang bisa lupa
    memeriksanya.
    """

    permission_classes = [IsSelfServiceEmployee]

    def get_exception_handler(self):
        """
        Balasan galat `/me` membawa `code` yang stabil.

        Hanya untuk turunan kelas ini; endpoint lain tidak berubah
        sebaris pun.
        """
        return self_service_exception_handler

    @property
    def employee(self):
        # Sudah diselesaikan permission class pada request yang sama;
        # panggilan ini membaca cache-nya, bukan query kedua.
        return CurrentEmployeeService.for_request(self.request)


class SelfContextView(SelfServiceAPIView):
    """
    `GET /api/me/` — identitas pegawai yang sedang login.

    Jawaban atas satu pertanyaan: "siapa saya di sistem ini, dan apakah
    saya punya ruang Self Service". Itu yang dibutuhkan shell aplikasi
    sebelum tahu menu `/me` mana yang layak ditampilkan.
    """

    def get(self, request):
        return success_response(
            data=SelfIdentitySerializer(
                self.employee,
                # Tanpa `request` di context, alamat fotonya terkirim
                # sebagai jalur relatif — dan frontend berdiri di origin
                # yang berbeda dari API, jadi jalur relatif itu menunjuk
                # ke dirinya sendiri lalu gagal tanpa pesan.
                context={"request": request},
            ).data,
        )


class SelfProfileView(SelfServiceAPIView):
    """
    `GET /api/me/profile/` — profil lengkap pegawai yang sedang login.

    Kontraknya `SelfProfileSerializer`: daftar putih eksplisit, berseksi,
    dan **tidak** diturunkan dari schema HR. Itu yang membuatnya tetap
    berdiri saat Employee Master bertambah kolom.

    Tidak ada varian ber-parameter. `/api/me/profile/<employee_id>/`
    tidak ada dan tidak akan dibuat.
    """

    def get(self, request):
        return success_response(
            data=SelfProfileSerializer(
                self.employee,
                context={"request": request},
            ).data,
        )


class SelfWorkspaceView(SelfServiceAPIView):
    """
    `GET /api/me/workspace/` — ringkasan hari kerja pegawai yang sedang
    login.

    **Lapisan agregasi.** Tidak satu pun model, perhitungan, atau alur
    yang pindah ke sini: jadwal tetap milik Roster/Shift, presensi dan
    cuti tetap milik HR, persetujuan tetap milik Workflow, slip tetap
    milik Payroll. Yang dikerjakan endpoint ini cuma memanggil
    ketujuhnya untuk **satu** pegawai — yang sedang login — lalu
    membentuk satu jawaban.

    Seperti seluruh `/api/me/*`: tidak ada parameter identitas. Tidak
    ada `?employee=`, tidak ada `<employee_id>` di rutenya, dan body
    tidak dibaca sama sekali. Subjeknya selalu
    `CurrentEmployeeService.for_request(request)`.
    """

    def get(self, request):
        employee = self.employee

        return success_response(
            data=SelfWorkspaceSerializer(
                employee,
                workspace=SelfWorkspaceService.build(
                    employee=employee,
                    user=request.user,
                ),
                context={"request": request},
            ).data,
        )


class SelfAttendanceView(SelfServiceAPIView):
    """
    `GET /api/me/attendance/` — presensi pegawai yang sedang login, per
    periode.

    Pelengkap `/api/me/workspace/`, bukan penggantinya: yang satu
    menjawab "hari ini bagaimana", yang ini "periode ini bagaimana".

    **Empat parameter, dan tidak satu pun menyebut orang.**
    `date_from`, `date_to`, `page`, `page_size` — itu saja yang dibaca.
    `?employee=`, `?employee_id=`, `?user=`, dan kerabatnya tidak punya
    cabang yang membacanya, jadi tidak ada cabang yang bisa lupa
    memeriksanya; subjeknya tetap `CurrentEmployeeService.for_request()`
    seperti seluruh `/api/me/*`.

    Rentang dan paginasi **wajib** dan dikerjakan database. Tanpa
    parameter, jawabannya tujuh hari terakhir — bukan seluruh histori.
    """

    def get(self, request):
        data, meta = SelfAttendanceService.build(
            employee=self.employee,
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
            page=request.query_params.get("page"),
            page_size=request.query_params.get("page_size"),
        )

        return success_response(data=data, meta=meta)


class SelfScheduleView(SelfServiceAPIView):
    """
    `GET /api/me/schedule/?month=YYYY-MM` — kalender shift pegawai yang
    sedang login. Juga menerima `start`/`end`; tanpa keduanya, bulan
    berjalan menurut jam dinding kantor.

    **Adapter tipis, bukan kalender kedua.** Rentangnya dibaca helper
    yang sama dengan `GET /api/hr/shift-calendar/`, sel-selnya dirakit
    `ShiftCalendarService` yang sama, dan bentuk balasannya
    `ShiftCalendarSerializer` yang sama — layar Shift Calendar
    merendernya tanpa cabang.

    Yang berbeda hanya **siapa subjeknya**. Endpoint HR menerima
    `?employee=` lalu mengujinya terhadap cakupan baca
    (`viewable_employees`); di sini tidak ada parameter itu sama sekali.
    `?employee=`, `?employee_id=`, `?user=`, `?employee_number=` tidak
    punya cabang yang membacanya — subjeknya selalu
    `CurrentEmployeeService.for_request()`. Cakupan data tidak
    ditanyakan: "baris ini memang dirinya" tidak bisa dipersempit
    cakupan, dan tidak boleh dilebarkan olehnya.
    """

    def get(self, request):
        from apps.hr.api.shift_calendar.views import (
            build_calendar_payload,
            resolve_calendar_range,
        )

        start, end = resolve_calendar_range(
            request.query_params,
            today=SelfWorkspaceService.today(),
        )

        return success_response(
            data=build_calendar_payload(self.employee, start, end),
        )


class SelfRequestView(SelfServiceAPIView):
    """
    Induk `POST /api/me/leave-requests/` dan
    `POST /api/me/attendance-permissions/`.

    **Adapter tulis tipis.** Subjeknya `self.employee`, validasi bentuk
    milik serializer HR, dan seluruh aturan — saldo, hitungan hari,
    tumpang tindih, jendela shift, periode, penomoran, workflow — milik
    service domain. Lihat `apps/self_service/services/requests.py`.

    Hanya `POST`. Membaca, menyunting, dan menarik kembali dokumennya
    tetap lewat layar/alur yang sudah ada.
    """

    http_method_names = ["post", "options"]

    spec = None

    def post(self, request):
        from apps.self_service.services.requests import SelfRequestService

        data = SelfRequestService.create(
            spec=self.spec,
            employee=self.employee,
            user=request.user,
            payload=request.data,
            request=request,
        )

        return success_response(
            data=data,
            message="Pengajuan dikirim.",
            status_code=201,
        )


class SelfLeaveRequestView(SelfRequestView):
    """`POST /api/me/leave-requests/` — Ajukan Cuti untuk diri sendiri."""

    @property
    def spec(self):
        from apps.self_service.services.requests import LEAVE_REQUEST

        return LEAVE_REQUEST


class SelfAttendancePermissionRequestView(SelfRequestView):
    """`POST /api/me/attendance-permissions/` — Ajukan Izin untuk diri sendiri."""

    @property
    def spec(self):
        from apps.self_service.services.requests import (
            ATTENDANCE_PERMISSION_REQUEST,
        )

        return ATTENDANCE_PERMISSION_REQUEST
