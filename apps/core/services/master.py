from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.services.base import BaseService


class BaseMasterService(BaseService):
    """
    Service dasar untuk master data yang memiliki:
    - relasi ke model lain;
    - child/detail;
    - validasi bisnis;
    - proses penyimpanan tambahan.
    """

    @classmethod
    def get_queryset(cls):
        queryset = super().get_queryset()

        model = cls.get_model()
        field_names = {
            field.name
            for field in model._meta.get_fields()
        }

        if "is_deleted" in field_names:
            queryset = queryset.filter(is_deleted=False)

        return queryset

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
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
        return data

    @classmethod
    def save_children(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> None:
        """
        Override pada service yang memiliki detail/child.

        Contoh:
        WorkScheduleService.save_children(...)
        """
        pass

    @classmethod
    def before_create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = super().before_create(
            data=data,
            user=user,
            **kwargs,
        )

        data = cls.prepare_create_data(
            data=data,
            user=user,
            **kwargs,
        )

        model = cls.get_model()
        field_names = {
            field.name
            for field in model._meta.get_fields()
        }

        if user is not None and "created_by" in field_names:
            data.setdefault("created_by", user)

        return data

    @classmethod
    def before_update(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = super().before_update(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        data = cls.prepare_update_data(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        field_names = {
            field.name
            for field in instance._meta.get_fields()
        }

        if user is not None and "updated_by" in field_names:
            data["updated_by"] = user

        return data

    @classmethod
    @transaction.atomic
    def create_with_children(
        cls,
        *,
        data: dict[str, Any],
        children: dict[str, Any] | None = None,
        user=None,
        **kwargs,
    ):
        instance = cls.create(
            data=data,
            user=user,
            **kwargs,
        )

        cls.save_children(
            instance=instance,
            data=children or {},
            user=user,
            **kwargs,
        )

        return instance

    @classmethod
    @transaction.atomic
    def update_with_children(
        cls,
        *,
        instance,
        data: dict[str, Any],
        children: dict[str, Any] | None = None,
        user=None,
        **kwargs,
    ):
        instance = cls.update(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        cls.save_children(
            instance=instance,
            data=children or {},
            user=user,
            **kwargs,
        )

        return instance
    # ------------------------------------------------------------------
    # Soft delete
    # ------------------------------------------------------------------

    @classmethod
    def before_soft_delete(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_soft_delete(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def soft_delete(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ):
        """
        Menandai record sebagai terhapus tanpa menghilangkan datanya.

        Dipakai `BaseMasterViewSet` untuk delete satuan maupun bulk.
        Model tanpa kolom `is_deleted` jatuh ke hard delete, karena
        tidak ada tempat menyimpan jejaknya.
        """
        if not hasattr(instance, "is_deleted"):
            return cls.delete(
                instance=instance,
                user=user,
                **kwargs,
            )

        cls.before_soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        instance.is_deleted = True

        update_fields = ["is_deleted"]

        if hasattr(instance, "deleted_at"):
            instance.deleted_at = timezone.now()
            update_fields.append("deleted_at")

        if hasattr(instance, "deleted_by"):
            instance.deleted_by = user
            update_fields.append("deleted_by")

        if hasattr(instance, "updated_at"):
            update_fields.append("updated_at")

        instance.save(update_fields=update_fields)

        # Penghapusan **wajib** tercatat, dan di codebase ini seluruh
        # delete adalah soft delete — jadi tanpa baris ini jejak audit
        # tidak pernah memuat satu pun penghapusan. Justru tindakan yang
        # paling perlu dijawab "siapa yang menghapus ini" yang hilang.
        #
        # Dicatat sebagai `delete`, bukan `update`, walau mekanismenya
        # menulis kolom: yang membaca jejak mencari penghapusannya, dan
        # "is_deleted: false → true" di antara empat puluh baris update
        # tidak bisa dicari.
        cls._audit(
            instance=instance,
            action="delete",
            user=user,
            before={"is_deleted": False},
            after={"is_deleted": True},
        )

        cls.after_soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        return instance

    @classmethod
    @transaction.atomic
    def restore(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ):
        """
        Kebalikan `soft_delete`. Dipakai fitur import untuk
        menghidupkan kembali record yang sebelumnya dihapus.
        """
        if not hasattr(instance, "is_deleted"):
            return instance

        instance.is_deleted = False

        update_fields = ["is_deleted"]

        if hasattr(instance, "deleted_at"):
            instance.deleted_at = None
            update_fields.append("deleted_at")

        if hasattr(instance, "deleted_by"):
            instance.deleted_by = None
            update_fields.append("deleted_by")

        if hasattr(instance, "updated_by"):
            instance.updated_by = user
            update_fields.append("updated_by")

        if hasattr(instance, "updated_at"):
            update_fields.append("updated_at")

        instance.save(update_fields=update_fields)

        # Menghidupkan kembali record yang sudah dihapus adalah tindakan
        # yang sama pentingnya dengan menghapusnya — dan lebih mudah
        # luput, karena tidak ada tombolnya di layar mana pun (jalurnya
        # lewat importer).
        cls._audit(
            instance=instance,
            action="update",
            user=user,
            before={"is_deleted": True},
            after={"is_deleted": False},
        )

        return instance
