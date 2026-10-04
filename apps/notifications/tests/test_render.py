"""
Sandbox perenderan template.

`SimpleTestCase` — **tidak menyentuh database sama sekali**, dan itu
properti yang harus tetap dijaga: perenderan template memang fungsi
murni, dan begitu ada yang menambahkan query ke dalamnya berkas ini yang
pertama gagal.

Isi template datang dari database yang disunting admin tenant, jadi yang
diuji di sini bukan kenyamanan melainkan batas: apa yang **tidak** boleh
bisa dilakukan seorang admin tenant lewat kotak isian surat.
"""

from datetime import date

from django.test import SimpleTestCase

from apps.notifications.render import (
    RenderError,
    render,
    safe_render,
    to_html,
    variables_used,
)


class TemplateSandboxTests(SimpleTestCase):
    # ------------------------------------------------------------------
    # Yang harus bisa
    # ------------------------------------------------------------------

    def test_placeholder_diisi(self):
        self.assertEqual(
            render("Halo {{ nama }}", {"nama": "Budi"}),
            "Halo Budi",
        )

    def test_percabangan_dan_perulangan(self):
        self.assertEqual(
            render("{% if n %}ada{% else %}kosong{% endif %}", {"n": 3}),
            "ada",
        )

        self.assertEqual(
            render("{% for x in s %}{{ x }}{% endfor %}", {"s": "ab"}),
            "ab",
        )

    def test_filter_bawaan(self):
        self.assertEqual(
            render("{{ d|date:'d M Y' }}", {"d": date(2026, 8, 15)}),
            "15 Aug 2026",
        )

        self.assertEqual(render("{{ x|default:'-' }}", {"x": ""}), "-")

    # ------------------------------------------------------------------
    # Yang tidak boleh bisa
    # ------------------------------------------------------------------

    def test_include_bukan_tag_yang_dikenal(self):
        """
        `{% include %}` harus **tidak ada**, bukan sekadar gagal mencari
        berkasnya.

        Sudah pernah salah sekali: `builtins=` pada `Engine` bersifat
        aditif, jadi menyebutkan daftar pendek di sana tidak menghapus
        `loader_tags`. Waktu itu `{% include %}` tetap tag yang dikenal
        dan hanya gagal karena daftar loader kebetulan kosong —
        penjagaan yang hilang begitu ada yang mengisi daftar itu.
        """
        with self.assertRaises(RenderError) as ctx:
            render('{% include "email/base.html" %}', {})

        self.assertIn("Invalid block tag", str(ctx.exception))

    def test_extends_bukan_tag_yang_dikenal(self):
        with self.assertRaises(RenderError) as ctx:
            render('{% extends "base.html" %}', {})

        self.assertIn("Invalid block tag", str(ctx.exception))

    def test_load_ditolak(self):
        with self.assertRaises(RenderError):
            render("{% load static %}{{ x }}", {})

    def test_nilai_di_escape(self):
        self.assertEqual(
            render("{{ x }}", {"x": "<script>alert(1)</script>"}),
            "&lt;script&gt;alert(1)&lt;/script&gt;",
        )

    def test_objek_tidak_bisa_ditelusuri(self):
        """
        Konteks selalu datar — objek yang telanjur diselipkan pemanggil
        diubah jadi teks, jadi atributnya tidak bisa dijangkau dari
        dalam template.
        """

        class Rahasia:
            token = "JANGAN-BOCOR"

            def __str__(self):
                return "objek"

        self.assertEqual(render("{{ o.token }}", {"o": Rahasia()}), "")
        self.assertEqual(render("{{ o }}", {"o": Rahasia()}), "objek")

    def test_none_jadi_kosong_bukan_kata_None(self):
        self.assertEqual(render("[{{ x }}]", {"x": None}), "[]")


class SafeRenderTests(SimpleTestCase):
    def test_template_rusak_tidak_melempar(self):
        """
        Template yang salah ketik tidak boleh membuang seluruh
        pemberitahuan — surat yang janggal tetap sampai dan langsung
        memberi tahu penyuntingnya ada yang salah.
        """
        hasil, pesan = safe_render("{% if %}", {})

        self.assertEqual(hasil, "{% if %}")
        self.assertTrue(pesan)

    def test_template_benar_tanpa_pesan(self):
        hasil, pesan = safe_render("Halo {{ n }}", {"n": "Budi"})

        self.assertEqual(hasil, "Halo Budi")
        self.assertEqual(pesan, "")


class HelperTests(SimpleTestCase):
    def test_variables_used(self):
        self.assertEqual(
            variables_used("{{ a }} {{ b|upper }} {{ c.d }}"),
            {"a", "b", "c"},
        )

    def test_to_html_memisahkan_paragraf(self):
        hasil = to_html("Baris satu\nbaris dua\n\nParagraf dua")

        self.assertEqual(
            hasil,
            "<p>Baris satu<br>baris dua</p>\n<p>Paragraf dua</p>",
        )

    def test_to_html_meng_escape_isi(self):
        """
        Teks di luar placeholder tidak tersentuh autoescape milik
        engine, jadi tanda `<` yang diketik orang di dalam kalimatnya
        sendiri akan memakan sisa paragraf kalau tidak di-escape di
        sini.
        """
        self.assertIn("&lt;b&gt;", to_html("Ini <b>tebal</b>"))
