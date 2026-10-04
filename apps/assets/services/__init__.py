"""
Service Asset Management.

`operations/` — register, kategori, custody, dan dokumen pergerakan.
Fixed Asset Accounting kelak di `accounting/`, dan arah dependensinya
satu: accounting boleh membaca operations, tidak sebaliknya
(`docs/claude/assets.md` §2).
"""

from .operations import (
    AssetAssignmentService,
    AssetCategoryService,
    AssetCustodyService,
    AssetReservationService,
    AssetReturnService,
    AssetService,
    AssetTransferService,
)


__all__ = [
    "AssetAssignmentService",
    "AssetCategoryService",
    "AssetCustodyService",
    "AssetReservationService",
    "AssetReturnService",
    "AssetService",
    "AssetTransferService",
]
