from __future__ import annotations

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.responses.api import success_response
from apps.framework.introspection import build_ui_schema
from apps.framework.periods import DEFAULT_PERIOD_MODES, resolve_period
from apps.framework.views.ui_schema import UISchemaMixin


class BaseDashboardAPIView(UISchemaMixin, APIView):
    """
    Dashboard per modul: susunannya dideklarasikan di `schema`, datanya
    dihitung oleh method `resolve_<key>` untuk tiap widget.

    Satu request mengembalikan seluruh widget sekaligus. Satu endpoint
    per widget akan membuat halaman seperti di HR menembak 8 request
    berbarengan hanya untuk render pertama.

    Turunan cukup menulis:

        class HRDashboardAPIView(BaseDashboardAPIView):
            framework_module = "hr/dashboard"
            schema = HR_DASHBOARD_SCHEMA

            def resolve_total_employees(self, *, context, widget):
                ...

    Widget yang dideklarasikan di schema tapi tidak punya resolver akan
    memunculkan NotImplementedError saat diakses — sengaja berisik,
    supaya widget yang lupa diimplementasi tidak diam-diam kosong.

    **Cakupan data tidak ikut sendiri di sini.** `BaseMasterViewSet`
    menyaring cakupan data lewat `filter_queryset()`; dashboard
    adalah `APIView` biasa yang merakit querysetnya sendiri, jadi jalur
    itu tidak pernah dilewati. Tiap resolver wajib memanggil
    `DataScopeService.filter(queryset, <peta>, context["user"])` di
    setiap queryset yang dibangunnya — lihat `HRDashboardService`.

    Gagalnya diam dan menyesatkan: angka agregat tetap tampil, cuma
    menghitung baris yang pemakainya tidak berhak lihat. Selisih antara
    "Total Pegawai" di dashboard dan jumlah baris di tabel Employee
    justru memberi tahu berapa banyak yang disembunyikan.
    """

    schema_type = "dashboard"
    permission_classes = [IsAuthenticated]

    framework_module = None
    ui_schema = {}

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def get_period_filter(self) -> dict:
        for item in (self.ui_schema or {}).get("filters", []):
            if item.get("type") == "period":
                return item

        return {}

    def get_period(self, request) -> dict:
        """
        Membaca `?mode=&start=&end=` (harian/mingguan/bulanan/kustom)
        dengan `?year=&month=` sebagai jalur lama, lalu mengembalikan
        satu rentang tanggal siap pakai — lihat `apps.framework.periods`.

        Nilai yang tidak masuk akal diabaikan (jatuh ke default) daripada
        membalas error: dashboard tidak seharusnya gagal total gara-gara
        satu parameter salah ketik.
        """
        config = self.get_period_filter()

        modes = tuple(config.get("modes") or DEFAULT_PERIOD_MODES)
        default_mode = config.get("mode") or "month"

        return resolve_period(
            request.query_params,
            default_mode=default_mode,
            allowed_modes=modes,
        )

    def get_context(self, request) -> dict:
        context = {
            "request": request,
            "user": request.user,
            "period": self.get_period(request),
        }

        multi_keys = self.get_multi_filter_keys()

        for name in self.get_filter_keys():
            if name in multi_keys:
                values = self.expand_filter_values(
                    name,
                    self._multi_values(request, name),
                    request,
                )

                if values:
                    context[name] = values

                continue

            value = request.query_params.get(name)

            if value not in (None, ""):
                context[name] = value

        return context

    def expand_filter_values(self, name: str, values: list, request) -> list:
        """
        Kesempatan terakhir menerjemahkan pilihan pengguna sebelum
        resolver melihatnya.

        Dipasang **di sini**, bukan di tiap service, dan itu yang
        menentukan: HR Dashboard dan HR Period Summary sama-sama punya
        filter Location, dan aturan yang ditulis dua kali adalah cara
        paling pasti membuat satu tombol berperilaku berbeda di dua
        layar — selisih yang tidak akan pernah ada yang mencurigainya.

        Satu-satunya penerjemahan hari ini: bagi **direksi**, satu
        lokasi yang dipilih berarti seluruh lokasi ber-kode sama yang
        boleh ia lihat (`JKT-HO` milik dua belas perusahaan = satu
        pilihan, bukan dua belas centang). Untuk siapa pun selain
        direksi nilainya dikembalikan apa adanya.

        **Bukan penjagaan.** Yang diperluas cuma daftar id yang dipakai
        menyaring; `DataScopeService` pada queryset-nya tetap yang
        menutup. Id yang tidak dikenal atau di luar cakupan tidak jadi
        terbuka karena lewat sini.
        """
        if name != "location" or not values:
            return values

        from apps.accounts.board import expand_location_selection

        return expand_location_selection(
            getattr(request, "user", None),
            values,
        )

    @staticmethod
    def _multi_values(request, name: str) -> list[str]:
        """
        Dua bentuk diterima: `?k=1&k=2` dan `?k=1,2`.

        Yang kedua yang benar-benar dipakai — `useApi.buildUrl` di
        frontend meng-`String()` seluruh nilai query, jadi array Vue
        mendarat sebagai "1,2". Yang pertama diterima juga karena itu
        bentuk baku HTML form, dan menolaknya berarti pemanggil lain
        (skrip, laporan) gagal tanpa sebab yang jelas.

        Yang bukan angka dibuang diam-diam, sejalan dengan aturan
        dashboard: satu query param salah ketik tidak boleh mematikan
        seluruh halaman.
        """
        values: list[str] = []

        for raw in request.query_params.getlist(name):
            for piece in str(raw).split(","):
                piece = piece.strip()

                if piece.isdigit():
                    values.append(piece)

        return values

    def get_filter_keys(self) -> list[str]:
        return [
            item.get("key")
            for item in (self.ui_schema or {}).get("filters", [])
            if item.get("key") and item.get("type") != "period"
        ]

    def get_multi_filter_keys(self) -> set[str]:
        return {
            item.get("key")
            for item in (self.ui_schema or {}).get("filters", [])
            if item.get("key") and item.get("multiple")
        }

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------

    def get_widgets(self) -> list[dict]:
        return list((self.ui_schema or {}).get("widgets", []))

    def get_requested_widgets(self, request) -> list[dict]:
        """
        `?widget=a,b` — hanya widget itu yang dihitung dan dibalas.

        Ada karena satu widget bisa berpindah keadaan sendiri tanpa
        menyeret sisanya: tabel laporan yang dipaginasi berganti halaman
        puluhan kali sementara KPI dan chart di atasnya tidak berubah
        sama sekali. Tanpa ini tiap klik "halaman berikutnya" memuat
        ulang seluruh dashboard, dan enam kartu KPI berkedip jadi
        kerangka lalu kembali ke angka yang sama persis — terbaca
        seperti angkanya ikut dihitung ulang per halaman, padahal tidak.

        Nama yang tidak dikenal diabaikan, dan permintaan yang seluruh
        namanya tidak dikenal dilayani sebagai permintaan biasa: aturan
        yang sama dengan `get_period` — satu query param salah ketik
        tidak boleh mematikan halaman.
        """
        widgets = self.get_widgets()

        wanted: set[str] = set()

        for raw in request.query_params.getlist("widget"):
            for piece in str(raw).split(","):
                piece = piece.strip()

                if piece:
                    wanted.add(piece)

        if not wanted:
            return widgets

        selected = [item for item in widgets if item.get("key") in wanted]

        return selected or widgets

    def resolve_widget(self, widget: dict, context: dict):
        key = widget.get("key")

        resolver = getattr(self, f"resolve_{key}", None)

        if resolver is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} tidak punya "
                f"`resolve_{key}()` untuk widget '{key}' yang "
                f"dideklarasikan di schema."
            )

        return resolver(context=context, widget=widget)

    def get(self, request):
        context = self.get_context(request)

        data = {
            widget["key"]: self.resolve_widget(widget, context)
            for widget in self.get_requested_widgets(request)
            if widget.get("key")
        }

        return success_response(
            data={
                "period": context["period"],
                "widgets": data,
            },
            message="Dashboard berhasil dimuat.",
        )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema_response(self, request):
        return Response(build_ui_schema(self, request))

    @classmethod
    def as_schema_view(cls, **initkwargs):
        """
        Pasangan `<endpoint>/ui-schema/`, sejajar dengan action bawaan
        `BaseMasterViewSet`. `AllowAny` mengikuti endpoint schema lain:
        generator frontend harus bisa jalan tanpa login.

        `framework_module` dikosongkan pada subclass ini supaya
        `framework_schema_view` — yang mencari berdasarkan subclass —
        tidak menemukan dua kandidat untuk module yang sama.
        """

        class _SchemaView(cls):
            permission_classes = [AllowAny]
            framework_module = None
            ui_schema = cls.ui_schema

            def get(self, request):
                return self.get_schema_response(request)

        _SchemaView.__name__ = f"{cls.__name__}Schema"

        return _SchemaView.as_view(**initkwargs)
