"""
Service artikel & kategori panduan.

Tiga hal yang harus lewat sini dan tidak boleh diserahkan ke
serializer: pembersihan HTML, penurunan slug, dan pengisian
`published_at`. Ketiganya dipakai juga oleh seed dan importer, jadi
menaruhnya di serializer berarti jalur non-HTTP menyimpan artikel yang
belum dibersihkan.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.text import slugify

from apps.core.services.master import BaseMasterService
from apps.helpcenter.models import (
    HelpArticle,
    HelpArticleStatus,
    HelpCategory,
)
from apps.helpcenter.sanitize import sanitize_html


class HelpCategoryService(BaseMasterService):
    model = HelpCategory


class HelpArticleService(BaseMasterService):
    model = HelpArticle

    # ------------------------------------------------------------------
    # Slug
    # ------------------------------------------------------------------

    @classmethod
    def unique_slug(cls, base: str, *, exclude_pk: int | None = None) -> str:
        """
        Slug yang dijamin belum dipakai artikel aktif lain.

        Bentrok diselesaikan dengan akhiran angka, bukan ditolak:
        dua artikel boleh saja berjudul "Mengajukan Cuti" di kategori
        berbeda, dan memaksa penulisnya mengarang judul lain hanya
        karena URL-nya bentrok bukan keputusan yang layak dibebankan
        kepadanya.
        """

        candidate = slugify(base or "")[:150] or "artikel"

        queryset = HelpArticle.objects.filter(is_deleted=False)

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        slug = candidate
        suffix = 2

        while queryset.filter(slug=slug).exists():
            slug = f"{candidate[:150 - len(str(suffix)) - 1]}-{suffix}"
            suffix += 1

        return slug

    # ------------------------------------------------------------------
    # Hook tulis
    # ------------------------------------------------------------------

    @classmethod
    def _apply_common(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "content" in data:
            data["content"] = sanitize_html(data.get("content"))

        return data

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls._apply_common(data)

        if not data.get("slug"):
            data["slug"] = cls.unique_slug(data.get("title", ""))
        else:
            data["slug"] = cls.unique_slug(data["slug"])

        if not data.get("code"):
            data["code"] = data["slug"].upper()[:50]

        if (
            data.get("status") == HelpArticleStatus.PUBLISHED
            and not data.get("published_at")
        ):
            data["published_at"] = timezone.now()

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls._apply_common(data)

        if "slug" in data:
            # Slug dikosongkan penulisnya = turunkan ulang dari judul.
            # Yang diisi tetap dihormati, hanya diunikkan.
            base = data["slug"] or data.get("title") or instance.title
            data["slug"] = cls.unique_slug(base, exclude_pk=instance.pk)

        status = data.get("status", instance.status)

        if status == HelpArticleStatus.PUBLISHED:
            if not (data.get("published_at") or instance.published_at):
                data["published_at"] = timezone.now()
        else:
            # Ditarik kembali jadi draft: tanggal terbitnya ikut
            # dikosongkan, kalau tidak artikel yang belum pernah
            # terbaca siapa pun tetap membawa tanggal terbit.
            data["published_at"] = None

        return data
