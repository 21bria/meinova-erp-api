"""
Preferensi bahasa per pengguna — kontraknya, bukan tampilannya.

Yang dijaga di sini ada dua kelompok, dan kelompok kedua yang lebih
penting.

**Yang harus berjalan:** akun bisa memilih bahasanya sendiri lewat
endpoint profilnya, pilihannya bertahan, dan `/auth/me/` mengirimkannya
balik supaya frontend bisa menyetel ulang UI sesudah login.

**Yang harus TIDAK berubah:** nilai yang disimpan tetap kode stabil,
akun lama tetap berbahasa Inggris tanpa ada yang menyentuhnya, bahasa
tidak bisa dipakai sebagai jalan masuk menaikkan wewenang, dan zona
waktu tidak ikut bergerak. Test yang cuma membuktikan kelompok pertama
akan tetap hijau pada implementasi yang diam-diam menerjemahkan data
bisnis — jadi tiap skenario punya pasangan negatifnya.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient


User = get_user_model()

ME_URL = "/api/accounts/auth/me/"


class UserLanguagePreferenceTests(TenantTestCase):
    """Kolom `User.language` dan jalur bacanya."""

    def setUp(self):
        super().setUp()

        self.user = User.objects.create_user(
            username="lang.user",
            email="lang.user@example.com",
            password="rahasia-sekali-123",
            first_name="Lang",
            last_name="User",
        )

        # `HTTP_HOST` wajib, dan tanpanya kegagalannya menyesatkan.
        #
        # `APIClient()` polos mengirim `Host: testserver`, yang tidak
        # cocok dengan domain tenant mana pun — `TenantMainMiddleware`
        # lalu jatuh ke schema `public`, dan `auth_users` tidak ada di
        # sana (accounts ada di TENANT_APPS). Errornya muncul sebagai
        # `relation "auth_users" does not exist`, terbaca seperti
        # migration yang belum jalan padahal cuma host yang salah.
        #
        # Lebih buruk lagi: koneksinya **tetap** di `public` sesudah
        # itu, jadi seluruh test berikutnya ikut gagal di `setUp`.
        self.client = APIClient(
            HTTP_HOST=self.tenant.get_primary_domain().domain,
        )
        self.client.force_authenticate(self.user)

    # ------------------------------------------------------------------
    # Bawaan
    # ------------------------------------------------------------------

    def test_akun_baru_berbahasa_inggris(self):
        """
        Bawaannya `en`, dan itu yang membuat migration ini aman.

        Kalau bawaannya `id`, seluruh akun yang sudah ada akan berganti
        bahasa karena sebuah migration — bukan karena ada yang
        memintanya.
        """
        self.assertEqual(self.user.language, "en")

    def test_akun_lama_tidak_tersentuh(self):
        """
        Baris yang dibuat tanpa menyebut `language` mendapat `en`, bukan
        kosong.

        Ini yang berlaku untuk seluruh baris yang sudah ada di database
        saat migration dijalankan: `AddField` mengisikan default-nya,
        dan tidak ada satu kolom lain pun yang disentuh.
        """
        lama = User.objects.create_user(
            username="akun.lama",
            email="akun.lama@example.com",
            password="rahasia-sekali-123",
        )

        lama.refresh_from_db()

        self.assertEqual(lama.language, "en")

    # ------------------------------------------------------------------
    # Pilihan yang sah
    # ------------------------------------------------------------------

    def test_pilihan_diturunkan_dari_settings(self):
        """
        `choices` kolom = `settings.LANGUAGES`, bukan daftar kedua.

        Dua daftar yang harus sama tapi ditulis terpisah pada akhirnya
        berbeda, dan bedanya muncul sebagai bahasa yang bisa dipilih di
        frontend tapi ditolak backend.
        """
        field = User._meta.get_field("language")

        self.assertEqual(list(field.choices), list(settings.LANGUAGES))

        codes = [code for code, _ in field.choices]

        self.assertIn("en", codes)
        self.assertIn("id", codes)

    def test_ganti_ke_indonesia_lewat_endpoint_profil(self):
        response = self.client.patch(ME_URL, {"language": "id"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["language"], "id")

        self.user.refresh_from_db()

        self.assertEqual(self.user.language, "id")

    def test_me_mengirimkan_bahasa(self):
        """
        `/auth/me/` membawa `language`.

        Tanpa ini frontend tidak punya cara tahu bahasa pilihan akun,
        dan orang yang login di komputer rekannya akan mendapat bahasa
        milik pemilik komputernya.
        """
        self.user.language = "id"
        self.user.save(update_fields=["language"])

        response = self.client.get(ME_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["language"], "id")

    def test_patch_bahasa_saja_tidak_menuntut_kolom_lain(self):
        """
        Pemilih bahasa mengirim satu kolom, dan itu harus cukup.

        Nama dan email tidak boleh ikut kosong sesudahnya — PATCH yang
        parsial yang diam-diam menghapus kolom lain adalah cara paling
        sunyi untuk kehilangan data profil.
        """
        response = self.client.patch(ME_URL, {"language": "id"}, format="json")

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()

        self.assertEqual(self.user.first_name, "Lang")
        self.assertEqual(self.user.last_name, "User")
        self.assertEqual(self.user.email, "lang.user@example.com")

    # ------------------------------------------------------------------
    # Pasangan negatifnya
    # ------------------------------------------------------------------

    def test_bahasa_di_luar_daftar_ditolak(self):
        response = self.client.patch(ME_URL, {"language": "fr"}, format="json")

        self.assertEqual(response.status_code, 400)

        # Error CRUD di sini berbentuk amplop
        # `{success, message, errors, status_code}` — bukan dict field
        # yang datar seperti bawaan DRF. Kesalahannya harus menempel
        # pada **kolomnya**, bukan sekadar 400 di suatu tempat:
        # pesan yang tidak menyebut field tidak menempel di form
        # frontend, dan yang mengisinya tidak tahu apa yang salah.
        self.assertIn("language", response.data["errors"])

        self.user.refresh_from_db()

        self.assertEqual(self.user.language, "en")

    def test_bahasa_bukan_jalan_menaikkan_wewenang(self):
        """
        Jalur tulisnya tetap `ProfileUpdateSerializer`.

        Menambahkan satu kolom ke daftar tulis adalah saat paling
        mungkin daftar itu tanpa sengaja jadi `MeSerializer`. Kalau itu
        terjadi, PATCH ini akan berhasil menjadikan orangnya superuser.
        """
        response = self.client.patch(
            ME_URL,
            {"language": "id", "is_superuser": True, "is_staff": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()

        self.assertEqual(self.user.language, "id")
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)

    def test_bahasa_tidak_menggeser_zona_waktu(self):
        """
        Bahasa dan zona waktu adalah dua hal, dan harus tetap dua hal.

        Menggabungkannya berarti pegawai yang mengganti antarmukanya ke
        Bahasa Indonesia mendapati jam absensinya bergeser tujuh jam.
        """
        sebelum = settings.TIME_ZONE

        self.client.patch(ME_URL, {"language": "id"}, format="json")

        self.assertEqual(settings.TIME_ZONE, sebelum)
        self.assertEqual(settings.TIME_ZONE, "UTC")

    def test_kode_stabil_yang_disimpan_bukan_nama_bahasanya(self):
        """
        Yang tersimpan `id`, bukan "Bahasa Indonesia".

        Nama bahasa boleh berubah kapan saja; kodenya tidak. Menyimpan
        namanya berarti setiap perbaikan ejaan jadi migration data.
        """
        self.user.language = "id"
        self.user.save(update_fields=["language"])

        raw = (
            User.objects
            .filter(pk=self.user.pk)
            .values_list("language", flat=True)
            .first()
        )

        self.assertEqual(raw, "id")
        self.assertNotEqual(raw, "Bahasa Indonesia")
