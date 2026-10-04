"""
Service Asset Register (`docs/claude/assets.md` §6, §12, §16).

Tiga hal yang harus lewat sini dan tidak boleh diserahkan ke serializer:

* **nomor aset** dari `DocumentNumberService` (AST) — tidak pernah dari
  klien, tidak berubah sesudah dibuat;
* **kolom yang dikunci** — company dan kode selamanya; kategori, lokasi,
  fasilitas, dan kondisi sesudah aset aktif (lokasi pindah lewat dokumen
  custody, kondisi lewat `record_condition`);
* **aktivasi** — DRAFT → ACTIVE + custody STORAGE pertama + log kondisi,
  satu transaksi, baris aset dikunci.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.assets.models import (
    Asset,
    AssetCondition,
    AssetConditionLog,
    AssetCustody,
    AssetStatus,
    ConditionSource,
)
from apps.core.services.master import BaseMasterService

from .custody import AssetCustodyService


NUMBERING_MODULE = "assets"
NUMBERING_DOCUMENT_TYPE = "asset"

TEXT_FIELDS = (
    "name",
    "description",
    "manufacturer",
    "model",
    "serial_number",
    "tag_number",
    "acquisition_reference",
    "supplier_name",
)

# Diisi sistem. Klien tidak pernah menulisnya, termasuk lewat jalur
# non-HTTP yang memanggil service langsung.
SYSTEM_FIELDS = (
    "asset_code",
    "status",
    "current_custody",
    "activated_at",
    "activated_by",
)

# Tidak berubah sesudah aset dibuat.
IMMUTABLE_FIELDS = ("company",)

# Tidak berubah sesudah aset aktif lewat jalur ini.
LOCKED_WHEN_ACTIVE = {
    "category": "Kategori tidak bisa diubah sesudah aset aktif.",
    "location": (
        "Lokasi aset aktif hanya berpindah lewat dokumen custody "
        "(Assignment/Transfer/Return)."
    ),
    "facility": (
        "Fasilitas aset aktif hanya berpindah lewat dokumen custody "
        "(Assignment/Transfer/Return)."
    ),
    "condition": (
        "Kondisi aset aktif dicatat lewat aksi Record Condition, "
        "supaya riwayatnya tidak hilang."
    ),
}


def _key(value):
    """Nilai pembanding untuk kolom biasa maupun FK."""
    return getattr(value, "pk", value)


class AssetService(BaseMasterService):
    model = Asset

    @classmethod
    def list(cls):
        return cls.get_queryset().select_related(
            "company",
            "category",
            "location",
            "facility",
            "current_custody",
            # Kolom Holder + kartu custody (ASSET-6) — tanpa N+1.
            "current_custody__employee",
            "current_custody__department",
            "current_custody__pic_employee",
            "current_custody__location",
            "current_custody__facility",
        )

    # ------------------------------------------------------------------
    # Create / update
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls._normalize(data)

        provided = [
            name for name in SYSTEM_FIELDS
            if data.get(name) not in (None, "")
        ]

        if provided:
            raise ValidationError({
                name: "Diisi sistem, tidak bisa dikirim." for name in provided
            })

        category = data.get("category")

        if category is not None:
            cls._assert_category_usable(category)

        company = data.get("company")

        cls._assert_identity_unique(
            company=company,
            serial_number=data.get("serial_number", ""),
            tag_number=data.get("tag_number", ""),
        )

        data["status"] = AssetStatus.DRAFT

        # Tanpa company `full_clean()` yang menolak; nomor tidak diambil
        # supaya deret tidak terpakai sia-sia.
        if company is not None:
            data["asset_code"] = cls._next_code(company)

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance: Asset,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls._normalize(data)

        errors = {}

        for name in (*SYSTEM_FIELDS, *IMMUTABLE_FIELDS):
            if name in data and _key(data[name]) != _key(getattr(instance, name)):
                errors[name] = "Tidak bisa diubah."

        if instance.status != AssetStatus.DRAFT:
            for name, message in LOCKED_WHEN_ACTIVE.items():
                if name in data and _key(data[name]) != _key(getattr(instance, name)):
                    errors[name] = message

        if errors:
            raise ValidationError(errors)

        if "category" in data and _key(data["category"]) != instance.category_id:
            cls._assert_category_usable(data["category"])

        serial = data.get("serial_number", instance.serial_number)

        cls._assert_identity_unique(
            company=instance.company,
            serial_number=serial,
            tag_number=data.get("tag_number", instance.tag_number),
            exclude_pk=instance.pk,
        )

        if (
            instance.status == AssetStatus.ACTIVE
            and instance.category.requires_serial_number
            and not serial
        ):
            raise ValidationError({
                "serial_number": (
                    "Kategori aset ini mewajibkan serial number."
                ),
            })

        return data

    @classmethod
    def before_soft_delete(cls, *, instance: Asset, user=None, **kwargs) -> None:
        if instance.status != AssetStatus.DRAFT:
            raise ValidationError({
                "status": (
                    "Aset yang sudah aktif tidak bisa dihapus — riwayat "
                    "custody-nya harus tetap terbaca."
                ),
            })

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def activate(cls, *, asset: Asset, user=None) -> Asset:
        """
        DRAFT → ACTIVE + custody STORAGE pertama + log kondisi awal.

        Baris aset dikunci dan statusnya dibaca **ulang** di dalam kunci:
        pemanggil yang memegang objek basi (DRAFT di memori, sudah ACTIVE
        di database) ditolak, bukan membuka custody kedua. Aktivasi kedua
        ditolak, bukan dianggap sukses — pemanggil tidak boleh mengira
        dialah yang mengaktifkan.
        """
        # `of=("self",)`: yang dikunci hanya baris aset. Tanpa itu
        # PostgreSQL menolak kuncinya — `facility` nullable, jadi
        # `select_related` menghasilkan LEFT JOIN, dan FOR UPDATE tidak
        # boleh mengenai sisi nullable outer join. Baris master yang
        # ikut dibaca juga memang tidak perlu dikunci.
        locked = (
            Asset.objects
            .select_for_update(of=("self",))
            .select_related("category", "company", "location", "facility")
            .filter(pk=asset.pk, is_deleted=False)
            .first()
        )

        if locked is None:
            raise ValidationError("Aset tidak ditemukan atau sudah dihapus.")

        if locked.status != AssetStatus.DRAFT:
            raise ValidationError({
                "status": "Aset sudah aktif.",
            })

        cls._assert_category_usable(locked.category)

        if locked.category.requires_serial_number and not locked.serial_number:
            raise ValidationError({
                "serial_number": (
                    "Kategori aset ini mewajibkan serial number sebelum "
                    "aset diaktifkan."
                ),
            })

        cls._assert_identity_unique(
            company=locked.company,
            serial_number=locked.serial_number,
            tag_number=locked.tag_number,
            exclude_pk=locked.pk,
        )

        locked.full_clean()

        if AssetCustody.objects.filter(
            asset=locked,
            ended_on__isnull=True,
            is_deleted=False,
        ).exists():
            raise ValidationError("Aset ini sudah punya custody terbuka.")

        custody = AssetCustodyService.open_initial(asset=locked, user=user)

        now = timezone.now()

        locked.status = AssetStatus.ACTIVE
        locked.current_custody = custody
        locked.activated_at = now
        locked.activated_by = user
        locked.updated_by = user
        locked.save(update_fields=[
            "status",
            "current_custody",
            "activated_at",
            "activated_by",
            "updated_by",
            "updated_at",
        ])

        AssetConditionLog.objects.create(
            asset=locked,
            previous_condition="",
            new_condition=locked.condition,
            source=ConditionSource.REGISTRATION,
            effective_at=now,
            recorded_by=user,
        )

        cls._audit(
            instance=locked,
            action="update",
            user=user,
            before={"status": AssetStatus.DRAFT},
            after={
                "status": AssetStatus.ACTIVE,
                "current_custody": custody.pk,
            },
        )

        return locked

    # ------------------------------------------------------------------
    # Condition
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def record_condition(
        cls,
        *,
        asset: Asset,
        condition: str,
        note: str = "",
        user=None,
    ) -> Asset:
        """
        Inspeksi tanpa pergerakan: satu baris log INSPECTION, dan
        `Asset.condition` mengikuti. Kondisi yang sama tetap dicatat —
        "diperiksa, masih baik" adalah bukti inspeksi.

        Selama DRAFT kondisi disunting lewat form biasa; riwayat baru
        dimulai saat aktivasi.
        """
        if condition not in AssetCondition.values:
            raise ValidationError({"condition": "Kondisi tidak dikenal."})

        locked = (
            Asset.objects
            .select_for_update()
            .filter(pk=asset.pk, is_deleted=False)
            .first()
        )

        if locked is None:
            raise ValidationError("Aset tidak ditemukan atau sudah dihapus.")

        if locked.status != AssetStatus.ACTIVE:
            raise ValidationError({
                "status": (
                    "Kondisi aset DRAFT diubah lewat form; riwayat kondisi "
                    "dimulai saat aset diaktifkan."
                ),
            })

        cls.append_condition(
            asset=locked,
            condition=condition,
            source=ConditionSource.INSPECTION,
            note=note,
            user=user,
        )

        return locked

    @classmethod
    def append_condition(
        cls,
        *,
        asset: Asset,
        condition: str,
        source: str,
        note: str = "",
        user=None,
    ) -> AssetConditionLog:
        """
        Satu-satunya jalan menulis riwayat kondisi sesudah aktivasi.

        Pemanggil wajib sudah mengunci baris asetnya. `Asset.condition`
        mengikuti log terakhir; audit trail hanya bila nilainya berubah.
        """
        if condition not in AssetCondition.values:
            raise ValidationError({"condition": "Kondisi tidak dikenal."})

        previous = asset.condition

        log = AssetConditionLog.objects.create(
            asset=asset,
            previous_condition=previous,
            new_condition=condition,
            source=source,
            effective_at=timezone.now(),
            recorded_by=user,
            note=(note or "").strip(),
        )

        if previous != condition:
            asset.condition = condition
            asset.updated_by = user
            asset.save(update_fields=["condition", "updated_by", "updated_at"])

            cls._audit(
                instance=asset,
                action="update",
                user=user,
                before={"condition": previous},
                after={"condition": condition, "source": source},
            )

        return log

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        for name in TEXT_FIELDS:
            value = data.get(name)

            if value is None and name in data:
                # Kosong = tidak ada, bukan NULL: kolomnya `default=""`.
                data[name] = ""
            elif isinstance(value, str):
                data[name] = value.strip()

        return data

    @staticmethod
    def _assert_category_usable(category) -> None:
        if getattr(category, "is_deleted", False) or not getattr(category, "is_active", True):
            raise ValidationError({
                "category": "Kategori ini sudah tidak aktif.",
            })

    @staticmethod
    def _assert_identity_unique(
        *,
        company,
        serial_number: str,
        tag_number: str,
        exclude_pk=None,
    ) -> None:
        """
        Serial/tag unik per company tanpa membedakan huruf, di antara aset
        yang belum dihapus. Company berbeda boleh sama. Database menjaga
        hal yang sama (`uniq_active_assets_asset_company_serial/_tag`);
        ini yang memberi pesan yang bisa dibaca.
        """
        if company is None:
            return

        queryset = Asset.objects.filter(company=company, is_deleted=False)

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        errors = {}

        if serial_number and queryset.filter(
            serial_number__iexact=serial_number,
        ).exists():
            errors["serial_number"] = (
                f"Serial number '{serial_number}' sudah dipakai aset lain "
                "di company ini."
            )

        if tag_number and queryset.filter(tag_number__iexact=tag_number).exists():
            errors["tag_number"] = (
                f"Tag number '{tag_number}' sudah dipakai aset lain "
                "di company ini."
            )

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _next_code(company) -> str:
        code = DocumentNumberService.next(
            module=NUMBERING_MODULE,
            document_type=NUMBERING_DOCUMENT_TYPE,
            company=company,
        )

        if not code:
            # Berbeda dari dokumen lain yang boleh terbit tanpa nomor:
            # `asset_code` adalah identitas aset, dan constraint menolak
            # yang kosong. Pesannya menyebut apa yang harus diisi.
            raise ValidationError({
                "asset_code": (
                    "Penomoran aset (assets/asset, AST) belum "
                    "dikonfigurasi. Jalankan seed numbering atau tambahkan "
                    "di Numbering Sequence."
                ),
            })

        return code
