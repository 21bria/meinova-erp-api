"""
Read model riwayat aset (`docs/claude/assets.md` §8, §27) — **hanya baca**.

Tidak ada tabel riwayat kedua: custody dibaca dari `AssetCustody`, kondisi
dari `AssetConditionLog`, dan dokumen sumber dari `opened_by_*` /
`closed_by_*` pada custody. Yang ditambahkan di sini cuma terjemahan
pasangan `(type, id)` menjadi nomor dokumen + rute halaman yang bisa
ditampilkan — rute diambil dari registry workflow (`register_route` di
`workflow_handlers.py`), bukan ditulis ulang.

Pemanggil wajib sudah memastikan aset itu boleh dibaca (viewset lewat
`get_object()`); service ini tidak menyaring cakupan.
"""

from __future__ import annotations

from apps.assets.models import (
    AssetAssignment,
    AssetConditionLog,
    AssetCustody,
    AssetReturn,
    AssetTransfer,
)


REGISTRATION = "registration"

# `opened_by_type`/`closed_by_type` → (label, model dokumen).
DOCUMENT_SOURCES = {
    REGISTRATION: ("Registration", None),
    "asset_assignment": ("Assignment", AssetAssignment),
    "asset_return": ("Return", AssetReturn),
    "asset_transfer": ("Transfer", AssetTransfer),
}


class AssetHistoryService:
    @staticmethod
    def custody_rows(asset) -> list[AssetCustody]:
        """Seluruh periode custody aset, terbaru dulu."""
        return list(
            AssetCustody.objects
            .filter(asset=asset, is_deleted=False)
            .select_related(
                "employee",
                "department",
                "pic_employee",
                "location",
                "facility",
            )
            .order_by("-started_on", "-id")
        )

    @staticmethod
    def condition_rows(asset):
        """Riwayat kondisi append-only, terbaru dulu."""
        return (
            AssetConditionLog.objects
            .filter(asset=asset)
            .select_related("recorded_by")
            .order_by("-effective_at", "-id")
        )

    @classmethod
    def provenance(cls, rows: list[AssetCustody]) -> dict[tuple[str, str], dict]:
        """
        `{(type, id): {type, type_label, document_id, document_number,
        route}}` untuk setiap `opened_by_*`/`closed_by_*` di `rows`.

        Satu query per jenis dokumen, bukan per baris. Dokumen yang tidak
        ditemukan tetap dilaporkan jenisnya, tanpa nomor/rute.
        """
        from apps.workflow.registry import document_url

        wanted: dict[str, set[str]] = {}

        for row in rows:
            for kind, ident in (
                (row.opened_by_type, row.opened_by_id),
                (row.closed_by_type, row.closed_by_id),
            ):
                if kind:
                    wanted.setdefault(kind, set()).add(ident)

        resolved: dict[tuple[str, str], dict] = {}

        for kind, idents in wanted.items():
            label, model = DOCUMENT_SOURCES.get(kind, (kind, None))

            numbers: dict[str, str] = {}

            if model is not None:
                keys = [ident for ident in idents if str(ident).isdigit()]
                numbers = {
                    str(pk): number
                    for pk, number in model.objects
                    .filter(pk__in=keys)
                    .values_list("pk", "document_number")
                }

            for ident in idents:
                found = model is not None and str(ident) in numbers

                resolved[(kind, ident)] = {
                    "type": kind,
                    "type_label": label,
                    "document_id": int(ident) if found else None,
                    "document_number": numbers.get(str(ident)) if found else None,
                    "route": (
                        document_url(
                            module="assets",
                            document_type=kind,
                            object_id=ident,
                        )
                        if found
                        else None
                    ),
                }

        return resolved
