from typing import Any

from django.db import models, transaction
from django.shortcuts import get_object_or_404


class BaseService:
    """
    Base service umum untuk operasi CRUD model.
    Service turunan wajib menentukan:
        model = SomeModel
    """

    model: type[models.Model] | None = None

    # Jejak audit ditulis dari sini — satu tempat, bukan ditaburkan di
    # tiap service. Seluruh mutasi di codebase ini memang lewat sini,
    # jadi menyambungkannya di titik ini menutup seluruh modul sekaligus.
    #
    # Dimatikan lewat `audit_enabled = False` pada service yang datanya
    # memang tidak menarik dicatat — ledger append-only, misalnya, sudah
    # jadi jejaknya sendiri.
    audit_enabled: bool = True

    @classmethod
    def _audit(cls, *, instance, action, user=None, before=None, after=None):
        if not cls.audit_enabled:
            return

        from apps.administration.api.audit.services.audit_service import (
            AuditTrailService,
        )

        AuditTrailService.record(
            instance=instance,
            action=action,
            user=user,
            before=before,
            after=after,
        )

    @classmethod
    def get_model(cls) -> type[models.Model]:
        if cls.model is None:
            raise NotImplementedError(
                f"{cls.__name__} harus menentukan atribut 'model'."
            )

        return cls.model

    @classmethod
    def get_queryset(cls):
        return cls.get_model().objects.all()

    @classmethod
    def get_by_id(cls, pk: Any):
        return get_object_or_404(
            cls.get_queryset(),
            pk=pk,
        )

    @classmethod
    def _split_many_to_many(
        cls,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Memisahkan kolom ManyToMany dari kolom biasa.

        Django melarang `setattr` pada m2m — *"Direct assignment to the
        forward side of a many-to-many set is prohibited"* — dan
        barisnya memang tidak bisa ditulis sebelum induknya punya pk.
        Jadi m2m dikeluarkan dari data, dipasang lewat `.set()` sesudah
        `save()`.

        Kolom yang **tidak disebut** `data` tidak ikut terbawa ke sini,
        dan itulah yang membuat PATCH parsial tidak menghapus relasi
        yang sudah ada: yang tidak dikirim tidak disentuh.
        """
        names = {
            field.name for field in cls.get_model()._meta.many_to_many
        }

        if not names:
            return data, {}

        plain = {k: v for k, v in data.items() if k not in names}
        related = {k: v for k, v in data.items() if k in names}

        return plain, related

    @staticmethod
    def _apply_many_to_many(instance, values: dict[str, Any]) -> None:
        """
        `None` dan list kosong sama-sama berarti **kosongkan** — itu
        pilihan yang memang dikirim pengguna, bukan ketiadaan kirim.
        """
        for name, value in values.items():
            getattr(instance, name).set(value or [])

    @classmethod
    def before_create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return data

    @classmethod
    def after_create(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> models.Model:
        return instance

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        model = cls.get_model()

        prepared_data = cls.before_create(
            data=dict(data),
            user=user,
            **kwargs,
        )

        prepared_data, related_data = cls._split_many_to_many(prepared_data)

        instance = model(**prepared_data)

        if hasattr(instance, "full_clean"):
            instance.full_clean()

        instance.save()

        # Sesudah `save()` (butuh pk) tapi sebelum `after_create`,
        # supaya hook turunan melihat relasinya sudah terpasang.
        cls._apply_many_to_many(instance, related_data)

        result = cls.after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

        cls._audit(
            instance=result or instance,
            action="create",
            user=user,
            after=cls._snapshot(result or instance),
        )

        return result

    @classmethod
    def before_update(
        cls,
        *,
        instance: models.Model,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return data

    @classmethod
    def after_update(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> models.Model:
        return instance

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: models.Model,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        before_values = cls._snapshot(instance)

        prepared_data = cls.before_update(
            instance=instance,
            data=dict(data),
            user=user,
            **kwargs,
        )

        prepared_data, related_data = cls._split_many_to_many(prepared_data)

        for field_name, value in prepared_data.items():
            setattr(instance, field_name, value)

        if hasattr(instance, "full_clean"):
            instance.full_clean()

        instance.save()

        cls._apply_many_to_many(instance, related_data)

        result = cls.after_update(
            instance=instance,
            user=user,
            **kwargs,
        )

        target = result or instance

        # Hanya kolom yang berubah. Menyalin seluruh record membuat
        # perubahan satu kolom tenggelam di antara empat puluh yang sama.
        changed_before, changed_after = cls._diff(
            before_values,
            cls._snapshot(target),
        )

        if changed_after:
            cls._audit(
                instance=target,
                action="update",
                user=user,
                before=changed_before,
                after=changed_after,
            )

        return result

    @classmethod
    def before_delete(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_delete(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def delete(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> None:
        cls.before_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        before_values = cls._snapshot(instance)

        # Dicatat **sebelum** dihapus: sesudahnya `instance.pk` sudah
        # `None`, dan baris jejak yang tidak menunjuk objek apa pun
        # tidak bisa ditelusuri.
        cls._audit(
            instance=instance,
            action="delete",
            user=user,
            before=before_values,
        )

        instance.delete()

        cls.after_delete(
            instance=instance,
            user=user,
            **kwargs,
        )
    # ------------------------------------------------------------------
    # Pembantu audit
    # ------------------------------------------------------------------

    @staticmethod
    def _snapshot(instance) -> dict:
        from apps.administration.api.audit.services.audit_service import (
            AuditTrailService,
        )

        return AuditTrailService.snapshot(instance)

    @staticmethod
    def _diff(before: dict, after: dict) -> tuple[dict, dict]:
        from apps.administration.api.audit.services.audit_service import (
            AuditTrailService,
        )

        return AuditTrailService.changes(before, after)
