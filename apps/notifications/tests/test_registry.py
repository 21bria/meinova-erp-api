"""
Registry event.

`SimpleTestCase` — tanpa database. Registry memang cuma dict di memori,
dan itu yang membuatnya bisa diperiksa tanpa menyiapkan tenant.
"""

from django.test import SimpleTestCase

from apps.notifications.constants import Channel, RecipientType
from apps.notifications.registry import (
    COMMON_PLACEHOLDERS,
    UnknownEvent,
    all_events,
    find_event,
    get_event,
    unknown_placeholders,
)
from apps.notifications.render import variables_used


class RegistryTests(SimpleTestCase):
    def test_event_tak_dikenal_melempar(self):
        """
        Melempar, bukan mengembalikan None. Nama event yang salah ketik
        membuat pemberitahuan tidak pernah terkirim — dan itu jenis
        kegagalan yang tidak ada yang melaporkannya, karena orang tidak
        mengeluhkan email yang tidak mereka tahu seharusnya ada.
        """
        with self.assertRaises(UnknownEvent):
            get_event("hr.tidak_pernah_ada")

    def test_pesan_menyebut_yang_tersedia(self):
        try:
            get_event("hr.salah_ketik")
        except UnknownEvent as exc:
            self.assertIn("hr.contract_end", str(exc))

    def test_find_event_mengembalikan_none(self):
        self.assertIsNone(find_event("hr.tidak_ada"))

    def test_placeholder_umum_selalu_ikut(self):
        event = get_event("hr.contract_end")
        keys = event.placeholder_keys()

        for common in COMMON_PLACEHOLDERS:
            self.assertIn(common.key, keys)

    def test_unknown_placeholders(self):
        self.assertEqual(
            unknown_placeholders("hr.contract_end", ["employee_name", "ngawur"]),
            ["ngawur"],
        )


class DefaultTemplateTests(SimpleTestCase):
    """
    Kalimat bawaan tiap event.

    Ini yang terkirim ke tenant yang belum pernah menyunting apa pun,
    jadi placeholder yang salah ketik di sini menghasilkan surat
    berlubang untuk semua orang sekaligus.
    """

    def test_semua_event_punya_judul_dan_isi(self):
        for event in all_events():
            with self.subTest(event=event.code):
                self.assertTrue(
                    event.default_subject.strip(),
                    f"{event.code} tidak punya judul bawaan.",
                )
                self.assertTrue(
                    event.default_body.strip(),
                    f"{event.code} tidak punya isi bawaan.",
                )

    def test_placeholder_bawaan_semuanya_dikenal(self):
        """
        Kunci yang dipakai kalimat bawaan wajib terdaftar sebagai
        placeholder event itu. Yang tidak terdaftar dirender jadi string
        kosong — surat yang berbunyi "Kontrak  berakhir " dan tidak ada
        satu pun pesan yang menyebutkannya.
        """
        for event in all_events():
            used = (
                variables_used(event.default_subject)
                | variables_used(event.default_body)
            )

            unknown = sorted(used - event.placeholder_keys())

            with self.subTest(event=event.code):
                self.assertEqual(
                    unknown,
                    [],
                    f"{event.code} memakai kunci tak terdaftar: {unknown}",
                )

    def test_kanal_dan_penerima_bawaan_sah(self):
        valid_channels = set(Channel.values)
        valid_recipients = set(RecipientType.values)

        for event in all_events():
            with self.subTest(event=event.code):
                self.assertTrue(
                    set(event.default_channels) <= valid_channels,
                    f"{event.code} menyebut kanal yang tidak ada.",
                )
                self.assertTrue(
                    set(event.default_recipients) <= valid_recipients,
                    f"{event.code} menyebut tipe penerima yang tidak ada.",
                )

    def test_penerima_role_menyebut_rolenya(self):
        """
        Event yang bawaannya mengirim ke pemegang role wajib menyebut
        kode role-nya. Kalau tidak, `_default_rules` menghasilkan nol
        aturan dan event itu tidak pernah sampai ke siapa pun — tanpa
        satu pun pesan.
        """
        for event in all_events():
            if RecipientType.ROLE not in event.default_recipients:
                continue

            with self.subTest(event=event.code):
                self.assertTrue(
                    event.default_roles,
                    f"{event.code} berpenerima role tapi tidak menyebut "
                    "satu kode role pun.",
                )
