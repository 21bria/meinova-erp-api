"""
Layar admin artikel panduan.

Editor `workspace` (bukan dialog) karena isinya panjang: menulis
panduan lima paragraf di dalam modal berarti mengetik sambil menahan
seluruh layar di belakangnya tetap terlihat.
"""

from apps.framework.builders import field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.helpcenter.models import HelpArticle
from apps.helpcenter.services import HelpArticleService

from .serializers import HelpArticleSerializer


CONTENT_FIELDS = {
    "title": field.text(
        tab="content",
        label="Title",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        layout="full",
        order=10,
    ),

    "category": field.lookup(
        tab="content",
        label="Category",
        lookup_endpoint="/api/helpcenter/lookup/help-categories/",
        display_key="category_name",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "summary": field.textarea(
        tab="content",
        label="Summary",
        rows=2,
        required=False,
        table=True,
        search=True,
        help_text=(
            "Satu kalimat yang tampil di kartu daftar. Ini yang dibaca "
            "orang sebelum memutuskan membuka artikelnya."
        ),
        order=30,
    ),

    "content": field.richtext(
        tab="content",
        label="Content",
        required=False,
        table=False,
        search=False,
        layout="full",
        help_text=(
            "Isi panduan. Tulis langkah demi langkah dan sebut nama "
            "tombol persis seperti yang tertulis di layar."
        ),
        order=40,
    ),

    "video_url": field.url(
        tab="content",
        label="Video URL",
        required=False,
        table=False,
        help_text="Tautan video tutorial, kalau ada.",
        order=50,
    ),
}


PUBLISHING_FIELDS = {
    "status": field.select(
        tab="publishing",
        label="Status",
        options=[
            {"label": "Draft", "value": "draft"},
            {"label": "Published", "value": "published"},
        ],
        display_key="status_label",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text="Hanya yang Published yang muncul di Help Center.",
        order=110,
    ),

    "sort_order": field.integer(
        tab="publishing",
        label="Sort Order",
        required=False,
        table=True,
        sortable=True,
        help_text="Urutan dalam kategorinya. Angka kecil di atas.",
        order=120,
    ),

    "route_prefix": field.text(
        tab="publishing",
        label="Related Screen",
        required=False,
        table=True,
        filter=False,
        help_text=(
            "Rute layar yang dijelaskan, mis. `/hr/leave`. Artikel ini "
            "otomatis ditawarkan saat pengguna membuka layar itu. "
            "Dikosongkan = tidak menempel ke layar mana pun."
        ),
        order=130,
    ),

    "role": field.lookup(
        tab="publishing",
        label="Visible To Role",
        lookup_endpoint="/api/accounts/lookup/roles/",
        display_key="role_name",
        required=False,
        table=True,
        filter=True,
        help_text=(
            "Dikosongkan = terbaca semua pengguna. Ini penyaring "
            "tampilan, bukan penjagaan rahasia — jangan menaruh data "
            "sensitif di artikel panduan."
        ),
        order=140,
    ),

    "keywords": field.text(
        tab="publishing",
        label="Search Keywords",
        required=False,
        table=False,
        search=True,
        help_text=(
            "Kata yang dipakai pengguna tapi tidak ada di isi artikel "
            "— mis. 'ijin' untuk artikel berjudul 'Cuti'. Dipisah koma."
        ),
        order=150,
    ),

    "icon": field.text(
        tab="publishing",
        label="Icon",
        required=False,
        table=False,
        help_text="Kosong = ikut ikon kategorinya.",
        order=160,
    ),

    "slug": field.text(
        tab="publishing",
        label="Slug",
        required=False,
        table=False,
        help_text=(
            "Bagian URL artikel. Dikosongkan = diturunkan dari judul. "
            "Mengubahnya membuat tautan lama ke artikel ini mati."
        ),
        order=170,
    ),

    "code": field.text(
        tab="publishing",
        label="Code",
        required=False,
        table=False,
        modes=["edit"],
        help_text="Kode tetap untuk seed. Tidak tampil ke pembaca.",
        order=180,
    ),
}


# Statistik baca. Ditaruh di tabnya sendiri dan read-only: angkanya
# milik sistem, dan kotak yang bisa diketik di sebelah "Views" adalah
# undangan untuk mengisinya.
STATS_FIELDS = {
    "view_count": field.integer(
        tab="stats",
        label="Views",
        required=False,
        table=True,
        sortable=True,
        modes=["edit"],
        display=True,
        read_only=True,
        order=210,
    ),

    "helpful_count": field.integer(
        tab="stats",
        label="Helpful",
        required=False,
        table=True,
        sortable=True,
        modes=["edit"],
        display=True,
        read_only=True,
        order=220,
    ),

    "not_helpful_count": field.integer(
        tab="stats",
        label="Not Helpful",
        required=False,
        table=True,
        sortable=True,
        modes=["edit"],
        display=True,
        read_only=True,
        order=230,
    ),

    "published_at": field.datetime(
        tab="stats",
        label="Published At",
        required=False,
        table=False,
        sortable=True,
        modes=["edit"],
        display=True,
        read_only=True,
        help_text="Diisi otomatis saat status berubah jadi Published.",
        order=240,
    ),
}


HELP_ARTICLE_SCHEMA = {
    "module": "administration/help-articles",
    "name": "HelpArticle",
    "label": "Help Article",
    # Rutenya di bawah Administration, API-nya di app-nya sendiri —
    # lihat catatan di `category/views.py`. Ditulis eksplisit karena
    # generator akan menurunkannya dari nama module kalau dikosongkan.
    "endpoint": "/api/helpcenter/articles/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Help Article",
            description=(
                "Panduan yang dibaca pengguna di Help Center. Yang "
                "berstatus Draft tidak terlihat siapa pun kecuali di "
                "layar ini."
            ),
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
            tabs=["content", "publishing", "stats"],
        ),
    },

    "tabs": [
        tabs.form(
            key="content",
            label="Content",
            fields=list(CONTENT_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="publishing",
            label="Publishing",
            fields=list(PUBLISHING_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
        tabs.form(
            key="stats",
            label="Statistics",
            fields=list(STATS_FIELDS.keys()),
            modes=["edit"],
            order=30,
            show_on_create=False,
        ),
    ],

    "fields": {
        **CONTENT_FIELDS,
        **PUBLISHING_FIELDS,
        **STATS_FIELDS,
        # Kolom turunan: ada di payload supaya `display_key` menemukan
        # nilainya, tapi tidak perlu jadi kolom tabel sendiri.
        **{
            name: {
                "table": False,
                "filter": False,
                "search": False,
                "sortable": False,
            }
            for name in ("category_name", "role_name", "status_label")
        },
    },
}


class HelpArticleViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = HelpArticleSerializer
    service_class = HelpArticleService

    framework_module = "administration/help-articles"
    schema = HELP_ARTICLE_SCHEMA

    search_fields = [
        "title",
        "summary",
        "keywords",
        "code",
        "category__name",
    ]

    filterset_fields = ["category", "status", "role"]

    ordering_fields = [
        "title",
        "sort_order",
        "status",
        "view_count",
        "helpful_count",
        "created_at",
    ]

    ordering = ["category__sort_order", "sort_order", "title"]

    def get_queryset(self):
        return (
            HelpArticle.objects
            .select_related("category", "role")
            .filter(is_deleted=False)
        )
