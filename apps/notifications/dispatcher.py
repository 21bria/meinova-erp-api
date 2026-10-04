"""
Pintu masuk tunggal untuk seluruh pemberitahuan.

Modul mana pun memanggil `notify(...)` dan berhenti di situ — tidak ada
modul yang mengurus template, penerima, kanal, dedup, atau log sendiri.
Itu yang membuat satu layar konfigurasi berlaku untuk seluruh aplikasi,
dan itu juga alasan `send_mail` tidak boleh muncul di luar
`channels/email.py`.

Tiga sifat yang harus tetap dijaga:

- **Tidak pernah menjatuhkan pemanggilnya.** Seluruh badan dibungkus
  savepoint sendiri dan kegagalannya hanya dicatat. Pengajuan cuti yang
  gagal karena servernya tidak bisa mengirim email adalah kesalahan
  yang jauh lebih besar daripada email yang tidak terkirim. Savepoint
  wajib, bukan sekadar `try/except`: exception di dalam transaksi induk
  membuat transaksi itu tidak bisa di-commit lagi **meski** exception-nya
  ditangkap — pelajaran yang sama dengan `BaseService._audit`.

- **Email diantre, bel ditulis langsung.** Bel cuma satu INSERT dan
  harus sudah terlihat saat penggunanya menyegarkan halaman; email lewat
  jaringan ke server orang lain dan tidak boleh menahan request.

- **Antreannya dijadwalkan `on_commit`.** Tanpa itu worker bisa
  mengambil task sebelum transaksi pemanggilnya commit, lalu mencari
  baris log yang belum ada — dan gagalnya terbaca sebagai email yang
  hilang secara acak. Konsekuensinya callback itu jalan **di luar**
  savepoint sifat pertama, jadi ia harus menjaga dirinya sendiri —
  lihat `_queue()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import recipients as recipient_resolver
from . import render as renderer
from .constants import (
    SKIP_NOT_IMPLEMENTED,
    Channel,
    DeliveryStatus,
    IMPLEMENTED_CHANNELS,
    RecipientType,
)
from .models import EmailTemplate, NotificationConfig, NotificationLog, NotificationRule
from .registry import UnknownEvent, get_event

logger = logging.getLogger(__name__)


@dataclass
class _DefaultRule:
    """
    Aturan bawaan dari registry, dibentuk saat tenant belum mengatur
    apa pun.

    Bentuknya sengaja meniru `NotificationRule` supaya resolver penerima
    tidak perlu tahu bedanya — dan supaya bawaannya **tidak** ditulis ke
    database. Menulisnya saat dibaca membuat "belum pernah mengatur"
    jadi keadaan yang tidak bisa dibedakan lagi, dan bawaan yang berubah
    besok tidak akan pernah sampai ke tenant lama. Pelajaran yang sama
    dengan `FavoriteApp.DEFAULT_CODES` dan susunan widget beranda.
    """

    recipient_type: str
    role: Any = None
    user: Any = None
    manager_level: int = 1
    send_in_app: bool = True
    send_email: bool = True


def _default_rules(event) -> list[_DefaultRule]:
    from apps.accounts.models import Role

    rules: list[_DefaultRule] = []

    channels = set(event.default_channels)
    in_app = Channel.IN_APP in channels
    email = Channel.EMAIL in channels

    for kind in event.default_recipients:
        if kind == RecipientType.ROLE:
            # Role bawaan disebut lewat **kode**, bukan id: registry
            # ditulis sekali untuk seluruh tenant, dan id role berbeda
            # di tiap schema.
            for code in event.default_roles:
                role = (
                    Role.objects
                    .filter(code=code, is_deleted=False)
                    .first()
                )

                if role is None:
                    # Role yang belum ada di tenant ini dilewati, bukan
                    # menggagalkan seluruh pengiriman — tenant yang
                    # belum menjalankan seed role tetap harus menerima
                    # pemberitahuan lewat jalur lain.
                    logger.debug(
                        "Role bawaan %s untuk event %s belum ada di "
                        "tenant ini.",
                        code,
                        event.code,
                    )

                    continue

                rules.append(
                    _DefaultRule(
                        recipient_type=kind,
                        role=role,
                        send_in_app=in_app,
                        send_email=email,
                    ),
                )

            continue

        rules.append(
            _DefaultRule(
                recipient_type=kind,
                send_in_app=in_app,
                send_email=email,
            ),
        )

    return rules


@dataclass
class DispatchResult:
    event: str = ""
    created: int = 0
    sent: int = 0
    skipped: int = 0
    queued: int = 0
    duplicates: int = 0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "event": self.event,
            "created": self.created,
            "sent": self.sent,
            "skipped": self.skipped,
            "queued": self.queued,
            "duplicates": self.duplicates,
            "reasons": self.reasons,
        }


def _absolute(base_url: str, link: str) -> str:
    """
    Tautan relatif → alamat penuh.

    Email dibuka di klien email, bukan di dalam aplikasi, jadi
    `/hr/leave/12` di sana tidak menunjuk apa pun. Yang sudah absolut
    dibiarkan — pemanggil boleh mengirim alamat lengkap kalau tujuannya
    di luar aplikasi.
    """
    target = str(link or "").strip()

    if not target:
        return ""

    if target.startswith(("http://", "https://")):
        return target

    return f"{base_url.rstrip('/')}/{target.lstrip('/')}"


def _build_context(
    *,
    event,
    config,
    user,
    context: Mapping[str, Any],
    action_url: str,
) -> dict[str, Any]:
    """
    Konteks lengkap untuk satu penerima.

    Placeholder umum diisi di sini, bukan oleh pemanggil: kalau tiap
    pemanggil harus mengingatnya, cepat atau lambat ada email yang kaki
    suratnya kosong atau menyapa orang tanpa nama.

    Nilai dari pemanggil ditaruh **terakhir** supaya bisa menimpa yang
    umum — event yang punya company sendiri (dokumen milik perusahaan
    lain dari penerimanya) harus bisa menyebutkan company itu.
    """
    full_name = ""

    if user is not None:
        getter = getattr(user, "get_full_name", None)
        full_name = (getter() if callable(getter) else "") or getattr(
            user, "username", ""
        )

    return {
        "recipient_name": full_name,
        "recipient_first_name": full_name.split(" ")[0] if full_name else "",
        "app_name": config.resolved_app_name,
        "company_name": config.resolved_app_name,
        "base_url": config.resolved_base_url,
        "action_url": action_url,
        "today": timezone.localdate(),
        **dict(context or {}),
    }


def notify(
    *,
    event: str,
    context: Mapping[str, Any] | None = None,
    subject_employee=None,
    submitter=None,
    pending_approvers: Iterable = (),
    preparers: Iterable = (),
    company=None,
    module: str = "",
    object_type: str = "",
    object_id: str = "",
    link: str = "",
    dedup_key: str = "",
    tone: str = "info",
    only_recipient_types: Iterable[str] | None = None,
    send_now: bool = False,
) -> DispatchResult:
    """
    Memicu satu event notifikasi.

    `only_recipient_types` **mempersempit**, tidak pernah memperluas.
    Dipakai modul yang punya kebijakannya sendiri soal siapa yang layak
    diberi tahu — `EmployeeReminderPolicy.notify_employee`, misalnya,
    yang bawaannya mati karena tidak semua perusahaan ingin pegawainya
    diberi tahu langsung soal kontraknya. Tanpa parameter ini, kebijakan
    itu dan `NotificationRule` jadi dua sumber kebenaran untuk
    pertanyaan yang sama, dan yang menang ditentukan urutan kode.

    Arahnya sengaja satu: aturan boleh dipersempit modul, tapi modul
    tidak bisa menambahkan penerima yang tidak dideklarasikan di layar
    Notification Rules — kalau bisa, layar itu berhenti menjawab
    "siapa saja yang menerima ini".

    `dedup_key` kosong = tidak pernah didedup, dan itu benar untuk
    kejadian yang memang bisa berulang (dokumen yang sama diajukan ulang
    setelah ditarik). Untuk pengingat berkala **wajib diisi**, kalau
    tidak tugas hariannya mengirim ulang setiap hari.

    `send_now=True` mengirim email di proses ini juga, tanpa Celery.
    Dipakai perintah manajemen dan pengujian; jalur API dan task selalu
    mengantre.
    """
    result = DispatchResult(event=str(event))

    try:
        # Savepoint — lihat sifat pertama di docstring modul.
        with transaction.atomic():
            _dispatch(
                result=result,
                event=event,
                context=context or {},
                subject_employee=subject_employee,
                submitter=submitter,
                pending_approvers=list(pending_approvers or ()),
                preparers=list(preparers or ()),
                company=company,
                module=module,
                object_type=object_type,
                object_id=object_id,
                link=link,
                dedup_key=dedup_key,
                tone=tone,
                only_recipient_types=(
                    set(only_recipient_types)
                    if only_recipient_types is not None
                    else None
                ),
                send_now=send_now,
            )
    except UnknownEvent:
        # Ini kesalahan pemrograman, bukan keadaan data — dan
        # menelannya berarti pemberitahuan yang tidak pernah terkirim
        # tanpa ada yang tahu. Tetap dicatat berisik, tapi tidak
        # dilempar ke pemanggil: dokumen tetap harus bisa disimpan.
        logger.exception("Event notifikasi tidak terdaftar: %s", event)

        result.reasons.append(f"Event '{event}' tidak terdaftar.")
    except Exception:  # noqa: BLE001
        logger.exception("Pengiriman notifikasi %s gagal seluruhnya.", event)

        result.reasons.append("Pengiriman gagal, lihat log server.")

    return result


def _dispatch(
    *,
    result: DispatchResult,
    event: str,
    context: Mapping[str, Any],
    subject_employee,
    submitter,
    pending_approvers: list,
    preparers: list,
    company,
    module: str,
    object_type: str,
    object_id: str,
    link: str,
    dedup_key: str,
    tone: str,
    only_recipient_types: set[str] | None,
    send_now: bool,
) -> None:
    spec = get_event(event)
    config = NotificationConfig.resolve()

    code = spec.code

    # Aturan tenant kalau ada barisnya, bawaan registry kalau belum.
    # Pembedanya **ada barisnya**, bukan ada yang aktif — yang sengaja
    # menonaktifkan seluruh barisnya memang berarti tidak ada yang
    # menerima, dan itu harus dihormati.
    if NotificationRule.is_configured(code, company=company):
        rules = NotificationRule.resolve(code, company=company)
    else:
        rules = _default_rules(spec)

    if not rules:
        result.reasons.append(
            "Tidak ada aturan penerima aktif untuk event ini.",
        )

        return

    if only_recipient_types is not None:
        narrowed = [
            rule
            for rule in rules
            if rule.recipient_type in only_recipient_types
        ]

        # Yang tersaring dilaporkan, bukan dibuang diam-diam: aturan
        # yang sudah ditulis orang di layar lalu tidak pernah berlaku
        # adalah keadaan yang harus punya jejak.
        for rule in rules:
            if rule.recipient_type not in only_recipient_types:
                result.reasons.append(
                    f"Penerima '{rule.recipient_type}' dimatikan oleh "
                    "kebijakan modul untuk event ini.",
                )

        rules = narrowed

        if not rules:
            return

    pairs: list[tuple[object, set[str], str]] = []

    for rule in rules:
        users, skipped = recipient_resolver.resolve(
            rule,
            subject_employee=subject_employee,
            submitter=submitter,
            pending_approvers=pending_approvers,
            preparers=preparers,
        )

        result.reasons.extend(skipped)

        channels = set()

        if rule.send_in_app:
            channels.add(Channel.IN_APP)

        if rule.send_email:
            channels.add(Channel.EMAIL)

        label = str(
            getattr(rule, "get_recipient_type_display", None)
            and rule.get_recipient_type_display()
            or rule.recipient_type
        )

        for user in users:
            pairs.append((user, channels, label))

    targets = recipient_resolver.merge(pairs)

    if not targets:
        return

    template = EmailTemplate.resolve(code, company=company)
    action_url = _absolute(config.resolved_base_url, link)

    subject_source = template.subject if template else spec.default_subject
    body_source = template.body if template else spec.default_body

    email_log_ids: list[int] = []

    for target in targets:
        full_context = _build_context(
            event=spec,
            config=config,
            user=target.user,
            context=context,
            action_url=action_url,
        )

        subject, _err = renderer.safe_render(
            subject_source,
            full_context,
            label=f"{code}.subject",
        )

        body_text, _err = renderer.safe_render(
            body_source,
            full_context,
            label=f"{code}.body",
        )

        for channel in sorted(target.channels):
            log = _create_log(
                result=result,
                event=code,
                user=target.user,
                channel=channel,
                module=module or spec.module,
                object_type=object_type,
                object_id=object_id,
                dedup_key=dedup_key,
                subject=subject,
                body=body_text,
                action_url=action_url,
                reason=target.reason,
            )

            if log is None:
                continue

            if channel not in IMPLEMENTED_CHANNELS:
                log.status = DeliveryStatus.SKIPPED
                log.detail = SKIP_NOT_IMPLEMENTED

                log.save(update_fields=["status", "detail"])

                result.skipped += 1

                continue

            if channel == Channel.IN_APP:
                from .channels import in_app

                title = (
                    template.in_app_title
                    if template and template.in_app_title
                    else subject
                )

                if template and template.in_app_title:
                    title, _err = renderer.safe_render(
                        template.in_app_title,
                        full_context,
                        label=f"{code}.in_app_title",
                    )

                short = subject

                if template and template.in_app_body:
                    short, _err = renderer.safe_render(
                        template.in_app_body,
                        full_context,
                        label=f"{code}.in_app_body",
                    )
                else:
                    short = " ".join(str(body_text).split())[:200]

                ok = in_app.send(
                    log,
                    config=config,
                    title=title,
                    message=short,
                    link=link,
                    tone=tone,
                )

                result.sent += 1 if ok else 0
                result.skipped += 0 if ok else 1

                continue

            # Email: barisnya sudah ada, pengirimannya diantre.
            email_log_ids.append(log.id)

    if not email_log_ids:
        return

    if send_now:
        from .sender import deliver_email

        for log_id in email_log_ids:
            if deliver_email(log_id):
                result.sent += 1
            else:
                result.skipped += 1

        return

    _queue(email_log_ids)

    result.queued += len(email_log_ids)


def _queue(log_ids: list[int]) -> None:
    """
    Menjadwalkan pengiriman email setelah transaksi pemanggil commit.

    `schema_name` ikut dioper karena worker **tidak** mewarisi schema
    dari pemanggilnya — pola yang sama dengan `run_attendance_import`
    dan `send_employee_reminders`. Tanpa itu task-nya jalan di public
    schema dan tidak menemukan satu baris log pun.

    Yang dioper cuma id barisnya. Isi surat sudah tersimpan di baris
    itu, jadi tidak ada konteks yang harus diserialisasi ke antrean —
    dan tidak ada risiko worker merender ulang dengan nilai yang sudah
    berbeda dari yang dilihat pemanggil.

    **Kegagalan mengantre tidak boleh menjatuhkan pemanggilnya, dan di
    sinilah satu-satunya tempat sifat pertama modul ini pernah bocor.**
    `notify()` membungkus seluruh badannya dengan savepoint, tapi
    callback `on_commit` jalan **di luar** savepoint itu — sesudah
    transaksinya commit, masih di dalam request. Broker yang mati
    membuat `.delay()` melempar `kombu.exceptions.OperationalError` dari
    titik itu, jadi:

    * datanya **sudah** tersimpan (dokumen disetujui, roster terbit,
      baseline shift terbentuk), tapi
    * response-nya 500, dan layar memberi tahu penggunanya bahwa
      keputusannya **gagal disimpan**

    Itu kebohongan yang paling mahal yang bisa dikeluarkan sistem ini:
    pengguna mengulang tindakan yang sebenarnya sudah berhasil. Ketahuan
    lewat UAT approval terakhir Roster Setup — dokumennya `committed`
    lengkap dengan 126 baris baseline, sementara approver-nya membaca
    "Keputusan gagal disimpan."

    Ditangkap **per baris**, bukan sekali untuk seluruh daftar: satu id
    yang gagal diantre tidak boleh membatalkan sisanya. Barisnya tetap
    berstatus `pending` — keadaan yang memang benar untuk surat yang
    belum terkirim, dan yang membuatnya bisa diambil ulang tanpa
    menduplikasi apa pun.
    """
    from django.db import connection

    from .tasks import send_email_notification

    schema_name = getattr(connection, "schema_name", "public")

    def _enqueue():
        for log_id in log_ids:
            try:
                send_email_notification.delay(schema_name, log_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Gagal mengantre email notifikasi %s di schema %s. "
                    "Barisnya tetap `pending` dan bisa dikirim ulang; "
                    "yang tidak boleh terjadi adalah tindakan penggunanya "
                    "ikut dilaporkan gagal.",
                    log_id,
                    schema_name,
                )

    transaction.on_commit(_enqueue)


def _create_log(
    *,
    result: DispatchResult,
    event: str,
    user,
    channel: str,
    module: str,
    object_type: str,
    object_id: str,
    dedup_key: str,
    subject: str,
    body: str,
    action_url: str,
    reason: str,
):
    """
    Membuat baris log, atau None kalau sudah pernah dikirim.

    Dedup ditegakkan **constraint database**, bukan pemeriksaan
    `exists()` lebih dulu: dua worker yang memproses pengingat yang sama
    bersamaan akan sama-sama membaca "belum pernah dikirim" sebelum
    salah satunya sempat menulis barisnya. Pelajaran yang sama dengan
    `applied_at` di RosterAdjustment dan `DocumentNumberService.next`.

    Savepoint tersendiri: `IntegrityError` yang tidak dibungkus membuat
    transaksi induknya tidak bisa dipakai lagi, jadi satu duplikat akan
    membatalkan seluruh pengiriman ke penerima lain.
    """
    from .channels.email import address_for

    try:
        with transaction.atomic():
            log = NotificationLog.objects.create(
                event=event,
                recipient=user,
                recipient_email=address_for(user) if channel == Channel.EMAIL else "",
                recipient_name=(
                    getattr(user, "get_full_name", lambda: "")()
                    or getattr(user, "username", "")
                )[:200],
                channel=channel,
                status=DeliveryStatus.PENDING,
                subject=str(subject)[:255],
                body=body,
                action_url=str(action_url or "")[:500],
                module=module,
                object_type=object_type,
                object_id=str(object_id or ""),
                dedup_key=dedup_key,
                detail=reason or "",
            )
    except IntegrityError:
        result.duplicates += 1

        return None

    result.created += 1

    return log
