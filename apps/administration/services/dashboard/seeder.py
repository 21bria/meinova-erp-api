from .seed_widgets import seed_widgets
from .seed_apps import seed_favorite_apps


class DashboardSeeder:
    """
    Dua fungsi sudah **dihapus**, bukan dipindah.

    `seed_default_layout` menulis satu baris `UserDashboardLayout` untuk
    **setiap pengguna × setiap widget**, dan `seed_favorite_menus`
    melakukan hal yang sama persis untuk lima pintasan bawaan. Dua
    kesalahan sekaligus: pengguna yang dibuat setelah seed dijalankan
    tidak dapat susunan apa pun sampai ada yang menjalankannya lagi, dan
    yang dapat baris bawaan berhenti mengikuti bawaan yang berubah besok.

    Susunan bawaan sekarang diturunkan dari katalog **saat dibaca** dan
    tidak pernah ditulis — pembeda "belum pernah menyusun" adalah tidak
    adanya baris. Pelajaran yang sama persis dengan
    `FavoriteApp.DEFAULT_CODES`.

    Pintasan bawaannya kini `DEFAULT_CODES` di
    `apps/administration/api/dashboard/menu_catalog.py`, dan katalog
    pilihannya tabel `Menu` — bukan lagi daftar tersendiri di berkas seed.
    """

    @staticmethod
    def seed_widgets():
        return seed_widgets()

    @staticmethod
    def seed_favorite_apps():
        return seed_favorite_apps()
