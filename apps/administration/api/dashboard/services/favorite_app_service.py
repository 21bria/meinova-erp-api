from django.db import transaction

from apps.administration.api.dashboard.catalog import (
    APP_CATALOG,
    DEFAULT_CODES,
    by_code,
)
from apps.administration.models import FavoriteApp


class FavoriteAppService:
    @staticmethod
    def allowed_codes(user) -> set[str] | None:
        """
        Modul yang menunya masih tersisa untuk pengguna ini, atau `None`
        kalau ia tidak dibatasi sama sekali.

        Kartu aplikasi yang menunya sudah disembunyikan `RoleMenuPermission`
        akan mendarat di halaman dengan sidebar kosong — pegawai biasa
        menekan "Administration" lalu tiba di layar yang tidak punya satu
        pun menu. Itu bukan penjagaan (URL-nya tetap bisa diketik), cuma
        soal tidak menyodorkan pintu yang tidak akan dibuka.

        Kecocokannya lewat awalan rute: menu terdaftar per layar
        (`/hr/employees`), sedangkan kartu menunjuk modulnya (`/hr`).
        """
        from apps.accounts.api.menu_permissions.access import MenuAccessService

        access = MenuAccessService.visible_for(user)

        if access.get("unrestricted"):
            return None

        routes = access.get("routes") or []

        return {
            entry["app_code"]
            for entry in APP_CATALOG
            if any(
                route == entry["link"] or route.startswith(f"{entry['link']}/")
                for route in routes
            )
        }

    @staticmethod
    def rows(user):
        return (
            FavoriteApp.objects
            .filter(user=user, is_deleted=False)
            .order_by("position")
        )

    @classmethod
    def get_favorites(cls, user) -> list[dict]:
        """
        Aplikasi yang tampil di halaman depan.

        Pengguna yang **belum pernah** menyusun sendiri mendapat susunan
        bawaan dari katalog, bukan daftar kosong. Sebelumnya bagian
        Applications kosong untuk semua orang termasuk superuser, dan itu
        terbaca seperti fitur yang rusak padahal memang belum ada isinya.

        Bawaan ini tidak ikut ditulis ke database: menulis saat membaca
        membuat "belum pernah menyusun" jadi keadaan yang tidak bisa
        dibedakan lagi, dan susunan bawaan yang berubah besok tidak akan
        pernah sampai ke pengguna lama.
        """
        catalog = by_code()

        allowed = cls.allowed_codes(user)

        def permitted(code: str) -> bool:
            return allowed is None or code in allowed

        stored = list(cls.rows(user))

        # Pembedanya "pernah menyimpan", bukan "ada yang tampil". Pengguna
        # yang sengaja mengosongkan seluruh kartunya tetap punya baris
        # (semuanya `is_visible=False`), dan susunan bawaan tidak boleh
        # muncul lagi menimpa keputusannya.
        if not stored:
            return [
                {**catalog[code], "position": index}
                for index, code in enumerate(DEFAULT_CODES)
                if code in catalog and permitted(code)
            ]

        rows = [
            row
            for row in stored
            if row.is_visible and permitted(row.app_code)
        ]

        result = []

        for index, row in enumerate(rows):
            entry = catalog.get(row.app_code, {})

            # Judul dan ikon selalu diambil dari katalog: baris lama yang
            # menyimpan nama modul sebelum diganti tidak boleh membuat
            # kartunya menampilkan nama yang sudah tidak dipakai lagi.
            result.append({
                "app_code": row.app_code,
                "title": entry.get("title") or row.title,
                "description": entry.get("description") or row.description,
                "link": entry.get("link") or row.link,
                "icon": entry.get("icon") or row.icon,
                "color": entry.get("color") or row.color,
                "badge": row.badge,
                "status": entry.get("status") or row.status,
                "position": index,
            })

        # Modul yang **belum pernah ada** waktu pengguna ini menyimpan
        # susunannya menyusul di belakang, dan itu bukan mengabaikan
        # pilihannya.
        #
        # `set_favorites` menulis satu baris untuk **seluruh** katalog —
        # yang tidak dipilih pun dapat baris ber-`is_visible=False`. Jadi
        # "tidak ada barisnya sama sekali" hanya bisa berarti satu hal:
        # modulnya lahir sesudah ia menyimpan, dan ia belum pernah
        # ditanya. Yang sengaja disembunyikan tetap punya barisnya dan
        # tetap tersembunyi.
        #
        # Tanpa ini modul baru tidak pernah sampai ke siapa pun yang
        # pernah menekan Save — dan `seed_dashboard` menekan Save untuk
        # semua orang sekaligus. Persis yang terjadi pada Reports: kartu
        # ada di katalog, statusnya ACTIVE, layarnya jadi, dan beranda
        # tetap tidak memperlihatkannya.
        known = {row.app_code for row in stored}

        for entry in APP_CATALOG:
            code = entry["app_code"]

            if code in known or code not in DEFAULT_CODES:
                continue

            if not permitted(code):
                continue

            result.append({**entry, "position": len(result)})

        return result

    @classmethod
    def get_catalog(cls, user) -> list[dict]:
        """
        Seluruh katalog + penanda pilihan pengguna + **penanda akses**.

        Katalognya tidak lagi disaring hak akses; yang tidak boleh
        dibuka ikut dikirim dengan `is_accessible: False`. Launcher
        beranda menampilkannya kelabu dan tidak bisa ditekan, supaya
        halaman depan memperlihatkan ekosistem ERP yang sebenarnya
        alih-alih dua ikon di kanvas kosong.

        **Ini bukan pelonggaran izin.** Yang dikirim di sini hanya nama
        modul, ikon, dan rutenya — daftar yang sama dengan brosur
        produk. Penjagaannya tetap di tempat yang sama persis seperti
        sebelumnya: `MenuAccessService` untuk menu, `DataScopeService`
        untuk baris data, dan permission DRF di tiap endpoint. Menekan
        URL modul yang kelabu tetap ditolak backend, dan `get_favorites`
        di atas **tetap** menyaring hak akses seperti semula.

        Dua penanda yang sengaja dipisah, karena sebabnya berbeda dan
        kalimat yang dibaca pengguna juga berbeda:

        * `is_accessible` — hak akses pengguna ini (`MenuAccessService`);
        * `is_available` — modulnya sendiri sudah jalan atau belum
          (`FavoriteApp.Status`). `finance` dan `scm` masih kerangka
          kosong, dan itu berlaku untuk semua orang termasuk superuser.

        Menyatukan keduanya membuat "Segera hadir" terbaca sebagai
        "Anda tidak punya izin" — pengguna lalu mengejar admin untuk hak
        akses ke modul yang memang belum ada isinya.
        """
        chosen = [item["app_code"] for item in cls.get_favorites(user)]

        allowed = cls.allowed_codes(user)

        entries = [
            {
                **entry,
                "is_favorite": entry["app_code"] in chosen,
                "is_accessible": allowed is None or entry["app_code"] in allowed,
                "is_available": entry["app_code"] in DEFAULT_CODES,
                # Posisi global, bukan dua deret yang bisa bertabrakan:
                # yang dipilih menempati 0..n-1 sesuai urutan pengguna,
                # sisanya menyusul di belakang. Frontend cukup memakai
                # urutan daftarnya apa adanya.
                "position": (
                    chosen.index(entry["app_code"])
                    if entry["app_code"] in chosen
                    else len(chosen) + entry["position"]
                ),
            }
            for entry in APP_CATALOG
        ]

        return sorted(entries, key=lambda item: item["position"])

    @classmethod
    @transaction.atomic
    def set_favorites(cls, user, codes) -> list[dict]:
        """
        Menyimpan susunan pilihan pengguna; urutan daftar = posisinya.

        Ditulis ulang seluruhnya, bukan ditambal per baris: susunan ini
        satu kesatuan, dan menyimpannya sebagian membuat urutan di layar
        berbeda dari yang tersimpan tanpa ada yang bisa menjelaskannya.
        """
        catalog = by_code()

        wanted = []

        for code in codes or []:
            code = str(code).strip()

            # Kode di luar katalog dilewati, bukan ditolak — katalog bisa
            # menyusut saat modul digabung, dan susunan lama yang masih
            # menyebutnya tidak boleh menggagalkan seluruh penyimpanan.
            if code in catalog and code not in wanted:
                wanted.append(code)

        # Baris ditulis untuk **seluruh** katalog, yang tidak dipilih
        # ditandai `is_visible=False`. Kalau yang tidak dipilih dibuang
        # begitu saja, pengguna yang sengaja mengosongkan semuanya jadi
        # tidak bisa dibedakan dari yang belum pernah menyusun — dan
        # susunan bawaannya akan muncul lagi seolah simpanannya gagal.
        rows = []

        for entry in APP_CATALOG:
            code = entry["app_code"]

            chosen = code in wanted

            rows.append(
                FavoriteApp(
                    user=user,
                    app_code=code,
                    title=entry["title"],
                    description=entry["description"],
                    link=entry["link"],
                    icon=entry["icon"],
                    color=entry["color"],
                    status=entry["status"],
                    is_visible=chosen,
                    position=(
                        wanted.index(code)
                        if chosen
                        else len(wanted) + entry["position"]
                    ),
                )
            )

        # Hard delete, bukan soft: ini preferensi tampilan, tidak ada
        # jejak yang perlu disimpan — dan `uniq_favorite_app_user_code`
        # tidak dikondisikan ke `is_deleted`, jadi baris yang ditandai
        # terhapus justru menghalangi penyimpanan berikutnya.
        FavoriteApp.objects.filter(user=user).delete()

        FavoriteApp.objects.bulk_create(rows)

        return cls.get_favorites(user)

    @classmethod
    def delete_favorite(cls, user, app_code):
        return FavoriteApp.objects.filter(
            user=user,
            app_code=app_code,
        ).delete()
