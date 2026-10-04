from __future__ import annotations

from pathlib import Path
from typing import Any, Type

from .base import BaseImporter
from .parsers import get_parser_class
from .registry import get_importer_or_raise


class ImportPipelineService:
    """
    Pipeline import generik: parse -> normalize -> validate -> resolve
    -> write. Perilaku spesifik resource ada di importer-nya masing-masing,
    service ini tidak tahu apa-apa soal domain.
    """

    @classmethod
    def resolve_importer(
        cls,
        module: str | Type[BaseImporter],
    ) -> Type[BaseImporter]:
        if isinstance(module, type) and issubclass(module, BaseImporter):
            return module

        return get_importer_or_raise(str(module))

    @classmethod
    def build_context(
        cls,
        *,
        options: dict[str, Any] | None = None,
        user=None,
        profile=None,
    ) -> dict[str, Any]:
        return {
            "options": dict(options or {}),
            "user": user,
            "profile": profile,
            # Ruang kerja importer. Isinya bebas dan umurnya satu file.
            "state": {},
        }

    @classmethod
    def parse_rows(
        cls,
        *,
        source_type: str,
        file_path: str | Path,
        parser_options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        parser_class = get_parser_class(source_type)

        parser = parser_class(
            file_path,
            options=parser_options,
        )

        return parser.parse()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def preview(
        cls,
        *,
        module: str | Type[BaseImporter],
        file_path: str | Path,
        source_type: str = "csv",
        parser_options: dict[str, Any] | None = None,
        mapping: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        value_mapping: dict[str, Any] | None = None,
        date_formats: Any = None,
        options: dict[str, Any] | None = None,
        user=None,
        profile=None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        importer = cls.resolve_importer(module)

        # Satu konteks untuk seluruh file, bukan satu per baris: di
        # sinilah importer menaruh ingatan lintas-baris (tap yang sudah
        # dilihat, hasil resolusi yang sudah dihitung) tanpa menyimpan
        # state di class — class-level state bocor antar tenant dan
        # antar job Celery di worker yang sama.
        if context is None:
            context = cls.build_context(
                options=options,
                user=user,
                profile=profile,
            )

        # Konfigurasi normalisasi ikut masuk konteks: `expand_row()`
        # perlu tahu kolom mana yang memuat tanggal dan jam, dan ia
        # dipanggil sebelum `normalize()` sempat menerimanya.
        context["mapping"] = mapping
        context["defaults"] = defaults
        context["value_mapping"] = value_mapping
        context["date_formats"] = date_formats

        hook_kwargs = importer.hook_kwargs(context)

        source_rows = cls.parse_rows(
            source_type=source_type,
            file_path=file_path,
            parser_options=parser_options,
        )

        # Satu baris file bisa melahirkan lebih dari satu kejadian —
        # lihat `BaseImporter.expand_row()`. Jumlah baris **file** tetap
        # dilaporkan terpisah supaya "38 baris dibaca" dan "76 tap
        # diproses" tidak tertukar di layar.
        raw_rows: list[dict[str, Any]] = []

        for source_row in source_rows:
            raw_rows.extend(
                importer.expand_row(source_row, **hook_kwargs),
            )

        rows: list[dict[str, Any]] = []

        valid_count = 0
        invalid_count = 0
        unmatched_count = 0
        duplicate_count = 0

        for raw_row in raw_rows:
            normalized = importer.normalize(
                raw_row,
                mapping=mapping,
                defaults=defaults,
                value_mapping=value_mapping,
                date_formats=date_formats,
                **hook_kwargs,
            )

            errors = importer.validate(normalized, **hook_kwargs)

            resolved: dict[str, Any] = {}

            if not errors:
                resolved, resolve_errors = importer.resolve(
                    normalized,
                    **hook_kwargs,
                )

                if resolve_errors:
                    unmatched_count += 1

                    for field_name, messages in resolve_errors.items():
                        errors.setdefault(
                            field_name,
                            [],
                        ).extend(messages)

            is_valid = not errors

            # Duplikat bukan baris rusak. Dihitung terpisah supaya
            # mengunggah ulang file yang sama tidak membuat job-nya
            # berstatus PARTIAL — "sudah pernah masuk" dan "barisnya
            # salah" adalah dua hal yang berbeda, dan menyamakannya
            # membuat orang berhenti mempercayai status job.
            is_duplicate = bool(normalized.get("_duplicate"))

            if is_duplicate:
                duplicate_count += 1
            elif is_valid:
                valid_count += 1
            else:
                invalid_count += 1

            rows.append({
                "row_number": normalized.get("_row_number"),
                "source_type": normalized.get("_source_type"),
                "duplicate": is_duplicate,
                **importer.build_preview_row(
                    normalized=normalized,
                    resolved=resolved,
                    **hook_kwargs,
                ),
                "valid": is_valid,
                "errors": errors,
                "normalized": normalized,
                "resolved": resolved,
            })

        return {
            "module": importer.module,
            "source_type": source_type,
            "source_rows": len(source_rows),
            "total_rows": len(raw_rows),
            "valid_rows": valid_count,
            "invalid_rows": invalid_count,
            "unmatched_rows": unmatched_count,
            "duplicate_rows": duplicate_count,
            "rows": rows,
        }

    # ------------------------------------------------------------------
    # Eksekusi
    # ------------------------------------------------------------------

    @classmethod
    def build_error_row(
        cls,
        *,
        importer: Type[BaseImporter],
        item: dict[str, Any],
        errors: dict[str, list[str]],
    ) -> dict[str, Any]:
        normalized = item.get("normalized") or {}

        return {
            "row_number": item.get("row_number"),
            "identity": importer.get_identity(normalized),
            "errors": errors,
            "raw_data": normalized.get("raw_payload", {}),
        }

    @classmethod
    def execute(
        cls,
        *,
        module: str | Type[BaseImporter],
        file_path: str | Path,
        source_type: str = "csv",
        parser_options: dict[str, Any] | None = None,
        mapping: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        value_mapping: dict[str, Any] | None = None,
        date_formats: Any = None,
        options: dict[str, Any] | None = None,
        user=None,
        profile=None,
        skip_invalid: bool = True,
    ) -> dict[str, Any]:
        importer = cls.resolve_importer(module)

        # Preview dan commit memakai konteks yang **sama**, bukan dua
        # konteks yang kebetulan dibangun dari argumen yang sama.
        # Bedanya terlihat pada importer yang mengingat sesuatu lintas
        # baris: dedup tap yang dihitung saat preview harus tetap
        # berlaku saat barisnya ditulis.
        context = cls.build_context(
            options=options,
            user=user,
            profile=profile,
        )

        hook_kwargs = importer.hook_kwargs(context)

        preview = cls.preview(
            module=importer,
            file_path=file_path,
            source_type=source_type,
            parser_options=parser_options,
            mapping=mapping,
            defaults=defaults,
            value_mapping=value_mapping,
            date_formats=date_formats,
            context=context,
        )

        created_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0

        imported_rows: list[dict[str, Any]] = []
        error_rows: list[dict[str, Any]] = []

        for item in preview["rows"]:
            if item.get("duplicate"):
                # Sudah pernah masuk. Tidak ditulis, tidak dilaporkan
                # sebagai error — angkanya tetap terlihat lewat
                # `duplicate_rows`.
                continue

            if not item["valid"]:
                skipped_count += 1

                error_rows.append(
                    cls.build_error_row(
                        importer=importer,
                        item=item,
                        errors=item.get("errors", {}),
                    )
                )

                if skip_invalid:
                    continue

                raise ValueError(
                    f"Invalid row {item.get('row_number')}: "
                    f"{item.get('errors')}"
                )

            try:
                instance, created = importer.write(
                    normalized=item["normalized"],
                    resolved=item.get("resolved", {}),
                    user=user,
                    **hook_kwargs,
                )
            except Exception as exc:
                failed_count += 1

                error_rows.append(
                    cls.build_error_row(
                        importer=importer,
                        item=item,
                        errors={
                            "__all__": [str(exc)],
                        },
                    )
                )

                if skip_invalid:
                    continue

                raise

            if created:
                created_count += 1
            else:
                updated_count += 1

            imported_rows.append({
                "row_number": item.get("row_number"),
                "record_id": getattr(instance, "id", None),
                "created": created,
                "duplicate": False,
            })

        return {
            "module": importer.module,
            "source_type": source_type,
            "source_rows": preview.get("source_rows", preview["total_rows"]),
            "total_rows": preview["total_rows"],
            "valid_rows": preview["valid_rows"],
            "invalid_rows": preview["invalid_rows"],
            "created_rows": created_count,
            "updated_rows": updated_count,
            "duplicate_rows": preview.get("duplicate_rows", 0),
            "skipped_rows": skipped_count,
            "failed_rows": failed_count,
            "error_rows": error_rows,
            "rows": imported_rows,
        }
