"""
Satu-satunya penulis `AssetCustody` (`docs/claude/assets.md` §12).

* `open_initial` — custody STORAGE pertama saat aset diaktifkan;
* `move` — tutup custody yang sedang terbuka dan buka yang baru, dipakai
  `complete` dokumen Assignment (dan kelak Transfer/Return).

Tidak ada model, serializer, atau dokumen yang menulis `AssetCustody`
di luar kelas ini.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.assets.models import (
    Asset,
    AssetCustody,
    AssetStatus,
    CustodyType,
)


REGISTRATION = "registration"


@dataclass(frozen=True)
class CustodyTarget:
    """Custody yang akan dibuka `move()`. Bentuknya divalidasi database."""

    custody_type: str
    location: object
    facility: object = None
    employee: object = None
    department: object = None
    pic_employee: object = None


class AssetCustodyService:
    @classmethod
    def open_initial(cls, *, asset: Asset, user=None) -> AssetCustody:
        """
        Custody STORAGE pertama di lokasi register aset.

        Dipanggil hanya dari `AssetService.activate()`, di dalam
        transaksinya dan sesudah baris asetnya dikunci. `full_clean()`
        ikut memeriksa constraint custody terbuka, jadi pemanggil lain
        yang lolos dari kunci tetap tertahan sebelum `INSERT`; yang
        lolos dari keduanya tertahan constraint database.
        """
        custody = AssetCustody(
            asset=asset,
            company_id=asset.company_id,
            custody_type=CustodyType.STORAGE,
            location_id=asset.location_id,
            facility_id=asset.facility_id,
            started_on=timezone.localdate(),
            start_condition=asset.condition,
            opened_by_type=REGISTRATION,
            opened_by_id=str(asset.pk),
            created_by=user,
            updated_by=user,
        )

        custody.full_clean()
        custody.save()

        return custody

    @classmethod
    @transaction.atomic
    def move(
        cls,
        *,
        asset_id: int,
        expected_custody_id: int,
        target: CustodyTarget,
        effective_date: date,
        source_type: str,
        source_id,
        condition: str = "",
        user=None,
    ) -> AssetCustody:
        """
        Pindahkan custody satu aset — tutup yang terbuka, buka `target`.

        Satu transaksi; baris aset **dan** custody terbukanya dikunci, lalu
        custody yang sedang terbuka harus persis `expected_custody_id`
        (dokumen yang dibuat atas custody lama ditolak, bukan menimpa
        custody yang sudah berpindah). Salinan `location`/`facility` aset
        ikut diperbarui di transaksi yang sama.

        Gagal di langkah mana pun — termasuk sesudah custody lama ditutup —
        seluruhnya rollback: tidak ada custody setengah pindah.
        """
        asset = (
            Asset.objects
            .select_for_update(of=("self",))
            .filter(pk=asset_id, is_deleted=False)
            .first()
        )

        if asset is None or asset.status != AssetStatus.ACTIVE:
            raise ValidationError("Aset tidak aktif atau sudah dihapus.")

        current = (
            AssetCustody.objects
            .select_for_update()
            .filter(pk=asset.current_custody_id)
            .first()
        )

        if (
            current is None
            or current.pk != expected_custody_id
            or current.ended_on is not None
        ):
            raise ValidationError(
                "Custody aset sudah berubah sejak dokumen ini dibuat. "
                "Muat ulang dokumennya.",
            )

        cls._assert_target(asset=asset, target=target)

        if effective_date > timezone.localdate():
            raise ValidationError(
                {"handover_date": "Tanggal serah terima tidak boleh di masa depan."},
            )

        if effective_date < current.started_on:
            raise ValidationError({
                "handover_date": (
                    "Tanggal serah terima tidak boleh sebelum custody saat "
                    f"ini dimulai ({current.started_on:%d-%m-%Y})."
                ),
            })

        condition = condition or asset.condition

        cls._close(
            custody=current,
            on=effective_date,
            condition=condition,
            source_type=source_type,
            source_id=source_id,
            user=user,
        )

        opened = cls._open(
            asset=asset,
            target=target,
            on=effective_date,
            condition=condition,
            source_type=source_type,
            source_id=source_id,
            user=user,
        )

        before = {
            "current_custody": current.pk,
            "location": asset.location_id,
            "facility": asset.facility_id,
        }

        asset.current_custody = opened
        asset.location = target.location
        asset.facility = target.facility
        asset.updated_by = user
        asset.save(update_fields=[
            "current_custody",
            "location",
            "facility",
            "updated_by",
            "updated_at",
        ])

        from apps.administration.api.audit.services.audit_service import (
            AuditTrailService,
        )

        AuditTrailService.record(
            instance=asset,
            action="update",
            user=user,
            before=before,
            after={
                "current_custody": opened.pk,
                "custody_type": opened.custody_type,
                "location": asset.location_id,
                "facility": asset.facility_id,
                "source": f"{source_type}:{source_id}",
            },
        )

        return opened

    @staticmethod
    def _assert_target(*, asset: Asset, target: CustodyTarget) -> None:
        """
        Aturan pemilik — berlaku untuk dokumen apa pun yang memanggil
        `move`. Kebijakan pemegang (pegawai lintas company, PIC) milik
        dokumennya, bukan di sini.
        """
        errors = {}

        if target.location is None:
            errors["location"] = "Lokasi tujuan wajib diisi."
        elif target.location.company_id != asset.company_id:
            errors["location"] = "Lokasi tujuan bukan milik company pemilik aset."

        if target.facility is not None and target.location is not None:
            if (
                target.facility.company_id != asset.company_id
                or target.facility.location_id != target.location.pk
            ):
                errors["facility"] = "Fasilitas tidak berada di lokasi tujuan."

        if (
            target.department is not None
            and target.department.company_id != asset.company_id
        ):
            errors["department"] = "Department bukan milik company pemilik aset."

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _close(*, custody, on, condition, source_type, source_id, user):
        custody.ended_on = on
        custody.end_condition = condition
        custody.closed_by_type = source_type
        custody.closed_by_id = str(source_id)
        custody.updated_by = user
        custody.save(update_fields=[
            "ended_on",
            "end_condition",
            "closed_by_type",
            "closed_by_id",
            "updated_by",
            "updated_at",
        ])

    @staticmethod
    def _open(*, asset, target, on, condition, source_type, source_id, user):
        custody = AssetCustody(
            asset=asset,
            company_id=asset.company_id,
            custody_type=target.custody_type,
            employee=target.employee,
            pic_employee=target.pic_employee,
            department=target.department,
            location=target.location,
            facility=target.facility,
            started_on=on,
            start_condition=condition,
            opened_by_type=source_type,
            opened_by_id=str(source_id),
            created_by=user,
            updated_by=user,
        )

        custody.full_clean()
        custody.save()

        return custody

    # ------------------------------------------------------------------
    # Audit read-only
    # ------------------------------------------------------------------

    @classmethod
    def integrity_issues(cls) -> list[dict]:
        """
        Pelanggaran invariant custody yang tidak bisa dijaga constraint
        database sendirian — dibaca perintah `audit_asset_custody` dan
        test. **Tidak menulis apa pun.**
        """
        issues: list[dict] = []

        active = (
            Asset.objects
            .filter(is_deleted=False, status=AssetStatus.ACTIVE)
            .select_related("current_custody")
        )

        for asset in active:
            custody = asset.current_custody

            if custody.asset_id != asset.pk:
                issues.append(cls._issue(asset, "custody saat ini milik aset lain"))
            elif custody.ended_on is not None or custody.is_deleted:
                issues.append(cls._issue(asset, "custody saat ini sudah tertutup"))
            elif (
                custody.location_id != asset.location_id
                or custody.facility_id != asset.facility_id
            ):
                issues.append(
                    cls._issue(asset, "salinan lokasi/fasilitas tidak sama dengan custody"),
                )

        open_rows = (
            AssetCustody.objects
            .filter(ended_on__isnull=True, is_deleted=False)
            .select_related("asset")
        )

        for custody in open_rows:
            if custody.asset.current_custody_id != custody.pk:
                issues.append(
                    cls._issue(custody.asset, "custody terbuka tidak ditunjuk aset"),
                )

        return issues

    @staticmethod
    def _issue(asset: Asset, problem: str) -> dict:
        return {
            "asset_id": asset.pk,
            "asset_code": asset.asset_code,
            "problem": problem,
        }
