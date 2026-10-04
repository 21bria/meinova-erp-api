"""
Task pengiriman notifikasi.

Nama task berawalan `notifications.` — itu yang dicocokkan
`CELERY_TASK_ROUTES` untuk melemparkannya ke antrean tersendiri. Kalau
awalannya diubah, task-nya diam-diam kembali ke antrean bawaan dan satu
berkas import 20.000 baris kembali menahan pemberitahuan approval di
belakangnya.

`schema_name` **selalu** argumen pertama. Worker tidak mewarisi schema
dari pemanggilnya — pola yang sama dengan `run_attendance_import` dan
`send_employee_reminders`.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


@shared_task(
    name="notifications.send_email",
    bind=True,
    max_retries=None,
    acks_late=True,
)
def send_email_notification(self, schema_name: str, log_id: int):
    """
    Mengirim satu email.

    Diulang dengan jeda kalau gagal, sampai batas `NOTIFICATION_MAX_RETRIES`.
    Kegagalan SMTP lazimnya sementara (rate limit, koneksi putus), jadi
    menyerah di percobaan pertama membuang pemberitahuan yang sebenarnya
    tinggal diulang.

    Setelah batasnya habis, task **berhenti tanpa melempar**: barisnya
    sudah bertanda `FAILED` beserta pesannya di layar log, dan task yang
    terus gagal berisik cuma memenuhi antrean ulangan tanpa ada yang
    memperbaiki datanya.
    """
    from .sender import deliver_email

    try:
        with schema_context(schema_name):
            ok = deliver_email(log_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Task email notifikasi %s (tenant %s) gagal.",
            log_id,
            schema_name,
        )

        ok = False
        error = exc
    else:
        error = None

    if ok:
        return {"schema": schema_name, "log": log_id, "sent": True}

    max_retries = int(getattr(settings, "NOTIFICATION_MAX_RETRIES", 3))

    if self.request.retries >= max_retries:
        logger.warning(
            "Email notifikasi %s (tenant %s) menyerah setelah %s percobaan.",
            log_id,
            schema_name,
            self.request.retries + 1,
        )

        return {
            "schema": schema_name,
            "log": log_id,
            "sent": False,
            "gave_up": True,
        }

    raise self.retry(
        exc=error,
        countdown=int(getattr(settings, "NOTIFICATION_RETRY_DELAY", 60)),
    )


@shared_task(name="notifications.retry_failed")
def retry_failed_notifications(schema_name: str, limit: int = 100):
    """
    Menyapu baris yang gagal untuk satu tenant.

    Belum dijadwalkan otomatis — dijalankan manual atau lewat tombol di
    layar log. Menjadwalkannya berarti memutuskan berapa lama sebuah
    kegagalan pantas diulang, dan itu bergantung penyedia SMTP-nya.
    """
    from .sender import retry_failed

    with schema_context(schema_name):
        return {"schema": schema_name, **retry_failed(limit=limit)}
