"""
Kanal bel dalam aplikasi.

Menumpang `NotificationService` yang sudah ada — bukan menulis
`Notification.objects.create()` sendiri. Dedup per (user, module,
object_type, object_id) yang belum dibaca ada di sana, dan pengingat
harian yang melewatinya akan mengisi bel dengan tiga puluh salinan
pemberitahuan kontrak yang sama.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from ..constants import SKIP_TENANT_OFF, SKIP_USER_DISABLED, DeliveryStatus

logger = logging.getLogger(__name__)


# `Notification.TYPE_CHOICES` memakai huruf besar. Dipetakan dari nada
# event supaya modul pemanggil tidak perlu mengenal kosakata model
# notifikasi lama.
TONE_TO_TYPE = {
    "info": "INFO",
    "success": "SUCCESS",
    "warning": "WARNING",
    "error": "ERROR",
}


def send(log, *, config, title: str, message: str, link: str = "", tone: str = "info"):
    """Menulis satu baris notifikasi bel, lalu memperbarui log-nya."""
    from apps.administration.api.notification.services.notification_service import (
        NotificationService,
    )

    if not config.in_app_enabled:
        return _skip(log, SKIP_TENANT_OFF)

    if log.recipient is None:
        return _skip(log, "Baris log ini tidak punya penerima.")

    try:
        result = NotificationService.push(
            log.recipient,
            title=title[:150],
            message=message,
            type=TONE_TO_TYPE.get(str(tone).lower(), "INFO"),
            module=log.module or "",
            link=link or "",
            object_type=log.object_type or "",
            object_id=log.object_id or "",
        )
    except Exception as exc:  # noqa: BLE001
        log.status = DeliveryStatus.FAILED
        log.attempts = (log.attempts or 0) + 1
        log.detail = f"{type(exc).__name__}: {exc}"[:2000]

        log.save(update_fields=["status", "attempts", "detail"])

        logger.exception("Notifikasi bel %s gagal ditulis.", log.event)

        return False

    if result is None:
        # `push()` mengembalikan None kalau penerimanya mematikan
        # notifikasi dalam aplikasi. Itu bukan kegagalan.
        return _skip(log, SKIP_USER_DISABLED)

    log.status = DeliveryStatus.SENT
    log.attempts = (log.attempts or 0) + 1
    log.sent_at = timezone.now()
    log.subject = title[:255]

    log.save(update_fields=["status", "attempts", "sent_at", "subject"])

    return True


def _skip(log, reason: str) -> bool:
    log.status = DeliveryStatus.SKIPPED
    log.detail = reason

    log.save(update_fields=["status", "detail"])

    return False
