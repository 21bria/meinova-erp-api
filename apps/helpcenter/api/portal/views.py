"""
Endpoint Help Center sisi pembaca.

`APIView` biasa, bukan viewset: bentuknya bukan CRUD dan tidak ada
yang perlu digenerate darinya. Penjagaannya cuma `IsAuthenticated` —
artikel panduan bukan data pegawai, dan mengunci halaman bantuan di
balik izin model berarti orang yang paling butuh bantuan (pegawai
dengan izin paling sedikit) yang paling tidak bisa membukanya.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses.api import error_response, success_response
from apps.helpcenter.services import HelpPortalService


class HelpPortalView(APIView):
    """
    GET /api/helpcenter/portal/

    Seluruh isi Help Center dalam satu request: daftar modul (untuk
    tab) beserta kategori dan artikelnya (tanpa isi lengkap).

    `?module=hr` ada untuk pemanggil API, tapi **frontend tidak
    memakainya**: seluruh pohonnya kecil dan sudah ikut di respons ini,
    jadi pindah tab disaring di klien. Menembak satu request tiap kali
    orang menekan tab membuat layar bantuan terasa berat justru saat
    penggunanya sedang bingung.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        module = request.query_params.get("module") or None

        return success_response(
            data={
                "modules": HelpPortalService.modules(request.user),
                "categories": HelpPortalService.tree(
                    request.user,
                    module=module,
                ),
            },
            message="Help center loaded.",
        )


class HelpArticleDetailView(APIView):
    """
    GET /api/helpcenter/portal/articles/<slug>/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug: str):
        data = HelpPortalService.detail(
            request.user,
            slug=slug,
            # Diturunkan dari request, bukan dari settings: host
            # backend berbeda per tenant (subdomain) dan per
            # lingkungan, dan menaruhnya di settings berarti satu
            # tenant selalu menunjuk host tenant lain.
            media_base=request.build_absolute_uri("/").rstrip("/"),
        )

        if data is None:
            return error_response(
                message="Artikel tidak ditemukan.",
                status_code=404,
            )

        # Dicatat setelah artikelnya benar-benar ketemu dan boleh
        # dibaca — kalau tidak, slug yang ditebak-tebak ikut menaikkan
        # penghitung artikel yang bahkan tidak dikembalikan.
        HelpPortalService.record_view(slug=slug)

        return success_response(
            data=data,
            message="Article loaded.",
        )


class HelpSearchView(APIView):
    """
    GET /api/helpcenter/portal/search/?q=cuti
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "")

        results = HelpPortalService.search(request.user, query=query)

        return success_response(
            data={
                "query": query,
                "results": results,
            },
            meta={"count": len(results)},
            message="Search completed.",
        )


class HelpContextualView(APIView):
    """
    GET /api/helpcenter/portal/contextual/?route=/hr/leave

    Panduan untuk layar yang sedang dibuka — yang menyalakan tombol
    Help di pojok tiap halaman.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        route = request.query_params.get("route", "")

        results = HelpPortalService.contextual(request.user, route=route)

        return success_response(
            data={
                "route": route,
                "results": results,
            },
            meta={"count": len(results)},
            message="Contextual help loaded.",
        )


class HelpFeedbackView(APIView):
    """
    POST /api/helpcenter/portal/articles/<slug>/feedback/

    Body: {"is_helpful": true, "comment": "..."}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug: str):
        raw = request.data.get("is_helpful")

        if isinstance(raw, str):
            raw = raw.strip().lower() in {"true", "1", "yes", "ya"}

        if not isinstance(raw, bool):
            return error_response(
                message="Kolom `is_helpful` wajib diisi true atau false.",
                errors={"is_helpful": ["Wajib diisi true atau false."]},
            )

        result = HelpPortalService.submit_feedback(
            request.user,
            slug=slug,
            is_helpful=raw,
            comment=request.data.get("comment", ""),
        )

        if result is None:
            return error_response(
                message="Artikel tidak ditemukan.",
                status_code=404,
            )

        return success_response(
            data=result,
            message="Terima kasih atas masukannya.",
        )
