from django.db import transaction
from django.utils import timezone

from apps.administration.models import Notification, NotificationSetting

# Berapa baris yang ikut di balasan bel. Isi dropdown, bukan halaman —
# yang mau melihat semuanya membuka daftar penuh.
BELL_LIMIT = 10


class NotificationService:
    """
    Notifikasi dalam aplikasi.

    Baris di sini hanya yang jenisnya **memberi tahu** — "kontrak
    berakhir 14 hari lagi", "ulang tahun besok". Yang **perlu tindakan**
    tetap tinggal di kotak masuk workflow dan tidak pernah disalin ke
    sini: notifikasi bisa ditandai terbaca, dan persetujuan yang hilang
    dari layar hanya karena belnya dibersihkan adalah dokumen yang
    mengendap tanpa ada yang merasa ditagih.
    """

    @staticmethod
    def list(user):
        """
        Notifikasi milik satu pengguna.

        Selalu disaring `user` — tidak ada peran mana pun yang berhak
        membaca notifikasi orang lain, jadi penyaringannya di sini,
        bukan diserahkan ke cakupan data.
        """
        return (
            Notification.objects
            .filter(user=user)
            .order_by("-created_at")
        )

    @classmethod
    def unread_count(cls, user) -> int:
        return cls.list(user).filter(is_read=False).count()

    @classmethod
    def bell(cls, user, *, limit: int = BELL_LIMIT):
        """
        Isi dropdown bel: jumlah yang belum dibaca + baris terbaru.

        Yang belum dibaca dihitung dari **seluruh** baris, bukan dari
        potongan `limit` — badge yang berhenti di 10 karena daftarnya
        dipotong memberi tahu panjang daftar, bukan jumlah pekerjaan.
        """
        queryset = cls.list(user)

        return {
            "unread_count": queryset.filter(is_read=False).count(),
            "items": list(queryset[:limit]),
        }

    @classmethod
    @transaction.atomic
    def mark_read(cls, user, ids=None) -> int:
        """
        Tandai terbaca. `ids` kosong = semuanya.

        Disaring `user` juga di sini walau id-nya sudah menunjuk baris
        tertentu — tanpa itu siapa pun bisa menandai terbaca notifikasi
        orang lain hanya dengan menebak id.
        """
        queryset = cls.list(user).filter(is_read=False)

        if ids:
            queryset = queryset.filter(id__in=ids)

        return queryset.update(
            is_read=True,
            read_at=timezone.now(),
        )

    @classmethod
    def push(
        cls,
        user,
        *,
        title,
        message="",
        type="INFO",
        module="",
        link="",
        object_type="",
        object_id="",
    ):
        """
        Tulis satu notifikasi. Ini pintu masuk satu-satunya untuk kode
        yang menghasilkan notifikasi — jangan `Notification.objects
        .create()` langsung, karena dedup di bawah akan terlewat.

        **Aman diulang.** Pengingat dijalankan tugas harian, jadi
        kontrak yang berakhir 30 hari lagi akan diperiksa 30 kali; tanpa
        dedup, belnya terisi 30 baris untuk satu kontrak yang sama.

        Kuncinya `(user, module, object_type, object_id)` yang **belum
        dibaca**. Sengaja hanya yang belum dibaca: yang sudah dibaca
        berarti sudah dilihat orangnya, dan pengingat ulang tahun tahun
        depan memang harus muncul lagi.

        Baris yang menunjuk dokumen berbeda tetap terpisah; yang tanpa
        `object_id` sama sekali tidak pernah didedup — kunci yang isinya
        kosong akan menyatukan hal-hal yang tidak berhubungan.
        """
        setting = NotificationSettingService.get_settings(user)

        if not setting.in_app_enabled:
            return None

        if object_id:
            existing = (
                cls.list(user)
                .filter(
                    is_read=False,
                    module=module,
                    object_type=object_type,
                    object_id=str(object_id),
                )
                .first()
            )

            if existing is not None:
                # Isinya diperbarui, bukan dilewati begitu saja: sisa
                # hari di dalam pesannya berubah tiap hari, dan baris
                # yang menulis "berakhir 30 hari lagi" di hari kesepuluh
                # lebih buruk daripada tidak ada barisnya.
                existing.title = title
                existing.message = message
                existing.type = type
                existing.link = link
                existing.save(
                    update_fields=[
                        "title",
                        "message",
                        "type",
                        "link",
                    ],
                )

                return existing

        return Notification.objects.create(
            user=user,
            title=title,
            message=message,
            type=type,
            module=module,
            link=link,
            object_type=object_type,
            object_id=str(object_id or ""),
        )


class NotificationSettingService:
    @staticmethod
    def list(user):
        return NotificationSetting.objects.filter(user=user)

    @staticmethod
    def get_settings(user):
        setting, _created = NotificationSetting.objects.get_or_create(
            user=user,
        )

        return setting
