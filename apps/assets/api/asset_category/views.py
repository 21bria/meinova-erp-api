"""
Master kategori aset — `/api/assets/categories/`.

Tanpa `data_scope`: kategori berlaku untuk seluruh tenant dan bukan
rahasia per lokasi, sama seperti master referensi lain. Baca terbuka
(dropdown aset di layar mana pun memakainya); tulis dijaga izin model
`assets.add/change/delete_assetcategory` lewat `ModelPermission` bawaan
`BaseMasterViewSet`.
"""

from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.assets.services import AssetCategoryService

from .schema import ASSET_CATEGORY_SCHEMA
from .serializers import AssetCategorySerializer


class AssetCategoryViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = AssetCategorySerializer
    service_class = AssetCategoryService

    framework_module = "assets/categories"
    schema = ASSET_CATEGORY_SCHEMA

    search_fields = ["code", "name", "description"]
    filterset_fields = ["is_active"]
    ordering_fields = ["sort_order", "code", "name", "created_at"]
    ordering = ["sort_order", "name"]
