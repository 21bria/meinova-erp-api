"""
Notifikasi generik: in-app + email, satu mesin untuk seluruh modul.

Pemakaian dari modul mana pun::

    from apps.notifications import notify

    notify(
        event="hr.contract_end",
        context={"employee_name": "Budi", "end_date": "30 Sep 2026"},
        subject_employee=employee,
        link=f"/hr/employees/{employee.pk}",
        dedup_key=f"hr.contract_end:{employee.pk}:{end_date}",
    )

Yang **tidak** boleh dilakukan modul: memanggil `django.core.mail`
sendiri. Email yang dikirim di luar mesin ini tidak punya template yang
bisa disunting, tidak punya aturan penerima, tidak masuk log, dan tidak
menghormati setelan notifikasi penggunanya.

Menambah event baru: daftarkan `NotificationEvent` lewat
`register_event()` dari `AppConfig.ready()` modul Anda. Lihat
`apps/notifications/events.py` sebagai contoh lengkap.
"""

default_app_config = "apps.notifications.apps.NotificationsConfig"


def notify(**kwargs):
    """
    Pintu masuk tunggal. Impor tertunda supaya modul ini aman di-import
    dari `models.py` mana pun tanpa memicu pemuatan ORM lebih awal.
    """
    from .dispatcher import notify as _notify

    return _notify(**kwargs)
