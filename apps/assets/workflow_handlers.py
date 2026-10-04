"""
Menyambungkan dokumen Asset Management ke engine approval generik.

Kotak masuk approval satu untuk semua modul; saat approver menekan
tombolnya dari sana, engine memanggil handler yang didaftarkan di sini.
Di-import dari `AssetsConfig.ready()` — kalau lupa, tombol Approve tetap
jalan tapi status dokumennya **tidak ikut berpindah**, dan gagalnya diam.
Dijaga test `test_workflow_registration`.
"""

from __future__ import annotations

import logging

from apps.workflow.registry import register_completion, register_route


logger = logging.getLogger(__name__)


# Rute halaman dokumen di frontend untuk tombol "Buka dokumen". Halamannya
# baru dibuat di ASSET-6; sampai saat itu tombolnya mendarat di 404 —
# rutenya didaftarkan sekarang supaya tidak terlupa saat halamannya ada.
register_route("assets", "asset_assignment", "/assets/assignments/{id}")
register_route("assets", "asset_return", "/assets/returns/{id}")
register_route("assets", "asset_transfer", "/assets/transfers/{id}")


def _final_actor(instance):
    """
    Siapa yang **memutuskan** — penerima kuasa lebih dulu, lalu approver.
    `None` bila seluruh meja terlewat.

    Aturan yang sama dengan `apps/finance/workflow_handlers._final_actor`,
    ditulis ulang di sini karena modul aset tidak boleh bergantung pada
    Finance. Kandidat untuk dipindah ke `apps/workflow` bila modul ketiga
    membutuhkannya.
    """
    row = (
        instance.approvals
        .filter(acted_at__isnull=False)
        .select_related("acted_by", "approver")
        .order_by("-acted_at", "-id")
        .first()
    )

    if row is None:
        return None

    return row.acted_by or row.approver


@register_completion("assets", "asset_assignment")
def asset_assignment_completed(instance, status):
    from apps.assets.models import AssetAssignment
    from apps.assets.services import AssetAssignmentService

    assignment = (
        AssetAssignment.objects
        .filter(pk=instance.object_id, is_deleted=False)
        .first()
    )

    if assignment is None:
        # Keputusan approver sudah tersimpan; menggagalkannya karena
        # dokumen yang hilang membatalkan persetujuan yang sah.
        logger.warning(
            "Workflow %s selesai tapi Asset Assignment #%s tidak ditemukan.",
            instance.pk,
            instance.object_id,
        )

        return None

    return AssetAssignmentService.on_workflow_done(
        assignment=assignment,
        status=status,
        user=_final_actor(instance),
    )


@register_completion("assets", "asset_return")
def asset_return_completed(instance, status):
    from apps.assets.models import AssetReturn
    from apps.assets.services import AssetReturnService

    asset_return = (
        AssetReturn.objects
        .filter(pk=instance.object_id, is_deleted=False)
        .first()
    )

    if asset_return is None:
        logger.warning(
            "Workflow %s selesai tapi Asset Return #%s tidak ditemukan.",
            instance.pk,
            instance.object_id,
        )

        return None

    return AssetReturnService.on_workflow_done(
        asset_return=asset_return,
        status=status,
        user=_final_actor(instance),
    )


@register_completion("assets", "asset_transfer")
def asset_transfer_completed(instance, status):
    from apps.assets.models import AssetTransfer
    from apps.assets.services import AssetTransferService

    transfer = (
        AssetTransfer.objects
        .filter(pk=instance.object_id, is_deleted=False)
        .first()
    )

    if transfer is None:
        logger.warning(
            "Workflow %s selesai tapi Asset Transfer #%s tidak ditemukan.",
            instance.pk,
            instance.object_id,
        )

        return None

    return AssetTransferService.on_workflow_done(
        transfer=transfer,
        status=status,
        user=_final_actor(instance),
    )
