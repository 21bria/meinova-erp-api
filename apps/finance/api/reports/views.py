"""
Laporan buku besar — Trial Balance dan Account Ledger.

`APIView`, bukan viewset: keduanya tidak punya baris yang bisa dibuat
atau dihapus. Konsekuensinya **cakupan data harus dipasang sendiri** —
`BaseMasterViewSet.filter_queryset()` tidak ikut ke sini, dan tanpa
panggilan eksplisit seluruh angka buku besar terbuka untuk siapa pun
yang bisa membuka layarnya. Itu dilakukan di dalam
`LedgerQueryService.base_queryset()`, satu tempat untuk kedua laporan.
"""

from __future__ import annotations

# `PermissionDenied` milik DRF, bukan milik Django. Yang kedua
# memang diterjemahkan `exception_handler` jadi 403, tapi lewat
# jalur yang bergantung pada `exc.args` ikut terbawa — dan pesan
# yang hilang di sini adalah satu-satunya kalimat yang memberi tahu
# orangnya izin mana yang kurang.
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses.api import success_response
from apps.finance.services import (
    AccountLedgerQueryService,
    TrialBalanceQueryService,
)

from .serializers import LedgerFilterSerializer


# Izin baca buku besar. Dipakai dua arah — menolak request di sini, dan
# memilih role mana yang menyumbang cakupan di
# `LedgerQueryService.apply_scope`. Satu nama izin untuk kedua
# pertanyaan; kalau keduanya menyusunnya sendiri-sendiri, satu
# perubahan nama model menggeser salah satunya saja.
LEDGER_VIEW_PERMISSION = "finance.view_journalline"


class BaseLedgerReportView(APIView):
    permission_classes = [IsAuthenticated]

    def resolve_filters(self, request):
        if not (
            request.user.is_superuser
            or request.user.has_perm(LEDGER_VIEW_PERMISSION)
        ):
            raise PermissionDenied(
                "Anda belum punya wewenang membaca buku besar. Minta "
                "administrator menambahkan izin 'Can view journal line' "
                "ke role Anda."
            )

        payload = LedgerFilterSerializer(data=request.query_params)
        payload.is_valid(raise_exception=True)

        return payload.to_filters(request.query_params)


class TrialBalanceView(BaseLedgerReportView):
    def get(self, request):
        filters = self.resolve_filters(request)

        report = TrialBalanceQueryService.build(filters, user=request.user)

        return success_response(
            data=report,
            message=(
                "Trial balance is in balance."
                if report["is_balanced"]
                else (
                    "Trial balance does NOT reconcile — difference "
                    f"{report['difference']}. Periksa jurnal yang "
                    "barisnya tidak seimbang."
                )
            ),
            meta={
                "count": len(report["rows"]),
                "date_from": report["date_from"],
                "date_to": report["date_to"],
            },
        )


class AccountLedgerView(BaseLedgerReportView):
    def get(self, request):
        filters = self.resolve_filters(request)

        try:
            limit = min(int(request.query_params.get("limit", 200)), 1000)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            limit, offset = 200, 0

        report = AccountLedgerQueryService.build(
            filters,
            user=request.user,
            limit=limit,
            offset=offset,
        )

        return success_response(
            data=report,
            message="Account ledger.",
            meta={
                "count": report["count"],
                "limit": report["limit"],
                "offset": report["offset"],
            },
        )
