"""
Susunan beranda per pengguna.

Yang disimpan cuma **urutan, tampil/tidak, dan terlipat/tidak** — bukan
koordinat dan bukan ukuran. Ukuran bebas berarti tiap widget harus
terlihat benar di berapa pun lebar, dan biaya perawatannya jauh lebih
besar daripada nilainya; `span` tetap ditentukan katalog.
"""

from __future__ import annotations

from django.db import transaction

from apps.administration.models import DashboardWidget, UserDashboardLayout

from apps.administration.api.dashboard.widget_catalog import (
    DEFAULT_CODES,
    HOME_WIDGETS,
    WIDGETS_BY_CODE,
)


class LayoutService:
    # ------------------------------------------------------------------
    # Baca
    # ------------------------------------------------------------------

    @staticmethod
    def _rows(user):
        return (
            UserDashboardLayout.objects
            .select_related("widget")
            .filter(user=user, is_deleted=False)
            .order_by("y", "id")
        )

    @classmethod
    def catalog(cls, user) -> list[dict]:
        """
        Seluruh widget yang tersedia, beserta keadaannya bagi `user`.

        **Katalog, bukan daftar yang tampil.** Satu request memberi dua
        keadaan sekaligus, jadi masuk mode Customize tidak menembak API
        lagi — pola yang sama dengan katalog aplikasi.

        Widget yang ada di susunan tersimpan tapi **tidak lagi ada di
        katalog** dilewati: itu widget yang sudah ditarik dari repo, dan
        merendernya berarti kotak kosong yang tidak bisa dihapus
        siapa pun.
        """
        saved = {
            row.widget.code: row
            for row in cls._rows(user)
            if row.widget.code in WIDGETS_BY_CODE
        }

        items = []

        for index, code in enumerate(cls._order_for(saved)):
            widget = WIDGETS_BY_CODE[code]
            row = saved.get(code)

            items.append({
                "code": code,
                "title": widget["title"],
                "description": widget["description"],
                "component": widget["component"],
                "span": widget["span"],
                "fixed_height": bool(widget.get("fixed_height")),
                "position": index,
                # Belum pernah menyusun = semuanya tampil, terbuka.
                "is_visible": row.is_visible if row else True,
                "is_collapsed": bool(
                    (row.config or {}).get("collapsed") if row else False
                ),
                # Dikembalikan apa adanya supaya frontend bisa
                # mengirimkannya balik utuh saat menyimpan — tanpa ini,
                # menyimpan susunan akan menghapus pengaturan widget
                # yang tidak dikenal halaman beranda.
                "config": dict(row.config or {}) if row else {},
            })

        return items

    @classmethod
    def config_for(cls, user, code: str) -> dict:
        """
        `config` satu widget, untuk pengaturan yang khusus widget itu.

        Dipakai Quick Actions menyimpan pintasan mana yang dipilih —
        **tanpa model baru**. Pilihan pintasan adalah preferensi
        tampilan milik satu widget, sama seperti terlipat/tidak, dan
        tabel tersendiri untuknya berarti satu lagi tempat yang harus
        dibersihkan saat penggunanya dihapus.
        """
        row = (
            UserDashboardLayout.objects
            .filter(user=user, widget__code=code, is_deleted=False)
            .first()
        )

        return dict(row.config or {}) if row else {}

    @staticmethod
    def _order_for(saved: dict) -> list[str]:
        """
        Urutan tampil: yang tersimpan lebih dulu, sisanya menyusul.

        Widget **baru** yang belum ada di susunan tersimpan tidak boleh
        hilang — kalau hanya baris tersimpan yang dirender, modul yang
        menambah widget besok tidak akan pernah terlihat oleh siapa pun
        yang sudah pernah menekan Save. Ditempel di belakang, urut
        katalog, jadi kelihatan tanpa mengacak susunan yang sudah diatur.
        """
        if not saved:
            return list(DEFAULT_CODES)

        ordered = [
            code
            for code in sorted(saved, key=lambda key: saved[key].y)
        ]

        ordered += [
            item["code"]
            for item in HOME_WIDGETS
            if item["code"] not in saved
        ]

        return ordered

    # ------------------------------------------------------------------
    # Tulis
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def set_layout(cls, user, items: list[dict]) -> list[dict]:
        """
        Menyimpan seluruh susunan sekaligus, bukan per widget.

        Satu kiriman untuk seluruh beranda: menggeser satu kartu
        mengubah posisi semua yang di bawahnya, jadi menyimpannya satu
        per satu berarti puluhan request untuk satu tarikan — dan
        keadaan setengah tersimpan kalau salah satunya gagal.

        Baris ditulis untuk **seluruh** katalog, termasuk yang
        disembunyikan. Kalau yang disembunyikan dibuang begitu saja,
        "sengaja disembunyikan semua" tidak bisa dibedakan dari "belum
        pernah menyusun", dan susunan bawaannya muncul lagi seolah
        simpanannya gagal. Pembedanya **ada barisnya**, bukan ada yang
        tampil.
        """
        widgets = cls._ensure_widgets()

        wanted = {
            item.get("code"): item
            for item in items
            if item.get("code") in WIDGETS_BY_CODE
        }

        # Urutan kiriman yang menentukan posisi; yang tidak disebut
        # ditempel di belakang mengikuti katalog.
        ordered = [
            item.get("code")
            for item in items
            if item.get("code") in WIDGETS_BY_CODE
        ]

        ordered += [
            item["code"]
            for item in HOME_WIDGETS
            if item["code"] not in wanted
        ]

        existing = {
            row.widget.code: row
            for row in cls._rows(user)
        }

        for position, code in enumerate(ordered):
            payload = wanted.get(code, {})

            row = existing.get(code) or UserDashboardLayout(
                user=user,
                widget=widgets[code],
            )

            row.x = 0
            row.y = position
            row.width = WIDGETS_BY_CODE[code]["span"]
            row.height = 1
            row.is_visible = bool(payload.get("is_visible", True))
            row.is_deleted = False

            config = dict(row.config or {})
            config["collapsed"] = bool(payload.get("is_collapsed", False))

            # Pengaturan khusus widget (mis. pintasan mana yang dipilih
            # di Quick Actions) ikut kiriman yang sama.
            #
            # Di-**merge**, bukan ditimpa: widget yang mengirim
            # `is_collapsed` saja tidak boleh menghapus pilihan
            # pintasan yang sudah tersimpan, dan itu persis yang terjadi
            # kalau seluruh `config` diganti isi kiriman.
            extra = payload.get("config")

            if isinstance(extra, dict):
                config.update(extra)

            row.config = config

            row.save()

        return cls.catalog(user)

    @classmethod
    @transaction.atomic
    def reset(cls, user) -> list[dict]:
        """
        Kembali ke susunan bawaan.

        **Hard delete**, bukan menulis ulang nilai bawaan: yang dituju
        adalah keadaan "belum pernah menyusun", dan itu ditandai
        **tidak adanya baris**. Menulis baris bernilai bawaan membuat
        pengguna itu berhenti ikut mengikuti bawaan yang berubah besok.
        """
        UserDashboardLayout.objects.filter(user=user).delete()

        return cls.catalog(user)

    # ------------------------------------------------------------------
    # Master widget
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_widgets() -> dict:
        """
        Baris `DashboardWidget` untuk tiap kode katalog.

        `UserDashboardLayout.widget` adalah FK, jadi barisnya harus ada
        sebelum susunan bisa disimpan. Dibuat di sini juga — bukan hanya
        di seed — supaya menambah widget baru tidak mengharuskan
        seseorang menjalankan `seed_dashboard` lebih dulu sebelum ada
        yang bisa menekan Save.
        """
        rows = {
            row.code: row
            for row in DashboardWidget.objects.filter(
                code__in=list(WIDGETS_BY_CODE),
            )
        }

        for code, widget in WIDGETS_BY_CODE.items():
            row = rows.get(code)

            if row is None:
                row = DashboardWidget.objects.create(
                    code=code,
                    title=widget["title"],
                    description=widget["description"],
                    component=widget["component"],
                    module="core",
                    default_width=widget["span"],
                    default_height=1,
                )

                rows[code] = row

                continue

            changed = []

            for field, value in (
                ("title", widget["title"]),
                ("description", widget["description"]),
                ("component", widget["component"]),
                ("default_width", widget["span"]),
            ):
                if getattr(row, field) != value:
                    setattr(row, field, value)
                    changed.append(field)

            if row.is_deleted:
                row.is_deleted = False
                changed.append("is_deleted")

            if changed:
                row.save(update_fields=[*changed, "updated_at"])

        return rows
