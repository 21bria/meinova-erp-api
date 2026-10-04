"""
Registry event notifikasi.

Ini jawaban untuk "satu mesin notifikasi untuk semua modul": modul
mendaftarkan **apa yang bisa terjadi padanya**, engine yang mengurus
template, penerima, kanal, dedup, dan log. Modul tidak pernah menulis
`send_mail` sendiri — kalau ada yang menulisnya, template dan penerima
event itu tidak bisa dikonfigurasi dari layar mana pun, dan itu persis
keadaan yang sedang diperbaiki.

Pola yang sama dengan `workflow.registry`, `framework.lookup`, dan
registry importer di codebase ini. Daftarkan dari `AppConfig.ready()` —
kalau lupa, event-nya tidak muncul di layar template dan pemanggilnya
gagal dengan `UnknownEvent`, bukan gagal diam.

**Placeholder didaftarkan, bukan dibiarkan bebas.** Orang yang menyunting
template harus bisa melihat daftar kunci yang tersedia beserta contoh
nilainya; tanpa itu satu-satunya cara mengetahuinya adalah membaca kode
pengirimnya. Daftar ini juga yang dipakai memvalidasi template saat
disimpan dan membangun contoh untuk tombol pratinjau.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from .constants import Channel, RecipientType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Placeholder:
    """Satu kunci yang boleh dipakai di dalam template."""

    key: str
    label: str
    example: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "example": self.example,
        }


# Placeholder yang selalu tersedia, apa pun event-nya. Diisi
# `NotificationDispatcher` dari setelan tenant, bukan oleh pemanggil —
# kalau tiap pemanggil harus mengingatnya, cepat atau lambat ada email
# yang kaki suratnya kosong.
COMMON_PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder("recipient_name", "Nama penerima", "Budi Santoso"),
    Placeholder("recipient_first_name", "Nama depan penerima", "Budi"),
    Placeholder("app_name", "Nama aplikasi", "Meinova ERP"),
    Placeholder("company_name", "Nama perusahaan", "Meinova Group"),
    Placeholder("base_url", "Alamat aplikasi", "https://demo.meinova.id"),
    Placeholder("action_url", "Tautan ke dokumen/layar terkait", ""),
    Placeholder("today", "Tanggal hari ini", "15 August 2026"),
)


@dataclass(frozen=True)
class NotificationEvent:
    """
    Satu hal yang bisa terjadi dan pantas diberitahukan.

    `default_*` cuma nilai awal — begitu tenant menyimpan satu baris
    `NotificationRule` untuk event ini, baris itu yang berlaku. Pola
    yang sama dengan `FavoriteApp.DEFAULT_CODES` dan susunan widget
    beranda: bawaan **tidak** ditulis ke database, supaya bawaan yang
    berubah besok tetap sampai ke tenant yang belum pernah mengaturnya.
    """

    code: str
    label: str
    module: str
    description: str = ""
    category: str = ""

    placeholders: tuple[Placeholder, ...] = ()

    default_recipients: tuple[str, ...] = (RecipientType.SUBJECT,)
    default_roles: tuple[str, ...] = ()
    default_channels: tuple[str, ...] = (Channel.IN_APP, Channel.EMAIL)

    # Judul & isi bawaan, dipakai `seed_notification_templates` dan
    # dipakai sebagai jatuhan kalau tenant belum punya barisnya.
    #
    # Jatuhan ini penting: event yang templatenya belum diseed tetap
    # terkirim dengan kalimat yang masuk akal, bukan hilang. Email yang
    # tidak pernah datang tidak bisa dibedakan dari fitur yang belum ada.
    default_subject: str = ""
    default_body: str = ""

    def all_placeholders(self) -> tuple[Placeholder, ...]:
        return COMMON_PLACEHOLDERS + self.placeholders

    def placeholder_keys(self) -> frozenset[str]:
        return frozenset(item.key for item in self.all_placeholders())

    def sample_context(self) -> dict[str, str]:
        """Contoh nilai untuk tombol pratinjau di layar template."""
        return {
            item.key: item.example
            for item in self.all_placeholders()
        }

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "module": self.module,
            "description": self.description,
            "category": self.category,
            "placeholders": [
                item.as_dict()
                for item in self.all_placeholders()
            ],
            "default_recipients": list(self.default_recipients),
            "default_roles": list(self.default_roles),
            "default_channels": list(self.default_channels),
        }


class UnknownEvent(KeyError):
    """
    Event yang tidak terdaftar.

    Dilempar, tidak dilewati diam-diam: nama event salah ketik akan
    membuat pemberitahuan tidak pernah terkirim, dan itu jenis kegagalan
    yang tidak ada yang melaporkannya — orang tidak mengeluhkan email
    yang tidak pernah mereka tahu seharusnya ada.
    """


_EVENTS: dict[str, NotificationEvent] = {}


def register_event(event: NotificationEvent) -> NotificationEvent:
    """Mendaftarkan satu event. Panggil dari `AppConfig.ready()`."""
    code = event.code.strip().lower()

    if code in _EVENTS and _EVENTS[code] is not event:
        logger.warning(
            "Event notifikasi '%s' didaftarkan dua kali — "
            "yang terakhir menang.",
            code,
        )

    _EVENTS[code] = event

    return event


def get_event(code: str) -> NotificationEvent:
    try:
        return _EVENTS[str(code).strip().lower()]
    except KeyError as exc:
        raise UnknownEvent(
            f"Event notifikasi '{code}' tidak terdaftar. "
            f"Daftarkan lewat register_event() di AppConfig.ready(). "
            f"Yang sudah terdaftar: {', '.join(sorted(_EVENTS)) or '(kosong)'}",
        ) from exc


def find_event(code: str) -> NotificationEvent | None:
    """Seperti `get_event` tapi mengembalikan None. Untuk layar dan seed."""
    return _EVENTS.get(str(code).strip().lower())


def all_events() -> list[NotificationEvent]:
    return sorted(_EVENTS.values(), key=lambda item: (item.module, item.code))


def events_for(module: str) -> list[NotificationEvent]:
    target = str(module).strip().lower()

    return [
        item
        for item in all_events()
        if item.module.strip().lower() == target
    ]


def event_choices() -> list[tuple[str, str]]:
    """Untuk `choices=` di model dan dropdown di layar."""
    return [(item.code, item.label) for item in all_events()]


def unknown_placeholders(code: str, keys: Iterable[str]) -> list[str]:
    """
    Kunci yang dipakai template tapi tidak dikenal event-nya.

    Dipakai validasi saat menyimpan template. Sengaja **peringatan di
    serializer, bukan penolakan di model**: placeholder yang tidak
    dikenal dirender jadi string kosong, dan menolak simpan gara-gara
    satu salah ketik akan membuang seluruh kalimat yang sudah ditulis
    orang.
    """
    event = find_event(code)

    if event is None:
        return []

    known = event.placeholder_keys()

    return sorted({key for key in keys if key not in known})
