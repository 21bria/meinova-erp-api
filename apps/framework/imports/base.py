from __future__ import annotations

from typing import Any

from .normalizer import ImportNormalizer


class BaseImporter:
    """
    Kontrak satu resource yang bisa diimport.

    Turunan wajib mengisi `module` (sama dengan `framework_module` pada
    ViewSet) dan mengimplementasikan `write()`. Sisanya opsional.

    Pipeline memanggil, per baris, dengan urutan:
        normalize() -> validate() -> resolve() -> write()
    """

    # Identitas
    module: str = ""
    label: str = ""

    # Konfigurasi parsing
    source_types: tuple[str, ...] = ("csv",)

    # target -> daftar alias header yang diterima
    mapping: dict[str, list[str]] = {}

    # Nilai default bila kolom kosong
    defaults: dict[str, Any] = {}

    # Field bertipe tanggal. Diseragamkan ke ISO saat normalisasi,
    # memakai `datetime_formats` dari ImportProfile bila diisi.
    date_fields: tuple[str, ...] = ()

    # Field yang wajib terisi supaya baris dianggap valid
    required_fields: tuple[str, ...] = ()

    # Kolom yang ditampilkan pada tabel preview di frontend
    preview_columns: tuple[dict[str, str], ...] = ()

    # Field yang dipakai sebagai identitas baris di laporan error
    identity_field: str = ""

    # Header pada file template yang bisa diunduh user.
    # Kosong = diturunkan dari alias pertama tiap target di `mapping`.
    template_columns: tuple[str, ...] = ()

    # Satu atau beberapa baris contoh isi template.
    template_sample_rows: tuple[dict[str, Any], ...] = ()

    # ------------------------------------------------------------------
    # Konteks satu jalannya import
    # ------------------------------------------------------------------
    #
    # Importer yang butuh lebih dari sekadar baris file — `options`
    # ImportProfile, pengguna yang mengunggah, atau ingatan lintas-baris
    # seperti daftar tap yang sudah dilihat — mengisi ini `True`.
    # `ImportPipelineService` lalu mengoper `context=` ke tiap hook.
    #
    # Bawaannya `False`, dan itu disengaja: dua importer yang sudah ada
    # (Employee, Leave Opening) menulis hook-nya tanpa parameter itu,
    # dan menambahkannya diam-diam ke semua orang berarti tiap importer
    # pihak ketiga pecah pada `TypeError` yang tidak menyebut sebabnya.
    context_aware: bool = False

    @classmethod
    def hook_kwargs(
        cls,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Kwargs tambahan untuk hook, kosong bila importer tidak butuh."""
        if not cls.context_aware:
            return {}

        return {"context": context if context is not None else {}}

    # ------------------------------------------------------------------
    # Pemekaran baris
    # ------------------------------------------------------------------

    @classmethod
    def expand_row(
        cls,
        raw_row: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Satu baris file -> satu atau beberapa baris yang dinormalisasi.

        Bawaannya satu jadi satu, dan itu benar untuk hampir semua
        resource: satu baris CSV pegawai adalah satu pegawai.

        Yang membutuhkannya: file yang **satu barisnya memuat beberapa
        kejadian**. Absensi harian, misalnya — satu baris berisi tanggal
        plus jam masuk plus jam pulang adalah dua tap, dan memaksanya
        jadi satu berarti membuang salah satu tanpa suara.

        Dipanggil sebelum `normalize()`. Baris hasil pemekaran boleh
        membawa kunci tambahan berawalan `_`; parser tidak akan
        menyentuhnya dan `raw_payload` tidak memuatnya.
        """
        return [raw_row]

    # ------------------------------------------------------------------
    # Penjelasan profile
    # ------------------------------------------------------------------

    @classmethod
    def describe_profile(
        cls,
        profile,
    ) -> dict[str, Any]:
        """
        Ringkasan format file yang **diharapkan** satu ImportProfile.

        Dipakai layar import supaya pengguna tidak menebak bentuk
        filenya: yang menjelaskan profile adalah profile itu sendiri,
        bukan teks bantuan yang ditulis ulang di frontend dan basi
        begitu ada yang mengubah delimiter-nya.

        Bentuknya `{"summary": [{"label", "value"}], "columns": [...],
        "notes": [str]}`.
        """
        delimiter = getattr(profile, "delimiter", ",") or ","

        readable = {
            "\t": "TAB",
            ",": "Comma ( , )",
            ";": "Semicolon ( ; )",
            "|": "Pipe ( | )",
        }.get(delimiter, delimiter)

        return {
            "summary": [
                {"label": "Delimiter", "value": readable},
                {
                    "label": "Encoding",
                    "value": getattr(profile, "encoding", "") or "utf-8-sig",
                },
            ],
            "columns": [],
            "notes": [],
        }

    # ------------------------------------------------------------------
    # Template
    # ------------------------------------------------------------------

    @classmethod
    def get_template_columns(cls) -> list[str]:
        if cls.template_columns:
            return list(cls.template_columns)

        columns: list[str] = []

        for aliases in cls.get_mapping().values():
            if aliases:
                columns.append(aliases[0])

        return columns

    @classmethod
    def get_template_rows(cls) -> list[list[str]]:
        columns = cls.get_template_columns()

        return [
            [
                str(sample.get(column, ""))
                for column in columns
            ]
            for sample in cls.template_sample_rows
        ]

    # ------------------------------------------------------------------
    # Normalisasi
    # ------------------------------------------------------------------

    @classmethod
    def get_mapping(
        cls,
        override: dict[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        return ImportNormalizer.merge_mapping(
            base=cls.mapping,
            override=override,
        )

    @classmethod
    def normalize(
        cls,
        raw_row: dict[str, Any],
        *,
        mapping: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        value_mapping: dict[str, Any] | None = None,
        date_formats: Any = None,
    ) -> dict[str, Any]:
        return ImportNormalizer.normalize(
            raw_row,
            mapping=cls.get_mapping(mapping),
            defaults={
                **cls.defaults,
                **(defaults or {}),
            },
            value_mapping=value_mapping,
            date_fields=cls.date_fields,
            date_formats=date_formats,
        )

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @classmethod
    def validate(
        cls,
        normalized: dict[str, Any],
    ) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}

        for field_name in cls.required_fields:
            value = normalized.get(field_name)

            if value in (None, ""):
                errors.setdefault(
                    field_name,
                    [],
                ).append(
                    f"{field_name} is required.",
                )

        return errors

    # ------------------------------------------------------------------
    # Resolusi relasi
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        normalized: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        """
        Mengubah kode/nama pada baris menjadi objek relasi.
        Kembalikan (resolved, errors).
        """
        return {}, {}

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def build_preview_row(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Field tambahan yang ikut ditampilkan pada tabel preview.
        Default: seluruh kolom yang dideklarasikan di `preview_columns`.
        """
        keys = [
            column["key"]
            for column in cls.preview_columns
            if column.get("key")
            not in {
                "row_number",
            }
        ]

        return {
            key: normalized.get(key)
            for key in keys
        }

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @classmethod
    def write(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> tuple[Any, bool]:
        """
        Simpan satu baris. Kembalikan (instance, created).
        """
        raise NotImplementedError(
            f"{cls.__name__} harus mengimplementasikan write().",
        )

    # ------------------------------------------------------------------
    # Util
    # ------------------------------------------------------------------

    @classmethod
    def get_identity(
        cls,
        normalized: dict[str, Any],
    ) -> str:
        if not cls.identity_field:
            return ""

        return ImportNormalizer.clean_text(
            normalized.get(cls.identity_field),
        )
