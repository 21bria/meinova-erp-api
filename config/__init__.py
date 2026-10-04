"""
Paket konfigurasi proyek.

Berkas ini ada bukan sekadar penanda paket. Tanpa impor di bawah,
`config.celery` tidak pernah dimuat oleh proses web, sehingga
`@shared_task` terdaftar pada **app Celery bawaan** yang belum
dikonfigurasi — `broker_url`-nya `None`, dan celery jatuh ke default
`amqp://guest@localhost:5672//`.

Gejalanya menyesatkan: setiap `.delay()` gagal `[Errno 61] Connection
refused` padahal Redis sehat dan worker jalan normal — worker memang
selamat karena `celery -A config worker` mengimpor `config.celery`
secara eksplisit, sedangkan proses web tidak pernah.
"""

from .celery import app as celery_app


__all__ = ("celery_app",)
