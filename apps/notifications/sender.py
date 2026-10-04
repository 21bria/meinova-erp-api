"""
Pengiriman satu baris log yang sudah dirakit.

Dipisah dari `tasks.py` supaya bisa dipanggil tanpa Celery — perintah
manajemen, pengujian, dan tombol "Kirim Ulang" di layar log memakai
fungsi yang sama dengan worker. Kalau jalurnya berbeda, yang diuji
bukan yang berjalan di produksi.
"""

from __future__ import annotations

import logging

from .constants import Channel, DeliveryStatus
from .models import NotificationConfig, NotificationLog

logger = logging.getLogger(__name__)


def deliver_email(log_id: int) -> bool:
    """
    Mengirim satu baris log email.

    Mengembalikan True kalau terkirim. Baris yang sudah `SENT`
    dikembalikan True tanpa dikirim ulang — task Celery bisa diulang
    (`acks_late` menyala di setelan proyek ini, jadi worker yang mati di
    tengah membuat task-nya diantre ulang), dan tanpa penjagaan ini
    penerimanya mendapat surat yang sama dua kali.
    """
    log = (
        NotificationLog.objects
        .select_related("recipient")
        .filter(pk=log_id, channel=Channel.EMAIL)
        .first()
    )

    if log is None:
        # Bukan kesalahan yang bisa diperbaiki dengan mengulang: barisnya
        # memang tidak ada. Dicatat supaya "email tidak terkirim" tetap
        # punya jejak.
        logger.warning("Baris log notifikasi %s tidak ditemukan.", log_id)

        return False

    if log.status == DeliveryStatus.SENT:
        return True

    from .channels import email as email_channel

    config = NotificationConfig.resolve()

    return email_channel.send(
        log,
        config=config,
        subject=log.subject,
        body_text=log.body,
        action_url=log.action_url,
    )


def retry_failed(*, event: str = "", limit: int = 100) -> dict:
    """
    Mengirim ulang baris yang gagal.

    Sengaja **tidak** menyentuh yang berstatus `SKIPPED`: itu keputusan
    yang benar (penerimanya mematikan email, alamatnya kosong), dan
    mengulanginya cuma menghasilkan baris dilewati yang sama. Yang perlu
    diperbaiki datanya, bukan pengirimannya.
    """
    queryset = NotificationLog.objects.filter(
        channel=Channel.EMAIL,
        status=DeliveryStatus.FAILED,
    )

    if event:
        queryset = queryset.filter(event=str(event).strip().lower())

    rows = list(queryset.order_by("id")[: max(1, int(limit))])

    sent = 0

    for log in rows:
        if deliver_email(log.id):
            sent += 1

    return {"attempted": len(rows), "sent": sent, "failed": len(rows) - sent}
