"""
Menyambungkan jurnal ke engine approval generik.

Kotak masuk approval satu untuk semua modul, jadi saat approver menekan
Approve dari sana, engine perlu tahu apa yang harus terjadi pada
dokumennya. Engine tidak boleh menebak nama kolom status modul lain —
di sinilah Finance mendaftarkan pemetaannya sendiri.

Di-import dari `FinanceConfig.ready()`. Kalau lupa, tombol Approve
tetap jalan tapi status jurnalnya tidak ikut berpindah, dan gagalnya
diam.
"""

from __future__ import annotations

import logging

from apps.workflow.registry import register_completion, register_route


logger = logging.getLogger(__name__)


# Rute halaman dokumen di frontend, dipakai tombol "Buka dokumen" di
# kotak masuk dan layar monitoring. Wajib cocok dengan `app/pages/` di
# repo Nuxt — rute yang salah membuat tombolnya mendarat di 404.
register_route("finance", "journal", "/finance/journals/{id}/edit")


@register_completion("finance", "journal")
def journal_completed(instance, status):
    """
    Dipanggil saat alur persetujuan sebuah jurnal berhenti.

    **Tidak memposting.** Persetujuan memindahkan status ke APPROVED;
    yang membukukan tetap tindakan tersendiri. Menyatukannya
    menghilangkan kesempatan terakhir memeriksa — approver menyatakan
    jurnalnya benar, akuntan yang membukukannya.
    """
    from apps.finance.models import Journal
    from apps.finance.services import JournalService

    journal = (
        Journal.objects
        .filter(pk=instance.object_id, is_deleted=False)
        .first()
    )

    if journal is None:
        # Dokumen yang hilang setelah alurnya berjalan. Dicatat, bukan
        # dilempar: keputusan approver-nya sendiri sudah tersimpan, dan
        # menggagalkan transaksi di titik ini membatalkan persetujuan
        # yang sah gara-gara dokumen yang sudah tidak ada.
        logger.warning(
            "Workflow %s selesai tapi jurnal #%s tidak ditemukan.",
            instance.pk,
            instance.object_id,
        )

        return None

    return JournalService.apply_workflow_status(
        journal=journal,
        status=status,
        user=_final_actor(instance),
    )


def _final_actor(instance):
    """
    Siapa yang **memutuskan**, bukan siapa yang mengajukan.

    `instance.submitted_by` adalah pengaju, dan memakainya berarti
    `Journal.approved_by` mencatat orang yang meminta persetujuan
    sebagai orang yang memberikannya — jejak audit yang salah dengan
    cara yang tidak terlihat janggal di layar mana pun.

    `acted_by` lebih dulu daripada `approver`: kalau keputusannya
    diambil penerima kuasa, yang menekan tombol dialah yang tercatat.
    Baris keputusannya sendiri tetap atas nama approver yang seharusnya
    menandatangani — itu urusan engine, dan tidak diubah di sini.

    `None` kalau seluruh mejanya terlewat (semuanya SKIPPED). Itu
    keadaan yang sah, dan mengarangnya jadi pengaju justru mengisi
    kolom audit dengan tebakan.
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
