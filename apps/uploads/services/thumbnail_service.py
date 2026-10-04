from __future__ import annotations

import io
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.uploads.models import UploadedFile


def get_thumbnail_size() -> tuple[int, int]:
    configured = getattr(
        settings,
        "UPLOAD_THUMBNAIL_SIZE",
        (320, 320),
    )

    return int(configured[0]), int(configured[1])


def get_thumbnail_quality() -> int:
    return int(
        getattr(
            settings,
            "UPLOAD_THUMBNAIL_QUALITY",
            85,
        )
    )


def generate_image_thumbnail(instance: UploadedFile) -> bool:
    if not instance.file:
        return False

    if not getattr(
        settings,
        "UPLOAD_GENERATE_IMAGE_THUMBNAIL",
        True,
    ):
        return False

    try:
        instance.file.open("rb")

        with Image.open(instance.file) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail(
                get_thumbnail_size(),
                Image.Resampling.LANCZOS,
            )

            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")

            output = io.BytesIO()

            image.save(
                output,
                format="WEBP",
                quality=get_thumbnail_quality(),
                optimize=True,
            )

            output.seek(0)

            thumbnail_name = (
                f"{instance.public_id.hex}.webp"
            )

            instance.thumbnail.save(
                thumbnail_name,
                ContentFile(output.read()),
                save=False,
            )

            instance.save(
                update_fields=[
                    "thumbnail",
                    "updated_at",
                ]
            )

            return True

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        return False
    finally:
        try:
            instance.file.close()
        except Exception:
            pass


def generate_pdf_thumbnail(instance: UploadedFile) -> bool:
    if not instance.file:
        return False

    if not getattr(
        settings,
        "UPLOAD_GENERATE_PDF_THUMBNAIL",
        True,
    ):
        return False

    try:
        import pypdfium2 as pdfium
    except ImportError:
        return False

    try:
        instance.file.open("rb")
        pdf_bytes = instance.file.read()

        document = pdfium.PdfDocument(pdf_bytes)
        instance.page_count = len(document)

        if len(document) == 0:
            instance.save(
                update_fields=[
                    "page_count",
                    "updated_at",
                ]
            )
            return False

        page = document[0]
        rendered = page.render(scale=1.5)
        image = rendered.to_pil()

        image.thumbnail(
            get_thumbnail_size(),
            Image.Resampling.LANCZOS,
        )

        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")

        output = io.BytesIO()

        image.save(
            output,
            format="WEBP",
            quality=get_thumbnail_quality(),
            optimize=True,
        )

        output.seek(0)

        thumbnail_name = (
            f"{instance.public_id.hex}.webp"
        )

        instance.thumbnail.save(
            thumbnail_name,
            ContentFile(output.read()),
            save=False,
        )

        instance.save(
            update_fields=[
                "thumbnail",
                "page_count",
                "updated_at",
            ]
        )

        page.close()
        document.close()

        return True

    except (OSError, ValueError, RuntimeError):
        return False
    finally:
        try:
            instance.file.close()
        except Exception:
            pass


def generate_thumbnail(instance: UploadedFile) -> bool:
    if instance.file_type == UploadedFile.FileType.IMAGE:
        return generate_image_thumbnail(instance)

    if instance.file_type == UploadedFile.FileType.PDF:
        return generate_pdf_thumbnail(instance)

    return False