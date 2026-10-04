from django.db import transaction

from apps.administration.api.dashboard.menu_catalog import (
    DEFAULT_CODES,
    by_code,
    menu_entries,
)
from apps.administration.models import FavoriteMenu


class FavoriteMenuService:
    @staticmethod
    def allowed_routes(user) -> set[str] | None:
        """
        Rute yang masih terlihat untuk pengguna ini, atau `None` kalau ia
        tidak dibatasi sama sekali.

        Kecocokannya **persis**, bukan awalan — beda dari katalog
        aplikasi. Pintasan menunjuk satu layar (`/hr/employees`) dan menu
        terdaftar per layar juga, jadi tidak ada yang perlu ditebak.

        Ini bukan penjagaan: halamannya tetap bisa dibuka lewat URL dan
        yang menolak sungguhan tetap API tiap resource. Ini soal tidak
        menyodorkan pintu yang tidak akan dibuka — pegawai biasa yang
        menu Employees-nya dicabut tidak boleh ditawari pintasan ke sana.
        """
        from apps.accounts.api.menu_permissions.access import MenuAccessService

        access = MenuAccessService.visible_for(user)

        if access.get("unrestricted"):
            return None

        return set(access.get("routes") or [])

    @staticmethod
    def rows(user):
        return (
            FavoriteMenu.objects
            .filter(user=user, is_deleted=False)
            .order_by("position")
        )

    @classmethod
    def catalog_entries(cls, user) -> list[dict]:
        """Katalog yang sudah disaring ke hak akses pengguna."""
        allowed = cls.allowed_routes(user)

        return [
            entry
            for entry in menu_entries()
            if allowed is None or entry["link"] in allowed
        ]

    @classmethod
    def get_favorites(cls, user) -> list[dict]:
        """
        Pintasan yang tampil di halaman depan.

        Pengguna yang **belum pernah** memilih mendapat susunan bawaan,
        dan bawaan itu **tidak** ikut ditulis ke database. Sebelumnya
        seed menuliskan lima baris untuk setiap pengguna, dan itu dua
        kesalahan sekaligus: akun yang dibuat setelah seed tidak dapat
        pintasan apa pun sampai ada yang menjalankannya lagi, dan yang
        dapat baris bawaan berhenti mengikuti bawaan yang berubah besok.

        Pembedanya **ada barisnya**, bukan **ada yang tampil** — pengguna
        yang sengaja mengosongkan seluruh pintasannya tetap punya baris
        (semuanya `is_visible=False`), dan bawaannya tidak boleh muncul
        lagi seolah simpanannya gagal.
        """
        catalog = by_code()

        allowed = cls.allowed_routes(user)

        def permitted(code: str) -> bool:
            entry = catalog.get(code)

            if entry is None:
                return False

            return allowed is None or entry["link"] in allowed

        stored = list(cls.rows(user))

        if not stored:
            return [
                {**catalog[code], "position": index, "is_visible": True}
                for index, code in enumerate(DEFAULT_CODES)
                if permitted(code)
            ]

        rows = [
            row
            for row in stored
            if row.is_visible and permitted(row.menu_code)
        ]

        result = []

        for index, row in enumerate(rows):
            entry = catalog[row.menu_code]

            # Judul, ikon, dan rute selalu dari katalog: baris lama yang
            # menyimpan nama menu sebelum diganti tidak boleh membuat
            # pintasannya menampilkan judul yang sudah tidak dipakai —
            # apalagi menunjuk rute yang sudah dipindah.
            result.append({
                **entry,
                "badge": row.badge,
                "position": index,
                "is_visible": True,
            })

        return result

    @classmethod
    def get_catalog(cls, user) -> list[dict]:
        """Seluruh katalog + penanda mana yang sedang dipilih pengguna."""
        chosen = [item["menu_code"] for item in cls.get_favorites(user)]

        entries = [
            {
                **entry,
                "is_favorite": entry["menu_code"] in chosen,

                # Posisi global, bukan dua deret yang bisa bertabrakan:
                # yang dipilih menempati 0..n-1 sesuai urutan pengguna,
                # sisanya menyusul di belakang. Frontend cukup memakai
                # urutan daftarnya apa adanya.
                "position": (
                    chosen.index(entry["menu_code"])
                    if entry["menu_code"] in chosen
                    else len(chosen) + entry["position"]
                ),
            }
            for entry in cls.catalog_entries(user)
        ]

        return sorted(entries, key=lambda item: item["position"])

    @classmethod
    @transaction.atomic
    def set_favorites(cls, user, codes) -> list[dict]:
        """
        Menyimpan susunan pilihan sekaligus; urutan daftar = posisinya.

        Ditulis ulang seluruhnya, bukan ditambal per baris: susunan ini
        satu kesatuan, dan menyimpannya sebagian membuat urutan di layar
        berbeda dari yang tersimpan tanpa ada yang bisa menjelaskannya.
        """
        catalog = by_code()

        # Katalog **penuh** yang jadi acuan penulisan, bukan yang sudah
        # disaring hak akses: pintasan yang sedang tidak terlihat karena
        # menunya dicabut sementara tidak boleh ikut terhapus dari
        # pilihan orangnya.
        entries = menu_entries()

        wanted = []

        for code in codes or []:
            code = str(code).strip()

            # Kode di luar katalog dilewati, bukan ditolak — menu bisa
            # menyusut saat layar digabung, dan susunan lama yang masih
            # menyebutnya tidak boleh menggagalkan seluruh penyimpanan.
            if code in catalog and code not in wanted:
                wanted.append(code)

        rows = [
            FavoriteMenu(
                user=user,
                menu_code=entry["menu_code"],
                title=entry["title"],
                description=entry["description"],
                link=entry["link"],
                icon=entry["icon"],
                color=entry["color"],
                badge="",
                is_visible=entry["menu_code"] in wanted,
                position=(
                    wanted.index(entry["menu_code"])
                    if entry["menu_code"] in wanted
                    else len(wanted) + entry["position"]
                ),
            )
            for entry in entries
        ]

        # Hard delete, bukan soft: ini preferensi tampilan, tidak ada
        # jejak yang perlu disimpan — dan `uniq_favorite_menu_user_code`
        # tidak dikondisikan ke `is_deleted`, jadi baris yang ditandai
        # terhapus justru menghalangi penyimpanan berikutnya.
        FavoriteMenu.objects.filter(user=user).delete()

        FavoriteMenu.objects.bulk_create(rows)

        return cls.get_favorites(user)
