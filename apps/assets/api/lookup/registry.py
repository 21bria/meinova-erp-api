from django.db.models import Exists, OuterRef, Q

from apps.framework.lookup import BaseLookup, register_lookup

from apps.assets.api.asset.scope import ASSET_SCOPE
from apps.assets.models import (
    ASSIGNABLE_CONDITIONS,
    Asset,
    AssetCategory,
    AssetOperationReservation,
    AssetStatus,
    CustodyType,
)


# Aset yang sedang diklaim dokumen operasional apa pun (Assignment,
# Return, Transfer) — satu authority, `AssetOperationReservation`.
RESERVED = Exists(
    AssetOperationReservation.objects.filter(
        asset=OuterRef("pk"),
        released_at__isnull=True,
    ),
)


@register_lookup
class AssetCategoryLookup(BaseLookup):
    # Nama registry lookup global lintas domain — `categories` saja akan
    # bertabrakan dengan modul lain, jadi diberi awalan `asset-`.
    # `BaseLookup` sudah membuang baris terhapus dan nonaktif: kategori
    # yang dimatikan tidak bisa dipilih untuk aset baru.
    name = "asset-categories"

    model = AssetCategory

    search_fields = ["code", "name"]

    ordering = ["sort_order", "name"]


@register_lookup
class AssetLookup(BaseLookup):
    # Pemilih aset **aktif** di cakupan data pemakai. DRAFT dan yang
    # terhapus tidak ditawarkan: dokumen tidak pernah boleh menunjuk aset
    # yang belum berdiri. Pemilih per dokumen ada di bawah.
    name = "assets"

    queryset = Asset.objects.filter(status=AssetStatus.ACTIVE)

    label_field = "asset_code"

    search_fields = ["asset_code", "name", "serial_number", "tag_number"]

    filter_fields = ["company_id", "location_id", "category_id"]

    ordering = ["asset_code"]

    data_scope = ASSET_SCOPE

    require_view_permission = True


@register_lookup
class AvailableAssetLookup(BaseLookup):
    """
    Aset yang **boleh diserahkan** lewat Assignment (`docs/claude/assets.md` §9):
    ACTIVE, custody terbuka STORAGE, kondisi layak (`ASSIGNABLE_CONDITIONS`
    — GOOD/FAIR), tidak sedang dipesan dokumen operasional apa pun, belum
    dihapus, di cakupan data pemakai.

    `?target_custody_type=EMPLOYEE|ORGANIZATION` menyaring kategori yang
    boleh dipegang tujuan itu. Tanpa parameter tidak menyaring kategori.
    Ini pemilih, bukan penjaga — service menolak hal yang sama.
    """

    name = "available-assets"

    queryset = (
        Asset.objects
        .filter(
            status=AssetStatus.ACTIVE,
            current_custody__custody_type=CustodyType.STORAGE,
            condition__in=ASSIGNABLE_CONDITIONS,
        )
        .exclude(RESERVED)
    )

    label_field = "asset_code"

    search_fields = ["asset_code", "name", "serial_number", "tag_number"]

    filter_fields = ["company_id", "location_id", "category_id"]

    ordering = ["asset_code"]

    data_scope = ASSET_SCOPE

    require_view_permission = True

    CATEGORY_FLAG = {
        CustodyType.EMPLOYEE: "category__allow_employee_custody",
        CustodyType.ORGANIZATION: "category__allow_organization_custody",
    }

    @classmethod
    def apply_filters(cls, queryset, params):
        queryset = super().apply_filters(queryset, params)

        flag = cls.CATEGORY_FLAG.get(params.get("target_custody_type", ""))

        if flag:
            queryset = queryset.filter(**{flag: True})

        return queryset


@register_lookup
class AssetInUseLookup(BaseLookup):
    """
    Aset yang **sedang dipakai** — pemilih Return:
    ACTIVE, custody terbuka EMPLOYEE atau ORGANIZATION, tidak sedang dipesan
    dokumen operasional apa pun, belum dihapus, di cakupan data pemakai.

    Kondisi tidak menyaring: aset rusak justru yang paling perlu kembali.

    Filter: `custody_type`, `employee_id`, `department_id` (pemegang
    custody terbuka), `location_id`, `company_id`, `category_id`.
    """

    name = "assets-in-use"

    queryset = (
        Asset.objects
        .filter(
            status=AssetStatus.ACTIVE,
            current_custody__custody_type__in=(
                CustodyType.EMPLOYEE,
                CustodyType.ORGANIZATION,
            ),
        )
        .exclude(RESERVED)
    )

    label_field = "asset_code"

    search_fields = ["asset_code", "name", "serial_number", "tag_number"]

    filter_fields = ["company_id", "location_id", "category_id"]

    ordering = ["asset_code"]

    data_scope = ASSET_SCOPE

    require_view_permission = True

    HOLDER_FILTERS = {
        "custody_type": "current_custody__custody_type",
        "employee_id": "current_custody__employee_id",
        "department_id": "current_custody__department_id",
    }

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("current_custody")

    @classmethod
    def serialize(cls, instance):
        # Fase asal ikut dikirim untuk `autofill` form Transfer (ASSET-6):
        # pilihan "Transfer To" disaring dari sini — STORAGE → STORAGE,
        # pemakaian → pemakaian. Penolakannya tetap milik service.
        custody = instance.current_custody

        return {
            "value": instance.pk,
            "label": instance.asset_code,
            "custody_type": custody.custody_type if custody else None,
            "condition": instance.condition,
        }

    @classmethod
    def apply_filters(cls, queryset, params):
        queryset = super().apply_filters(queryset, params)

        for param, path in cls.HOLDER_FILTERS.items():
            values = cls.filter_values(params, param)

            if len(values) == 1:
                queryset = queryset.filter(**{path: values[0]})
            elif values:
                queryset = queryset.filter(**{f"{path}__in": values})

        return queryset


@register_lookup
class TransferableAssetLookup(AssetInUseLookup):
    """
    Asal yang sah untuk **Transfer** (`docs/claude/assets.md` §10):

    * custody EMPLOYEE/ORGANIZATION dengan kondisi layak (GOOD/FAIR) —
      pemakaian → pemakaian; aset rusak dikembalikan lewat Return;
    * custody STORAGE dengan kondisi **apa pun** — STORAGE → STORAGE
      (mis. ke gudang/workshop).

    Selalu ACTIVE, tidak dipesan dokumen apa pun, belum dihapus, di
    cakupan data pemakai. Filter pemegang diwarisi dari `assets-in-use`.
    """

    name = "transferable-assets"

    queryset = (
        Asset.objects
        .filter(status=AssetStatus.ACTIVE)
        .filter(
            Q(
                current_custody__custody_type__in=(
                    CustodyType.EMPLOYEE,
                    CustodyType.ORGANIZATION,
                ),
                condition__in=ASSIGNABLE_CONDITIONS,
            )
            | Q(current_custody__custody_type=CustodyType.STORAGE),
        )
        .exclude(RESERVED)
    )
