"""
Layar admin kategori panduan.
"""

from apps.framework.builders import field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.helpcenter.models import HelpCategory
from apps.helpcenter.services import HelpCategoryService

from .serializers import HelpCategorySerializer


GENERAL_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        help_text="Kode tetap. Dipakai seed, tidak tampil ke pembaca.",
        order=10,
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        help_text="Judul kelompok di sidebar Help Center.",
        order=20,
    ),

    "module": field.select(
        tab="general",
        label="Module",
        options=[
            {"label": "General", "value": ""},
            {"label": "HR", "value": "hr"},
            {"label": "Payroll", "value": "payroll"},
            {"label": "Administration", "value": "administration"},
            {"label": "Workflow", "value": "workflow"},
            {"label": "Finance", "value": "finance"},
            {"label": "Supply Chain", "value": "scm"},
        ],
        required=False,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Modul yang dijelaskan. Dikosongkan = panduan umum yang "
            "tidak menempel ke modul mana pun."
        ),
        order=30,
    ),

    "icon": field.text(
        tab="general",
        label="Icon",
        required=False,
        table=False,
        help_text=(
            "Nama ikon Nuxt UI, mis. `i-lucide-rocket`. Nama yang "
            "tidak dikenal jatuh ke ikon bawaan tanpa error."
        ),
        order=40,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        search=True,
        order=50,
    ),

    "sort_order": field.integer(
        tab="general",
        label="Sort Order",
        required=False,
        table=True,
        sortable=True,
        help_text="Angka kecil tampil lebih dulu.",
        order=60,
    ),

    "is_published": field.switch(
        tab="general",
        label="Published",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Dimatikan: kategori beserta seluruh artikelnya hilang "
            "dari Help Center, tapi tetap bisa disunting di sini."
        ),
        order=70,
    ),

    "article_count": field.integer(
        tab="general",
        label="Articles",
        required=False,
        table=True,
        sortable=False,
        modes=["edit"],
        display=True,
        read_only=True,
        order=80,
    ),
}


HELP_CATEGORY_SCHEMA = {
    "module": "administration/help-categories",
    "name": "HelpCategory",
    "label": "Help Category",
    # `framework_module` menentukan letak halaman Nuxt, `endpoint`
    # menentukan API-nya, dan keduanya memang **tidak** sama di sini:
    # layarnya duduk di bawah Administration (supaya sidebar-nya
    # benar), API-nya di app-nya sendiri. Kalau `endpoint` tidak
    # ditulis eksplisit, generator menurunkannya dari nama module dan
    # tabelnya menampilkan "No results." tanpa satu pun pesan error.
    "endpoint": "/api/helpcenter/categories/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Help Category",
            description=(
                "Kelompok artikel panduan di Help Center. Kategori "
                "yang belum punya artikel terbit tidak ditampilkan ke "
                "pembaca."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },

    "tabs": [
        tabs.form(
            key="general",
            label="General",
            fields=list(GENERAL_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
    ],

    "fields": GENERAL_FIELDS,
}


class HelpCategoryViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = HelpCategorySerializer
    service_class = HelpCategoryService

    framework_module = "administration/help-categories"
    schema = HELP_CATEGORY_SCHEMA

    search_fields = ["code", "name", "description"]
    filterset_fields = ["module", "is_published"]
    ordering_fields = ["sort_order", "code", "name", "created_at"]
    ordering = ["sort_order", "name"]

    def get_queryset(self):
        return (
            HelpCategory.objects
            .prefetch_related("articles")
            .filter(is_deleted=False)
        )
