"""
Jejak audit: siapa mengubah apa, kapan, dan dari mana.

Tabel `AuditTrail`, endpoint, dan layarnya sudah lama ada — tapi **tidak
ada satu baris kode pun yang menulisnya**, jadi tabelnya 0 baris sejak
tenant pertama dibuat. Pola yang sama dengan `Role.permissions`,
`RoleMenuPermission`, dan kewenangan `RoleAssignment` sebelum masing-masing
disambungkan. Ini yang menulisnya.

Dipanggil dari `BaseService` — satu tempat, bukan ditaburkan di tiap
service. Seluruh mutasi di codebase ini memang lewat sana.

Tiga keputusan yang menentukan bentuknya
----------------------------------------

**Gagal mencatat tidak boleh membatalkan perubahannya.** Penyimpanan
gaji yang gagal gara-gara baris audit adalah kerusakan yang jauh lebih
besar daripada satu baris jejak yang hilang. Karena itu penulisannya
dibungkus savepoint sendiri dan kegagalannya dicatat `logger.exception`
— tanpa savepoint, error di dalam transaksi induk membuat seluruh
transaksinya tidak bisa di-commit lagi meski exception-nya ditangkap.

**Yang tanpa pengguna tidak dicatat.** Seed, importer, dan perintah
manajemen mengoper `user=None`; mencatat semuanya membuat satu
`seed_demo_workforce` menulis ratusan baris dan menenggelamkan
perubahan yang benar-benar dilakukan orang. Jejak audit menjawab "siapa
yang mengubah ini", dan jawaban "sistem, saat seed" tidak pernah
ditanyakan.

**Yang disimpan hanya field yang berubah.** Menyalin seluruh record
sebelum dan sesudah membuat tabelnya membengkak dan justru
menyembunyikan perubahannya di antara empat puluh kolom yang sama.
"""

from __future__ import annotations

import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from apps.administration.models import AuditTrail


logger = logging.getLogger(__name__)


# Kolom yang tidak pernah menarik untuk dicatat: audit kolom audit.
IGNORED_FIELDS = {
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "deleted_at",
    "deleted_by",
    "password",
}


MAX_REPR = 255


class AuditAction:
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class AuditTrailService:
    @staticmethod
    def list():
        return AuditTrail.objects.select_related(
            "company",
            "location",
            "user",
        ).order_by("-created_at")

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @staticmethod
    def snapshot(instance) -> dict:
        """
        Nilai kolom sederhana sebuah instance, siap dibandingkan.

        Relasi disimpan sebagai id (`<field>_id`), bukan objeknya —
        dua alasan: `JSONField` tidak bisa menyimpan model, dan
        memanggil `str()` pada relasi menembak satu query per kolom.
        """
        if instance is None:
            return {}

        values = {}

        for field in instance._meta.concrete_fields:
            name = field.attname

            if field.name in IGNORED_FIELDS or name in IGNORED_FIELDS:
                continue

            values[name] = getattr(instance, name, None)

        return values

    @staticmethod
    def changes(before: dict, after: dict) -> tuple[dict, dict]:
        """Hanya kolom yang benar-benar berbeda."""
        keys = set(before) | set(after)

        changed = [
            key
            for key in keys
            if before.get(key) != after.get(key)
        ]

        return (
            {key: before.get(key) for key in changed},
            {key: after.get(key) for key in changed},
        )

    @classmethod
    def record(
        cls,
        *,
        instance,
        action: str,
        user=None,
        before: dict | None = None,
        after: dict | None = None,
        module: str = "",
    ) -> None:
        from apps.core.middleware.current_user import get_request_context

        context = get_request_context()

        actor = user or context.get("user")

        if actor is None or not getattr(actor, "is_authenticated", False):
            return

        try:
            with transaction.atomic():
                cls._write(
                    instance=instance,
                    action=action,
                    actor=actor,
                    before=before,
                    after=after,
                    module=module,
                    context=context,
                )
        except Exception:
            # Sengaja ditelan. Lihat catatan di kepala berkas: baris
            # jejak yang hilang jauh lebih murah daripada perubahan yang
            # dibatalkan.
            logger.exception(
                "Gagal mencatat audit %s pada %s",
                action,
                type(instance).__name__,
            )

    @classmethod
    def _write(
        cls,
        *,
        instance,
        action: str,
        actor,
        before: dict | None,
        after: dict | None,
        module: str,
        context: dict,
    ) -> None:
        meta = instance._meta

        AuditTrail.objects.create(
            company=getattr(instance, "company", None),
            location=getattr(instance, "location", None),
            user=actor,
            action=action,
            module=module or meta.app_label,
            object_type=meta.model_name,
            object_id=str(instance.pk),
            object_repr=str(instance)[:MAX_REPR],
            before=cls._jsonable(before),
            after=cls._jsonable(after),
            ip_address=context.get("ip_address"),
            user_agent=context.get("user_agent") or "",
        )

    @staticmethod
    def _jsonable(values: dict | None) -> dict | None:
        """
        Nilai yang `JSONField` memang bisa menyimpannya.

        `date`, `Decimal`, dan `UUID` ditangani `DjangoJSONEncoder`.
        Sisanya jatuh ke `str` lewat `default=` — dan itu bukan
        kemalasan, itu syarat supaya jejaknya tidak hilang.

        Kejadian nyata: `PrintSetting.logo` bertipe `ImageFieldFile`,
        yang tidak dikenali encoder mana pun. Tanpa jaring ini seluruh
        pemanggilan `record()` untuk model itu melempar, ditelan
        `except`, dan tabel auditnya **tetap nol baris** — persis
        keadaan yang sedang diperbaiki, cuma dengan penyebab berbeda.
        Satu tipe kolom tak terduga tidak boleh mematikan pencatatan
        seluruh model.
        """
        if not values:
            return None

        import json

        return json.loads(
            json.dumps(values, cls=DjangoJSONEncoder, default=str),
        )
