"""
Perenderan template notifikasi.

Isi template datang dari **database yang disunting admin tenant**, dan
itu yang menentukan seluruh bentuk berkas ini. Merendernya dengan engine
Django apa adanya berarti seorang admin tenant bisa menulis
`{% include "/etc/passwd" %}` atau memuat template tag apa pun yang
terpasang — di aplikasi multi-tenant, itu satu tenant membaca berkas
server yang melayani seluruh tenant lain.

Tiga lapis yang menutupnya, dan ketiganya harus tetap ada:

1. **Engine terbatas.** `django.template.loader_tags` dibuang, jadi
   `{% include %}` dan `{% extends %}` bukan tag yang dikenal — bukan
   dilarang, memang tidak ada. `libraries={}` membuat `{% load %}` gagal
   karena tidak ada satu pustaka pun yang bisa dimuat. Yang tersisa:
   `{% if %}`, `{% for %}`, dan filter bawaan seperti `|date` dan
   `|default` — cukup untuk menulis surat, tidak cukup untuk membaca
   berkas.

   Membuangnya **wajib lewat subclass**, bukan lewat parameter
   `builtins=`: parameter itu bersifat aditif (`self.builtins =
   self.default_builtins + builtins`), jadi menyebutkan daftar pendek di
   sana tidak menghapus apa pun. Sudah kena sekali — `{% include %}`
   tetap tag yang dikenal dan hanya gagal karena daftar loader kebetulan
   kosong. Menggantungkan penjagaannya pada daftar loader berarti
   siapa pun yang kelak mengisinya membuka kembali pembacaan berkas
   server, tanpa satu pun tanda bahwa itu yang terjadi.

2. **Konteks selalu datar.** Nilai yang masuk hanya primitif (str, int,
   date, Decimal) — tidak pernah instance model. Ini yang menutup
   penelusuran atribut: tanpa objek di konteks, `{{ x.employee.user }}`
   tidak menunjuk apa pun. Pembangun konteks tiap event yang menjaganya,
   dan `flatten()` di bawah yang menegakkannya.

3. **Autoescape menyala.** Nama pegawai yang memuat `&` atau `<` tidak
   merusak HTML-nya, dan nilai dari database tidak bisa menyuntikkan
   markup ke email yang dibaca orang lain.

Kegagalan render **tidak boleh menjatuhkan pengiriman**: template yang
salah ketik satu tanda kurung akan membuat seluruh pemberitahuan hilang,
dan itu jauh lebih merugikan daripada satu email yang kalimatnya
janggal. `safe_render` mengembalikan sumber apa adanya beserta pesannya.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from django.template import Context, Engine, TemplateSyntaxError
from django.utils.html import escape

logger = logging.getLogger(__name__)


class SandboxedEngine(Engine):
    """
    Engine tanpa tag pemuat template.

    `default_builtins` ditimpa, bukan ditambah — lihat lapis (1) di
    docstring modul. Ini satu-satunya cara membuat `{% include %}` dan
    `{% extends %}` benar-benar tidak ada.
    """

    default_builtins = [
        "django.template.defaulttags",
        "django.template.defaultfilters",
    ]


# Dibangun sekali di tingkat modul: `Engine` mengompilasi daftar tag
# saat dibuat, dan membangunnya ulang tiap render membuat pengiriman
# massal menghabiskan waktu di tempat yang tidak ada hubungannya dengan
# email.
_ENGINE = SandboxedEngine(
    dirs=[],
    loaders=[],
    libraries={},
    autoescape=True,
    string_if_invalid="",
)


# `{{ nama }}`, `{{ nama|filter }}`, `{{ nama.atribut }}`.
#
# Hanya untuk **melaporkan** kunci yang tidak dikenal di layar penyunting
# — bukan untuk menyaring apa pun. Penjagaannya ada di engine dan di
# bentuk konteksnya, bukan di regex ini.
_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w]*)")


class RenderError(Exception):
    """Template tidak bisa dikompilasi."""


def variables_used(source: str) -> set[str]:
    """Kunci yang disebut sebuah template."""
    return set(_VARIABLE_RE.findall(str(source or "")))


def flatten(context: Mapping[str, Any]) -> dict[str, Any]:
    """
    Memaksa konteks jadi datar — lapis (2).

    Nilai yang bukan primitif diubah jadi teks, **bukan** diteruskan apa
    adanya. Itu yang membuat instance model yang telanjur diselipkan
    seseorang tidak pernah bisa ditelusuri dari dalam template: yang
    sampai ke sana tinggal hasil `str()`-nya.

    `None` jadi string kosong, bukan "None" — kolom yang belum diisi
    harus terbaca sebagai kosong di surat, bukan sebagai kata "None"
    yang membuat penerimanya mengira sistemnya rusak.
    """
    flat: dict[str, Any] = {}

    for key, value in dict(context or {}).items():
        name = str(key)

        if value is None:
            flat[name] = ""
        elif isinstance(value, (str, int, float, Decimal, bool)):
            flat[name] = value
        elif isinstance(value, (date, datetime)):
            flat[name] = value
        else:
            flat[name] = str(value)

    return flat


def render(source: str, context: Mapping[str, Any]) -> str:
    """
    Merender satu template. Melempar `RenderError` kalau sumbernya
    tidak bisa dikompilasi.

    Dipakai layar pratinjau, yang memang harus memperlihatkan
    kesalahannya. Jalur pengiriman memakai `safe_render`.
    """
    try:
        template = _ENGINE.from_string(str(source or ""))
    except TemplateSyntaxError as exc:
        raise RenderError(str(exc)) from exc

    try:
        return template.render(Context(flatten(context), autoescape=True))
    except Exception as exc:  # noqa: BLE001 - lihat docstring modul
        raise RenderError(str(exc)) from exc


def safe_render(
    source: str,
    context: Mapping[str, Any],
    *,
    label: str = "",
) -> tuple[str, str]:
    """
    Merender tanpa pernah melempar.

    Mengembalikan `(hasil, pesan_kesalahan)`. Kalau gagal, hasilnya
    adalah sumber apa adanya — surat yang masih memuat `{{ nama }}`
    memang janggal, tapi ia sampai, terbaca, dan langsung memberi tahu
    orang yang menyuntingnya bahwa ada yang salah. Yang tidak terkirim
    tidak memberi tahu siapa pun apa pun.
    """
    try:
        return render(source, context), ""
    except RenderError as exc:
        logger.warning(
            "Template notifikasi %s gagal dirender: %s",
            label or "(tanpa nama)",
            exc,
        )

        return str(source or ""), str(exc)


def to_html(text: str) -> str:
    """
    Teks biasa → HTML sederhana.

    Isi template ditulis sebagai teks di kotak biasa, bukan editor kaya
    — surat pemberitahuan isinya beberapa paragraf, dan toolbar penuh
    tombol format cuma mengundang orang membuat email yang tidak terbaca
    di klien email lama. Yang perlu dijaga cuma barisnya: baris kosong
    jadi paragraf baru, pindah baris tunggal jadi `<br>`.

    Di-escape lebih dulu. Isi ini sudah lewat `render()` yang
    autoescape-nya menyala, tapi **teks di luar placeholder tidak
    tersentuh escape itu** — dan tanda `<` yang diketik orang di dalam
    kalimatnya sendiri akan memakan sisa paragraf.
    """
    escaped = escape(str(text or "").strip())

    paragraphs = [
        block.strip().replace("\n", "<br>")
        for block in re.split(r"\n\s*\n", escaped)
        if block.strip()
    ]

    return "\n".join(f"<p>{block}</p>" for block in paragraphs)
