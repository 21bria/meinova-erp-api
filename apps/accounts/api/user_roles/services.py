"""
Menugaskan role ke pengguna.

Form User di layar Security cuma menampilkan `role_names` sebagai teks
read-only — tidak ada satu pun kontrol untuk memberikan role, jadi
seluruh RBAC hanya bisa diatur lewat shell. Ini yang menutupnya.

Bentuknya pohon datar (satu tingkat) supaya bisa memakai ulang komponen
centang yang sama dengan Menu Permission dan Role Permission, bukan
komponen keempat yang berperilaku sedikit berbeda.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.accounts.services.role_assignment import (
    assign_roles,
    read_authority,
    set_authority,
)


User = get_user_model()


class UserRoleService:
    @staticmethod
    def get_tree(user_id) -> list[dict]:
        if not user_id:
            return []

        user = User.objects.filter(pk=user_id).first()

        if user is None:
            return []

        held = set(user.roles.values_list("id", flat=True))

        return [
            {
                "id": role.pk,
                "label": f"{role.code} — {role.name}",
                "code": role.code,
                "description": role.description,
                "checked": role.pk in held,
            }
            for role in Role.objects.filter(is_deleted=False).order_by("code")
        ]

    @staticmethod
    def get_authority(user_id) -> list[dict]:
        """
        Kewenangan tiap penugasan milik satu pengguna.

        Terpisah dari `get_tree()` dengan sengaja: keanggotaan dan
        kewenangan dua pertanyaan berbeda, dan urutannya penting —
        role dulu, WHERE-nya kemudian. Layar yang menggabungkan
        keduanya jadi satu simpanan akan memaksa orang menentukan
        kewenangan untuk role yang bahkan belum diputuskan diberikan.
        """
        if not user_id:
            return []

        user = User.objects.filter(pk=user_id).first()

        if user is None:
            return []

        return read_authority(user)

    @staticmethod
    def save_authority(user_id, role_id, *, mode, level="", authorities=()):
        user = User.objects.filter(pk=user_id).first()

        if user is None:
            raise ValueError("Pengguna tidak ditemukan.")

        return set_authority(
            user, role_id,
            mode=mode, level=level, authorities=authorities,
        )

    @staticmethod
    def save(user_id, role_ids) -> dict:
        """
        Menyimpan daftar role **utuh** milik satu pengguna.

        Daftarnya utuh, bukan tambahan: yang tidak ada di dalamnya
        berarti dicabut. Itu sebabnya id yang tidak dikenal ditolak
        alih-alih dilewati — id kedaluwarsa yang diam-diam dibuang akan
        terbaca sebagai perintah mencabut role, dan jawabannya tetap
        sukses. Lihat `apps.accounts.services.role_assignment`.

        Yang dikembalikan menyebut **pencabutan** juga, bukan cuma
        jumlah yang tersimpan. Penyimpanan yang mencabut kewenangan
        harus terbaca dari jawabannya sendiri.
        """
        user = User.objects.get(pk=user_id)

        delta = assign_roles(user, role_ids)

        return {
            "user": user.pk,
            "saved": len(delta.kept) + len(delta.added),
            **delta.as_dict(),
        }
