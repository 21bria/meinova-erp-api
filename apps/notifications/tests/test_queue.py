"""
Antrean email tidak boleh menjatuhkan pemanggilnya.

Sifat pertama modul dispatcher — "tidak pernah menjatuhkan pemanggilnya"
— dijaga savepoint di dalam `notify()`. Callback `on_commit` jalan **di
luar** savepoint itu, sesudah transaksinya commit, jadi ia satu-satunya
titik yang savepoint tidak bisa lindungi.

Ketahuan lewat UAT persetujuan terakhir Roster Setup: broker mati →
`.delay()` melempar dari dalam callback → response 500, padahal
dokumennya sudah `committed` lengkap dengan roster dan baseline shift.
Approver membaca "Keputusan gagal disimpan" untuk sesuatu yang tersimpan
seluruhnya, lalu mengulanginya.

`SimpleTestCase` — yang diuji perilaku satu fungsi terhadap broker yang
melempar, dan itu tidak butuh tenant maupun satu baris data pun.
`databases` tetap harus disebut: `transaction.on_commit` menanyakan
status autocommit ke koneksi, dan tanpa izin itu Django menolaknya
sebelum callback-nya sempat jalan. Di luar blok atomic callback-nya
jalan **seketika**, jadi kegagalannya muncul di pemanggil persis seperti
di produksi.
"""

from unittest import mock

from django.test import SimpleTestCase

from apps.notifications import dispatcher


class QueueEmailsTests(SimpleTestCase):
    databases = {"default"}

    def test_broker_yang_mati_tidak_menjatuhkan_pemanggilnya(self):
        """
        Yang dijaga bukan email terkirim — yang dijaga tindakan
        penggunanya tidak ikut dilaporkan gagal.
        """
        boom = mock.Mock(side_effect=RuntimeError("Connection refused"))

        with mock.patch(
            "apps.notifications.tasks.send_email_notification.delay",
            boom,
        ):
            # Tidak dibungkus assertRaises: **tidak melempar** itulah
            # seluruh isi test ini.
            dispatcher._queue([101, 102, 103])

        self.assertEqual(
            boom.call_count,
            3,
            "Satu id yang gagal diantre tidak boleh menghentikan "
            "sisanya — ditangkap per baris, bukan sekali untuk seluruh "
            "daftar.",
        )

    def test_broker_sehat_tetap_mengantre_semuanya(self):
        ok = mock.Mock()

        with mock.patch(
            "apps.notifications.tasks.send_email_notification.delay",
            ok,
        ):
            dispatcher._queue([7, 8])

        self.assertEqual(ok.call_count, 2)

        # Schema ikut dioper: worker tidak mewarisi schema dari
        # pemanggilnya, dan tanpa itu task-nya jalan di public schema
        # lalu tidak menemukan satu baris log pun.
        for call in ok.call_args_list:
            self.assertEqual(len(call.args), 2)
            self.assertIsInstance(call.args[0], str)
