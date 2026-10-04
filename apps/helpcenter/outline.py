"""
Daftar isi artikel — bagian "ON THIS PAGE".

Diturunkan dari heading di dalam isi artikel, **saat dibaca**, bukan
disimpan sebagai kolom tersendiri. Alasannya: judul heading berubah
tiap kali penulisnya menyunting artikel, dan daftar isi yang disimpan
akan menunjuk judul yang sudah tidak ada tanpa satu pun tanda. Isi
artikelnya kecil (satu-dua layar), jadi mengurainya per permintaan jauh
lebih murah daripada menjaga dua salinan tetap sama.

Id-nya diturunkan dari teks headingnya, bukan dari nomor urut: `#1`
berubah artinya begitu ada satu heading disisipkan di atasnya, dan
tautan yang dibagikan orang ke rekannya mendarat di bagian yang salah.
"""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser

from django.utils.text import slugify


HEADING_TAGS = ("h2", "h3", "h4")


class _Outliner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.parts: list[str] = []
        self.toc: list[dict] = []

        self._heading: str | None = None
        self._text: list[str] = []
        self._used: set[str] = set()

    # Isi yang masuk ke sini **sudah** lewat `sanitize_html()`, jadi
    # tugasnya cuma menyalin ulang apa adanya sambil menyisipkan id.
    def handle_starttag(self, tag, attrs):
        if tag in HEADING_TAGS:
            self._heading = tag
            self._text = []
            return

        self.parts.append(self._render(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self._render(tag, attrs, self_closing=True))

    def handle_endtag(self, tag):
        if tag in HEADING_TAGS and self._heading == tag:
            text = "".join(self._text).strip()
            anchor = self._anchor(text)

            self.toc.append({
                "id": anchor,
                "text": text,
                # h2 = 1, h3 = 2, … supaya sisi tampilan cukup
                # membaca angka dan tidak perlu tahu soal tag HTML.
                "level": HEADING_TAGS.index(tag) + 1,
            })

            self.parts.append(
                f'<{tag} id="{escape(anchor, quote=True)}">'
                f"{escape(text, quote=False)}</{tag}>"
            )

            self._heading = None
            self._text = []
            return

        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._heading:
            self._text.append(data)
            return

        self.parts.append(escape(data, quote=False))

    def _anchor(self, text: str) -> str:
        base = slugify(text)[:60] or "bagian"

        # Dua heading berjudul sama di satu artikel bukan hal aneh
        # ("Langkah", "Catatan"), dan id kembar membuat tautan selalu
        # mendarat di yang pertama.
        anchor = base
        suffix = 2

        while anchor in self._used:
            anchor = f"{base}-{suffix}"
            suffix += 1

        self._used.add(anchor)

        return anchor

    @staticmethod
    def _render(tag: str, attrs, *, self_closing: bool = False) -> str:
        rendered = "".join(
            f' {name}="{escape(value, quote=True)}"'
            for name, value in attrs
            if value is not None
        )

        return f"<{tag}{rendered}{' /' if self_closing else ''}>"


def build_outline(content: str | None) -> tuple[str, list[dict]]:
    """
    Mengembalikan `(isi dengan id pada heading, daftar isi)`.

    Isi yang dioper **wajib** sudah dibersihkan `sanitize_html()` —
    fungsi ini menyalin atribut apa adanya dan tidak memeriksa apa pun.
    """

    if not content:
        return "", []

    parser = _Outliner()
    parser.feed(content)
    parser.close()

    return "".join(parser.parts), parser.toc
