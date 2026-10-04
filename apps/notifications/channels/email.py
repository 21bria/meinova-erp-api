"""
Kanal email.

Satu berkas ini satu-satunya tempat di codebase yang benar-benar
memanggil `django.core.mail`. Modul lain memanggil dispatcher; kalau ada
yang memanggil `send_mail` sendiri, template dan penerima email itu
tidak bisa dikonfigurasi dari layar mana pun, dan itu persis keadaan
yang sedang diperbaiki.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe

from ..constants import (
    SKIP_GLOBAL_OFF,
    SKIP_NO_ADDRESS,
    SKIP_TENANT_OFF,
    SKIP_USER_DISABLED,
    DeliveryStatus,
)

logger = logging.getLogger(__name__)


def address_for(user) -> str:
    """
    Alamat email seorang penerima.

    Urutannya `User.email` → `work_email` pegawainya → `personal_email`.
    Email kantor didahulukan atas email pribadi dengan sengaja:
    pemberitahuan kontrak dan dokumen persetujuan adalah surat dinas,
    dan mengirimkannya ke alamat pribadi seseorang bukan keputusan yang
    boleh diambil sistem sendiri. Email pribadi tetap jadi jatuhan
    terakhir — pegawai site lazim tidak punya alamat kantor sama sekali,
    dan tidak punya alamat berarti tidak pernah diberi tahu apa pun.
    """
    direct = str(getattr(user, "email", "") or "").strip()

    if direct:
        return direct

    employee = getattr(user, "employee_profile", None)

    if employee is None:
        return ""

    for attribute in ("work_email", "personal_email"):
        value = str(getattr(employee, attribute, "") or "").strip()

        if value:
            return value

    return ""


def _recipient_allows_email(user) -> bool:
    from apps.administration.api.notification.services.notification_service import (
        NotificationSettingService,
    )

    setting = NotificationSettingService.get_settings(user)

    return bool(setting.email_enabled)


def build_message(
    *,
    config,
    subject: str,
    body_text: str,
    to: str,
    action_url: str = "",
    action_label: str = "",
) -> EmailMultiAlternatives:
    """
    Merakit satu email siap kirim dari isi berbentuk **teks**.

    Dua bagian: teks biasa dan HTML. Yang teks bukan formalitas —
    sebagian klien email di lapangan (dan hampir semua notifikasi di
    jam tangan) menampilkan bagian itu, dan email yang bagian teksnya
    kosong terbaca sebagai pesan kosong.

    Bagian teks memakai isi aslinya, **bukan** hasil `striptags` dari
    versi HTML-nya. Sudah kena sekali: `striptags` membuang `</p><p>`
    tanpa menyisakan pemisah, jadi seluruh surat menempel jadi satu
    paragraf panjang tanpa satu pun baris baru.
    """
    from ..render import to_html

    context = {
        "subject": subject,
        # `to_html()` meng-escape isinya lebih dulu, jadi menandainya
        # aman di sini benar. Yang belum di-escape tidak pernah sampai
        # ke titik ini.
        "body_html": mark_safe(to_html(body_text)),
        "body_text": body_text,
        "app_name": config.resolved_app_name,
        "logo_url": config.logo_url,
        "base_url": config.resolved_base_url,
        "footer_text": config.footer_text,
        "action_url": action_url,
        "action_label": action_label or "Buka di aplikasi",
    }

    html = render_to_string("email/base.html", context)
    text = render_to_string("email/base.txt", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=config.resolved_sender or None,
        to=[to],
    )

    if config.reply_to:
        message.reply_to = [config.reply_to]

    message.attach_alternative(html, "text/html")

    return message


def send(log, *, config, subject: str, body_text: str, action_url: str = ""):
    """
    Mengirim satu baris log, lalu memperbaruinya.

    **Tidak pernah melempar.** Kegagalan ditulis ke barisnya sendiri dan
    dikembalikan sebagai `False`; pemanggilnya (task Celery) yang
    memutuskan diulang atau tidak. Melempar dari sini akan menjatuhkan
    seluruh batch hanya karena satu alamat yang salah ketik.
    """
    if not getattr(settings, "NOTIFICATION_EMAIL_ENABLED", True):
        return _skip(log, SKIP_GLOBAL_OFF)

    if not config.email_enabled:
        return _skip(log, SKIP_TENANT_OFF)

    if log.recipient_id and not _recipient_allows_email(log.recipient):
        return _skip(log, SKIP_USER_DISABLED)

    if not log.recipient_email:
        return _skip(log, SKIP_NO_ADDRESS)

    # Pengalihan lingkungan bukan produksi. Alamat aslinya **tetap**
    # tercatat di barisnya — kalau ditimpa, log jadi tidak berguna untuk
    # memeriksa siapa yang seharusnya menerima.
    redirect_to = str(
        getattr(settings, "NOTIFICATION_EMAIL_REDIRECT_TO", "") or ""
    ).strip()

    target = redirect_to or log.recipient_email

    try:
        message = build_message(
            config=config,
            subject=subject,
            body_text=body_text,
            to=target,
            action_url=action_url,
        )

        connection = get_connection(fail_silently=False)
        message.connection = connection
        message.send()
    except Exception as exc:  # noqa: BLE001 - lihat docstring
        log.status = DeliveryStatus.FAILED
        log.attempts = (log.attempts or 0) + 1
        log.detail = f"{type(exc).__name__}: {exc}"[:2000]

        log.save(update_fields=["status", "attempts", "detail"])

        logger.warning(
            "Email notifikasi %s ke %s gagal: %s",
            log.event,
            log.recipient_email,
            exc,
        )

        return False

    log.status = DeliveryStatus.SENT
    log.attempts = (log.attempts or 0) + 1
    log.sent_at = timezone.now()
    log.subject = subject[:255]
    log.detail = (
        f"Dialihkan ke {redirect_to} (NOTIFICATION_EMAIL_REDIRECT_TO)."
        if redirect_to
        else ""
    )

    log.save(
        update_fields=["status", "attempts", "sent_at", "subject", "detail"],
    )

    return True


def _skip(log, reason: str) -> bool:
    log.status = DeliveryStatus.SKIPPED
    log.detail = reason

    log.save(update_fields=["status", "detail"])

    return False
