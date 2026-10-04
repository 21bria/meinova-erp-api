"""
Seed template email bawaan.

**Template diseed, aturan penerima tidak.** Bedanya bukan selera:

- Template adalah **isi** yang memang ditujukan untuk disunting. Layar
  yang kosong terbaca seperti fitur yang belum ada, dan orang tidak akan
  menulis surat dari nol untuk sebelas event. Diseed = ada titik awal
  yang bisa diubah satu kalimat.

- Aturan penerima adalah **keputusan** yang punya bawaan sah dari
  registry. Menulisnya ke database membuat "belum pernah diatur" tidak
  bisa dibedakan lagi dari "sudah diatur dan kebetulan sama", dan bawaan
  yang berubah besok tidak akan pernah sampai ke tenant lama. Pelajaran
  yang sama dengan `FavoriteApp.DEFAULT_CODES`, `seed_favorite_menus`,
  dan susunan widget beranda.

Aman diulang, dan **template yang sudah disunting orang dilewati**
(`updated_by` terisi). Seed adalah titik awal, bukan pemilik isinya —
pola yang sama dengan `seed_help_center`.
"""

from __future__ import annotations

import logging

from apps.notifications.models import EmailTemplate
from apps.notifications.registry import all_events

logger = logging.getLogger(__name__)


def run(*, overwrite: bool = False) -> dict:
    """
    Menulis satu template global per event terdaftar.

    Global (`company=None`), bukan per company: bawaan yang sama untuk
    semua perusahaan adalah titik awal yang benar, dan tenant yang butuh
    kalimat berbeda per perusahaan tinggal menambah barisnya sendiri —
    yang bercompany otomatis mengalahkan yang global.
    """
    stats = {"created": 0, "updated": 0, "skipped_edited": 0}

    for event in all_events():
        existing = (
            EmailTemplate.objects
            .filter(event=event.code, company__isnull=True, is_deleted=False)
            .first()
        )

        if existing is None:
            EmailTemplate.objects.create(
                event=event.code,
                company=None,
                name=event.label,
                subject=event.default_subject,
                body=event.default_body,
            )

            stats["created"] += 1

            continue

        if existing.updated_by_id is not None and not overwrite:
            stats["skipped_edited"] += 1

            continue

        existing.name = existing.name or event.label
        existing.subject = event.default_subject
        existing.body = event.default_body

        existing.save(update_fields=["name", "subject", "body", "updated_at"])

        stats["updated"] += 1

    logger.info("Seed template notifikasi: %s", stats)

    return stats
