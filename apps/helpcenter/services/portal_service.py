"""
Sisi pembaca Help Center.

Terpisah dari service CRUD-nya karena aturannya memang berbeda: yang
di sini **hanya membaca**, hanya artikel yang sudah terbit, dan ikut
menyaring role. Menggabungkannya dengan `HelpArticleService` berarti
satu kelas yang kadang menyaring kadang tidak, dan cepat atau lambat
ada yang memanggil cabang yang salah — draft yang belum selesai
ditulis tampil di halaman bantuan seluruh tenant.

**Ini penyaring tampilan, bukan penjagaan rahasia.** Artikel panduan
tidak memuat data pegawai; yang disaring role cuma supaya panduan
admin tidak memenuhi daftar milik pegawai biasa.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import F, Q, QuerySet

from apps.administration.api.dashboard.catalog import APP_CATALOG
from apps.helpcenter.models import (
    HelpArticle,
    HelpArticleFeedback,
    HelpArticleStatus,
    HelpCategory,
)
from apps.helpcenter.outline import build_outline
from apps.helpcenter.sanitize import absolutize_media, strip_tags


# Panjang cuplikan hasil pencarian. Cukup untuk satu-dua kalimat di
# sekitar kata yang dicari; lebih panjang dari itu kartunya jadi
# dinding teks dan hasil kelima tidak pernah terlihat.
SNIPPET_LENGTH = 180


# Label modul diambil dari `APP_CATALOG` — daftar modul yang sudah
# dipakai kartu Applications di beranda. Menulis daftar kedua di sini
# berarti dua daftar modul yang harus dijaga tetap sama, dan bedanya
# baru ketahuan saat ada yang menambah modul lalu tab-nya berbunyi
# "scm" di satu layar dan "Supply Chain" di layar lain.
def _module_labels() -> dict[str, dict]:
    return {
        app["app_code"]: {
            "label": app["title"],
            "icon": app.get("icon", ""),
            "color": app.get("color", ""),
            "position": app.get("position", 999),
        }
        for app in APP_CATALOG
    }


class HelpPortalService:
    # ------------------------------------------------------------------
    # Queryset dasar
    # ------------------------------------------------------------------

    @classmethod
    def visible_articles(cls, user) -> QuerySet[HelpArticle]:
        queryset = (
            HelpArticle.objects
            .select_related("category")
            .filter(
                is_deleted=False,
                is_active=True,
                status=HelpArticleStatus.PUBLISHED,
                category__is_deleted=False,
                category__is_published=True,
            )
        )

        if user is None or not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        # `role` kosong = terbaca semua orang. Kosong berarti "berlaku
        # untuk semua", bukan "tidak berlaku" — konvensi yang sama
        # dengan seluruh policy di codebase ini.
        role_ids = list(
            user.roles.filter(is_deleted=False).values_list("id", flat=True)
        )

        return queryset.filter(
            Q(role__isnull=True) | Q(role_id__in=role_ids)
        )

    @classmethod
    def visible_categories(cls, user) -> QuerySet[HelpCategory]:
        return (
            HelpCategory.objects
            .filter(
                is_deleted=False,
                is_active=True,
                is_published=True,
            )
        )

    # ------------------------------------------------------------------
    # Daftar
    # ------------------------------------------------------------------

    @classmethod
    def tree(cls, user, *, module: str | None = None) -> list[dict]:
        """
        Kategori beserta artikelnya — satu request untuk seluruh
        sidebar Help Center.

        Satu endpoint, bukan satu per kategori: halaman bantuan
        dibuka justru saat pengguna sedang bingung, dan menembak
        belasan request untuk render pertama membuat layar itu lambat
        tepat di saat paling tidak boleh lambat. Alasan yang sama
        dengan `BaseDashboardAPIView`.
        """

        articles = cls.visible_articles(user).order_by(
            "category__sort_order",
            "category__name",
            "sort_order",
            "title",
        )

        if module:
            articles = articles.filter(category__module=module)

        grouped: dict[int, list[HelpArticle]] = {}

        for article in articles:
            grouped.setdefault(article.category_id, []).append(article)

        categories = cls.visible_categories(user).order_by(
            "sort_order",
            "name",
        )

        result = []

        for category in categories:
            items = grouped.get(category.id, [])

            # Kategori tanpa artikel yang terbaca **tidak** ditampilkan.
            # Judul kategori yang dibuka lalu kosong terbaca seperti
            # halaman gagal memuat, bukan seperti "belum ada isinya".
            if not items:
                continue

            result.append({
                "code": category.code,
                "name": category.name,
                "description": category.description,
                "icon": category.icon,
                "module": category.module,
                "articles": [cls.serialize_card(a) for a in items],
            })

        return result

    @classmethod
    def modules(cls, user) -> list[dict]:
        """
        Modul yang punya panduan, untuk tab di atas Help Center.

        Dihitung dari artikel yang **benar-benar terbaca pengguna
        ini**, bukan dari daftar kategori: tab bertuliskan "Payroll"
        yang dibuka lalu kosong lebih buruk daripada tab yang memang
        tidak ada — pembacanya menyangka datanya gagal dimuat.

        Kategori tanpa `module` dikumpulkan sebagai "Umum". Kosong di
        sini berarti "tidak menempel ke modul mana pun", bukan "belum
        diisi" — konvensi yang sama dengan seluruh policy di codebase
        ini.
        """

        counts: dict[str, int] = {}

        rows = (
            cls.visible_articles(user)
            .values_list("category__module", flat=True)
        )

        for module in rows:
            counts[module or ""] = counts.get(module or "", 0) + 1

        labels = _module_labels()

        result = []

        for code, count in counts.items():
            meta = labels.get(code, {})

            result.append({
                "code": code,
                "label": meta.get("label") or (code.title() if code else "Umum"),
                "icon": meta.get("icon", ""),
                "color": meta.get("color", ""),
                "count": count,
                "position": meta.get("position", 999),
            })

        # Urutannya mengikuti `APP_CATALOG` supaya tab di sini sejajar
        # dengan urutan kartu di beranda. "Umum" selalu paling akhir:
        # ia bukan modul, dan menaruhnya di antara modul membuat
        # deretnya terbaca seperti ada modul bernama Umum.
        result.sort(key=lambda m: (m["code"] == "", m["position"], m["label"]))

        for item in result:
            item.pop("position")

        return result

    @classmethod
    def contextual(cls, user, *, route: str) -> list[dict]:
        """
        Panduan untuk layar yang sedang dibuka.

        Kecocokannya lewat **awalan rute yang berhenti di batas
        segmen**: artikel ber-`route_prefix` `/hr` ikut muncul di
        `/hr/employees`, tapi `/hr-old/x` tidak. Yang lebih spesifik
        didahulukan, jadi panduan khusus layar Employees duduk di atas
        panduan modul HR.

        `route_prefix` = `/` **hanya** cocok dengan beranda. Tanpa
        pengecualian itu ia cocok dengan setiap rute yang ada, dan
        panduan beranda muncul di seluruh layar sistem — persis yang
        terjadi sebelum ini.
        """

        route = (route or "").strip()

        if not route:
            return []

        route = "/" + route.strip("/")

        candidates = [
            article
            for article in cls.visible_articles(user).exclude(route_prefix="")
            if cls.route_matches(route, article.route_prefix)
        ]

        candidates.sort(
            key=lambda a: (-len(a.route_prefix), a.sort_order, a.title),
        )

        return [cls.serialize_card(a) for a in candidates]

    @staticmethod
    def route_matches(route: str, prefix: str) -> bool:
        prefix = "/" + (prefix or "").strip().strip("/")

        if prefix == "/":
            return route == "/"

        return route == prefix or route.startswith(prefix + "/")

    @classmethod
    def search(cls, user, *, query: str, limit: int = 20) -> list[dict]:
        query = (query or "").strip()

        if len(query) < 2:
            return []

        matches = cls.visible_articles(user).filter(
            Q(title__icontains=query)
            | Q(summary__icontains=query)
            | Q(keywords__icontains=query)
            | Q(content__icontains=query)
        )[:limit]

        results = []

        for article in matches:
            card = cls.serialize_card(article)
            card["snippet"] = cls.snippet(article, query)
            results.append(card)

        # Judul yang cocok didahulukan: yang mengetik "cuti" mencari
        # artikel *tentang* cuti, bukan artikel yang kebetulan
        # menyebut kata itu di paragraf kelima.
        lowered = query.lower()

        results.sort(
            key=lambda card: (
                0 if lowered in (card["title"] or "").lower() else 1,
                card["title"] or "",
            ),
        )

        return results

    # ------------------------------------------------------------------
    # Detail
    # ------------------------------------------------------------------

    @classmethod
    def detail(cls, user, *, slug: str, media_base: str | None = None) -> dict | None:
        article = (
            cls.visible_articles(user)
            .filter(slug=slug)
            .first()
        )

        if article is None:
            return None

        siblings = list(
            cls.visible_articles(user)
            .filter(category_id=article.category_id)
            .order_by("sort_order", "title")
            .values("slug", "title")
        )

        index = next(
            (
                i
                for i, item in enumerate(siblings)
                if item["slug"] == article.slug
            ),
            None,
        )

        my_feedback = (
            HelpArticleFeedback.objects
            .filter(article=article, user=user, is_deleted=False)
            .values_list("is_helpful", flat=True)
            .first()
        )

        # Heading diberi id di sini, bukan disimpan begitu di
        # database: judul heading berubah tiap penulisnya menyunting
        # artikel, dan daftar isi yang tersimpan akan menunjuk bagian
        # yang sudah tidak ada tanpa satu pun tanda.
        content, toc = build_outline(article.content)

        # Jalur gambar disimpan relatif supaya artikelnya bisa dipindah
        # antar lingkungan, tapi frontend beda origin dari backend —
        # tanpa ini seluruh gambar panduan tampil sebagai ikon pecah.
        content = absolutize_media(content, media_base)

        return {
            **cls.serialize_card(article),
            "content": content,
            "toc": toc,
            "video_url": article.video_url,
            "category": {
                "code": article.category.code,
                "name": article.category.name,
                "icon": article.category.icon,
            },
            "updated_at": article.updated_at,
            "view_count": article.view_count,
            "helpful_count": article.helpful_count,
            "not_helpful_count": article.not_helpful_count,
            "my_feedback": my_feedback,
            "previous": (
                siblings[index - 1]
                if index not in (None, 0)
                else None
            ),
            "next": (
                siblings[index + 1]
                if index is not None and index + 1 < len(siblings)
                else None
            ),
        }

    @classmethod
    def record_view(cls, *, slug: str) -> None:
        """
        Menaikkan penghitung baca.

        `update()` langsung ke database, bukan `instance.view_count +=
        1` lalu `save()`: dua pembaca yang membuka artikel bersamaan
        akan sama-sama membaca angka lama dan salah satunya hilang.
        Sengaja **tidak** lewat service — ini bukan perubahan yang
        perlu masuk jejak audit, dan mencatatnya berarti tiap kali
        seseorang membuka panduan tertulis satu baris audit.
        """

        (
            HelpArticle.objects
            .filter(slug=slug, is_deleted=False)
            .update(view_count=F("view_count") + 1)
        )

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit_feedback(
        cls,
        user,
        *,
        slug: str,
        is_helpful: bool,
        comment: str = "",
    ) -> dict | None:
        article = cls.visible_articles(user).filter(slug=slug).first()

        if article is None:
            return None

        # Satu suara per orang, dan boleh diubah — pembaca yang
        # awalnya menjawab "tidak membantu" lalu menemukan jawabannya
        # di paragraf berikutnya harus bisa membetulkannya.
        HelpArticleFeedback.objects.update_or_create(
            article=article,
            user=user,
            is_deleted=False,
            defaults={
                "is_helpful": is_helpful,
                "comment": (comment or "").strip()[:2000],
                "updated_by": user,
            },
        )

        cls.recount_feedback(article)

        return {
            "helpful_count": article.helpful_count,
            "not_helpful_count": article.not_helpful_count,
            "my_feedback": is_helpful,
        }

    @classmethod
    def recount_feedback(cls, article: HelpArticle) -> None:
        """
        Menjumlahkan ulang dari baris feedback, bukan menambah satu.

        Penjumlahan ulang tidak bisa hanyut; penambahan inkremental
        akan meleset begitu ada satu suara yang diubah atau dihapus.
        Pola yang sama dengan `LeaveBalance.used`.
        """

        rows = HelpArticleFeedback.objects.filter(
            article=article,
            is_deleted=False,
        )

        article.helpful_count = rows.filter(is_helpful=True).count()
        article.not_helpful_count = rows.filter(is_helpful=False).count()

        article.save(update_fields=["helpful_count", "not_helpful_count"])

    # ------------------------------------------------------------------
    # Bentuk payload
    # ------------------------------------------------------------------

    @staticmethod
    def serialize_card(article: HelpArticle) -> dict:
        return {
            "slug": article.slug,
            "title": article.title,
            "summary": article.summary,
            "icon": article.icon or article.category.icon,
            "category_code": article.category.code,
            "category_name": article.category.name,
            "route_prefix": article.route_prefix,
            "has_video": bool(article.video_url),
        }

    @staticmethod
    def snippet(article: HelpArticle, query: str) -> str:
        text = strip_tags(article.content)

        if not text:
            return article.summary

        position = text.lower().find(query.lower())

        if position < 0:
            return text[:SNIPPET_LENGTH].strip()

        start = max(0, position - SNIPPET_LENGTH // 3)
        excerpt = text[start:start + SNIPPET_LENGTH].strip()

        return ("… " if start > 0 else "") + excerpt + " …"
