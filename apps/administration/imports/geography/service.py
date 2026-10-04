"""
Import wilayah Indonesia dari CSV Kemendagri.

Bentuknya berbeda dari importer di `apps/framework/imports`, dan itu
disengaja. Pipeline generik itu bekerja **per baris** — `resolve()` lalu
`write()` untuk tiap baris — dan bentuk itu benar untuk berkas klien
yang isinya ratusan baris dengan aturan bisnis berlapis. Di sini
berkasnya 83.762 baris kelurahan yang hanya perlu satu hal: induknya
ditemukan lewat awalan kodenya. Menjalankannya lewat pipeline per-baris
berarti 83.762 `SELECT` untuk induk plus 83.762 `INSERT` satu-satu, dan
itu bukan optimasi yang bisa ditambahkan belakangan — ia menentukan
bentuk kodenya.

Yang dipakai di sini: **satu query per tingkat** untuk memuat seluruh
induk ke dalam dict, lalu `bulk_create`/`bulk_update` berkelompok. Tidak
ada satu pun query di dalam loop baris.

Dua hal yang sengaja tidak dilewati:

* **Urutan.** Province -> Kabupaten/Kota -> Kecamatan -> Kelurahan/Desa.
  Anak tidak pernah ditulis sebelum induknya ada.
* **Identitas.** `tingkat + aid`. Import ulang berkas yang sama tidak
  pernah menghasilkan baris kedua.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from django.db import transaction

from apps.administration.models import (
    City,
    Country,
    District,
    Province,
    Village,
)

from .codes import (
    LEVEL_ORDER,
    LEVELS,
    GeographyLevel,
    clean_aid,
    get_level,
    level_for_aid,
    parent_aid,
)


# Model per tingkat. Dipisah dari `codes.py` supaya modul itu tetap bisa
# diimpor (dan diuji) tanpa menyentuh Django sama sekali.
MODELS: dict[str, type] = {
    "province": Province,
    "city": City,
    "district": District,
    "village": Village,
}


DEFAULT_COUNTRY_CODE = "ID"
DEFAULT_COUNTRY_NAME = "Indonesia"

DEFAULT_BATCH_SIZE = 2000

# Batas jumlah error yang **disimpan**; penghitungnya tetap utuh. Berkas
# yang seluruh barisnya salah (mis. tertukar antar tingkat) akan
# menghasilkan puluhan ribu pesan yang isinya sama — menyimpannya semua
# cuma menghabiskan memori untuk laporan yang tidak terbaca siapa pun.
DEFAULT_MAX_ERRORS = 200


@dataclass
class RowError:
    """Satu baris yang ditolak, lengkap dengan asal-usulnya."""

    level: str
    row_number: int
    code: str
    name: str
    parent_code: str
    error: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "row": self.row_number,
            "code": self.code,
            "name": self.name,
            "parent_code": self.parent_code,
            "error": self.error,
        }


@dataclass
class LevelResult:
    level: str
    label: str

    total: int = 0
    valid: int = 0
    invalid: int = 0

    created: int = 0
    updated: int = 0
    skipped: int = 0

    errors: list[RowError] = field(default_factory=list)
    error_count: int = 0

    # Diisi walau dry-run: dipakai tingkat berikutnya sebagai daftar
    # induk yang *akan* ada, supaya dry-run di database kosong tidak
    # melaporkan "induk tidak ditemukan" untuk seluruh berkas.
    valid_aids: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "label": self.label,
            "total": self.total,
            "valid": self.valid,
            "invalid": self.invalid,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": [item.as_dict() for item in self.errors],
            "error_count": self.error_count,
        }


class GeographyImportService:
    """
    Import berjenjang Province -> Kabupaten/Kota -> Kecamatan ->
    Kelurahan/Desa dari berkas CSV berformat `id,name`.
    """

    # ------------------------------------------------------------------
    # Pembacaan berkas
    # ------------------------------------------------------------------

    @classmethod
    def read_rows(
        cls,
        file_path: str | Path,
    ) -> Iterator[tuple[int, str, str]]:
        """
        Menghasilkan `(nomor_baris, aid, name)` per baris data.

        Nomor barisnya nomor baris **berkas** (header = 1), bukan indeks
        data — yang membaca laporan error akan membuka berkasnya lalu
        melompat ke nomor itu.

        `utf-8-sig` bukan kelebihan: berkas yang pernah dibuka Excel
        membawa BOM di depan header, dan tanpa itu kolom pertama terbaca
        sebagai `\\ufeffid` sehingga seluruh kode terbaca kosong.
        """

        path = Path(file_path)

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)

            try:
                header = next(reader)
            except StopIteration:
                return

            columns = [
                str(item or "").strip().lower().lstrip("﻿")
                for item in header
            ]

            id_index = cls._column_index(columns, ("id", "kode", "code", "aid"))
            name_index = cls._column_index(
                columns,
                ("name", "nama", "nama_wilayah"),
            )

            if id_index is None or name_index is None:
                raise ValueError(
                    f"{path.name}: header wajib memuat kolom 'id' dan "
                    f"'name'. Yang terbaca: {', '.join(columns) or '(kosong)'}."
                )

            for row_number, row in enumerate(reader, start=2):
                if not row or not any(str(cell).strip() for cell in row):
                    continue

                aid = (
                    clean_aid(row[id_index])
                    if id_index < len(row)
                    else ""
                )

                name = (
                    str(row[name_index]).strip()
                    if name_index < len(row)
                    else ""
                )

                yield row_number, aid, name

    @staticmethod
    def _column_index(
        columns: list[str],
        candidates: tuple[str, ...],
    ) -> int | None:
        for candidate in candidates:
            if candidate in columns:
                return columns.index(candidate)

        return None

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @classmethod
    def validate_rows(
        cls,
        *,
        level: GeographyLevel,
        rows: Iterable[tuple[int, str, str]],
        parent_aids: set[str] | None,
        result: LevelResult,
        max_errors: int = DEFAULT_MAX_ERRORS,
    ) -> list[tuple[int, str, str, str]]:
        """
        Mengembalikan baris yang lolos sebagai
        `(nomor_baris, aid, name, parent_aid)`.

        Seluruh penolakan terjadi di sini — sebelum satu baris pun
        ditulis — supaya dry-run dan import sungguhan melaporkan hal yang
        sama persis. Kalau sebagian penolakan baru jatuh saat menulis,
        dry-run yang bersih tidak lagi berarti apa-apa.
        """

        valid_rows: list[tuple[int, str, str, str]] = []

        # Duplikat **di dalam berkas** tidak bisa ditangkap constraint
        # database: saat dry-run belum ada yang tertulis, dan saat import
        # sungguhan `bulk_create` akan menolak seluruh batch-nya, bukan
        # baris yang bersangkutan.
        seen: dict[str, int] = {}

        def reject(
            row_number: int,
            aid: str,
            name: str,
            parent: str,
            message: str,
        ) -> None:
            result.invalid += 1
            result.error_count += 1

            if len(result.errors) < max_errors:
                result.errors.append(
                    RowError(
                        level=level.label,
                        row_number=row_number,
                        code=aid,
                        name=name,
                        parent_code=parent,
                        error=message,
                    )
                )

        for row_number, aid, name in rows:
            result.total += 1

            parent = parent_aid(aid)

            if not aid:
                reject(row_number, aid, name, parent, "id kosong.")
                continue

            if not name:
                reject(row_number, aid, name, parent, "name kosong.")
                continue

            if not level.matches(aid):
                actual = level_for_aid(aid)

                detail = (
                    f" Bentuknya cocok untuk {actual.label}."
                    if actual is not None
                    else ""
                )

                reject(
                    row_number,
                    aid,
                    name,
                    parent,
                    f"Kode '{aid}' tidak sesuai format {level.label} "
                    f"({level.pattern.pattern}).{detail}",
                )
                continue

            duplicate_of = seen.get(aid)

            if duplicate_of is not None:
                reject(
                    row_number,
                    aid,
                    name,
                    parent,
                    f"Kode '{aid}' duplikat — sudah dipakai baris "
                    f"{duplicate_of} di berkas yang sama.",
                )
                continue

            # `parent_aids is None` hanya untuk Province: induknya
            # Country, dan Country tidak punya kode berjenjang.
            if parent_aids is not None:
                if not parent:
                    reject(
                        row_number,
                        aid,
                        name,
                        parent,
                        f"Kode '{aid}' tidak punya kode induk.",
                    )
                    continue

                if parent not in parent_aids:
                    parent_level = (
                        LEVELS[level.parent_key].label
                        if level.parent_key
                        else "induk"
                    )

                    reject(
                        row_number,
                        aid,
                        name,
                        parent,
                        f"{parent_level} '{parent}' tidak ditemukan. "
                        f"Import {parent_level} lebih dulu, atau "
                        f"periksa kode barisnya.",
                    )
                    continue

            seen[aid] = row_number

            result.valid += 1
            result.valid_aids.add(aid)

            valid_rows.append((row_number, aid, name, parent))

        return valid_rows

    # ------------------------------------------------------------------
    # Peta induk
    # ------------------------------------------------------------------

    @staticmethod
    def load_aid_map(model: type) -> dict[str, int]:
        """
        `{aid: pk}` untuk seluruh baris aktif sebuah tingkat — satu
        query, dua kolom.

        Inilah yang menggantikan `Model.objects.get(aid=...)` per baris.
        Untuk 83.762 kelurahan, bedanya 2 query melawan 167.524.
        """

        return {
            aid: pk
            for aid, pk in (
                model.objects
                .filter(is_deleted=False)
                .exclude(aid="")
                .values_list("aid", "id")
            )
        }

    # ------------------------------------------------------------------
    # Country
    # ------------------------------------------------------------------

    @classmethod
    def resolve_country(
        cls,
        *,
        code: str = DEFAULT_COUNTRY_CODE,
        name: str = DEFAULT_COUNTRY_NAME,
        create_missing: bool = True,
    ) -> Country | None:
        """
        Country Indonesia **dipakai ulang, tidak pernah diduplikasi.**

        Dicari lewat `code` (yang memang berconstraint unik), bukan lewat
        nama: "Indonesia", "INDONESIA", dan "Republik Indonesia" adalah
        baris yang sama bagi siapa pun kecuali pencocokan teks.
        """

        country = (
            Country.objects
            .filter(code__iexact=code, is_deleted=False)
            .order_by("id")
            .first()
        )

        if country is not None or not create_missing:
            return country

        return Country.objects.create(
            code=code,
            name=name,
            phone_code="+62",
            currency_code="IDR",
        )

    # ------------------------------------------------------------------
    # Satu tingkat
    # ------------------------------------------------------------------

    @classmethod
    def import_level(
        cls,
        *,
        level: GeographyLevel,
        file_path: str | Path,
        parent_map: dict[str, int] | None,
        country: Country | None = None,
        dry_run: bool = False,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_errors: int = DEFAULT_MAX_ERRORS,
        extra_parent_aids: set[str] | None = None,
    ) -> LevelResult:
        result = LevelResult(level=level.key, label=level.label)

        model = MODELS[level.key]

        # Daftar induk yang dianggap ada saat validasi = yang sudah di
        # database **ditambah** yang baru saja lolos di tingkat
        # sebelumnya pada jalan yang sama. Tanpa gabungan itu, dry-run di
        # database kosong akan menolak seluruh berkas anak — padahal
        # induknya ada di berkas yang barusan divalidasi.
        parent_aids: set[str] | None = None

        if level.parent_key is not None:
            parent_aids = set(parent_map or {}) | set(extra_parent_aids or set())

        valid_rows = cls.validate_rows(
            level=level,
            rows=cls.read_rows(file_path),
            parent_aids=parent_aids,
            result=result,
            max_errors=max_errors,
        )

        if dry_run:
            # Dry-run berhenti di sini, sebelum menyentuh database. Yang
            # dilaporkan cuma hasil validasi — created/updated/skipped
            # sengaja dibiarkan nol, bukan ditebak: menebaknya berarti
            # angka yang tidak pernah bisa dipertanggungjawabkan.
            return result

        existing = cls._load_existing(model, level.parent_field)

        to_create: list[Any] = []
        to_update: list[Any] = []

        for _row_number, aid, name, parent in valid_rows:
            parent_id = (
                (parent_map or {}).get(parent)
                if level.parent_key is not None
                else None
            )

            if level.parent_key is not None and parent_id is None:
                # Lolos validasi lewat `extra_parent_aids` tapi induknya
                # tidak ada di database. Hanya mungkin kalau tingkat
                # induknya sendiri gagal ditulis di jalan yang sama.
                result.skipped += 1
                continue

            current = existing.get(aid)

            if current is None:
                instance = model(
                    aid=aid,
                    code=aid,
                    name=name,
                )

                if level.parent_key is None:
                    instance.country = country
                else:
                    setattr(instance, f"{level.parent_field}_id", parent_id)

                to_create.append(instance)
                continue

            pk, current_name, current_code, current_parent_id = current

            unchanged = (
                current_name == name
                and current_code == aid
                and (
                    level.parent_key is None
                    or current_parent_id == parent_id
                )
            )

            if unchanged:
                result.skipped += 1
                continue

            instance = model(pk=pk)
            instance.aid = aid
            instance.code = aid
            instance.name = name

            if level.parent_key is None:
                instance.country = country
            else:
                setattr(instance, f"{level.parent_field}_id", parent_id)

            to_update.append(instance)

        with transaction.atomic():
            if to_create:
                model.objects.bulk_create(
                    to_create,
                    batch_size=batch_size,
                )

                result.created = len(to_create)

            if to_update:
                update_fields = ["aid", "code", "name"]

                if level.parent_key is not None:
                    update_fields.append(level.parent_field)
                else:
                    update_fields.append("country")

                model.objects.bulk_update(
                    to_update,
                    update_fields,
                    batch_size=batch_size,
                )

                result.updated = len(to_update)

        return result

    @staticmethod
    def _load_existing(
        model: type,
        parent_field: str,
    ) -> dict[str, tuple[int, str, str, int | None]]:
        """
        `{aid: (pk, name, code, parent_id)}`.

        Induknya ikut dibaca supaya baris yang **tidak berubah** bisa
        dilewati tanpa satu pun UPDATE — itu yang membuat import ulang
        berkas yang sama selesai cepat dan melaporkan 0 created,
        0 updated.

        `parent_field` dioper eksplisit, bukan ditebak dari daftar nama
        kolom yang mungkin. Tebakan itu bekerja hari ini dan berhenti
        bekerja diam-diam begitu ada yang mendenormalisasi induk ke
        tingkat bawah (mis. `Village.city`): kolom yang dibandingkan
        jadi salah, seluruh baris terbaca "tidak berubah", dan
        perpindahan wilayah tidak pernah ikut terbarui.
        """

        columns = ["id", "aid", "name", "code"]

        if parent_field:
            columns.append(f"{parent_field}_id")

        rows = (
            model.objects
            .filter(is_deleted=False)
            .exclude(aid="")
            .values_list(*columns)
        )

        result: dict[str, tuple[int, str, str, int | None]] = {}

        for row in rows:
            pk, aid, name, code = row[0], row[1], row[2], row[3]
            parent_id = row[4] if parent_field else None

            result[aid] = (pk, name, code, parent_id)

        return result

    # ------------------------------------------------------------------
    # Seluruh jenjang
    # ------------------------------------------------------------------

    @classmethod
    def run(
        cls,
        *,
        directory: str | Path,
        levels: Iterable[str] | None = None,
        dry_run: bool = False,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_errors: int = DEFAULT_MAX_ERRORS,
        country_code: str = DEFAULT_COUNTRY_CODE,
        files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Menjalankan seluruh jenjang, selalu dalam urutan
        Province -> Kabupaten/Kota -> Kecamatan -> Kelurahan/Desa.

        Urutan itu tidak bisa dilewati pemanggil: `levels` cuma
        *menyaring* tingkat mana yang dijalankan, bukan mengurutkannya
        ulang.
        """

        base = Path(directory)

        selected = (
            [get_level(item).key for item in levels]
            if levels
            else list(LEVEL_ORDER)
        )

        country = cls.resolve_country(
            code=country_code,
            create_missing=not dry_run,
        )

        if country is None and not dry_run:
            raise ValueError(
                f"Country '{country_code}' tidak ditemukan dan tidak "
                f"bisa dibuat."
            )

        results: dict[str, LevelResult] = {}

        # Aid yang lolos di tingkat sebelumnya, dipakai supaya dry-run
        # tetap bisa memvalidasi anak walau induknya belum tertulis.
        previous_valid: set[str] = set()

        for level_key in LEVEL_ORDER:
            if level_key not in selected:
                previous_valid = set()
                continue

            level = LEVELS[level_key]

            file_path = base / (
                (files or {}).get(level_key)
                or level.filename
            )

            if not file_path.exists():
                raise FileNotFoundError(
                    f"Berkas {level.label} tidak ditemukan: {file_path}"
                )

            parent_map: dict[str, int] | None = None

            if level.parent_key is not None:
                parent_map = cls.load_aid_map(MODELS[level.parent_key])

            result = cls.import_level(
                level=level,
                file_path=file_path,
                parent_map=parent_map,
                country=country,
                dry_run=dry_run,
                batch_size=batch_size,
                max_errors=max_errors,
                extra_parent_aids=previous_valid,
            )

            results[level_key] = result
            previous_valid = result.valid_aids

        return {
            "dry_run": dry_run,
            "country": getattr(country, "code", country_code),
            "levels": [
                results[key].as_dict()
                for key in LEVEL_ORDER
                if key in results
            ],
            "total_created": sum(item.created for item in results.values()),
            "total_updated": sum(item.updated for item in results.values()),
            "total_skipped": sum(item.skipped for item in results.values()),
            "total_invalid": sum(item.invalid for item in results.values()),
            "has_errors": any(item.invalid for item in results.values()),
        }
