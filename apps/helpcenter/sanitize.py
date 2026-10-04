"""
Pembersih HTML untuk isi artikel panduan.

Artikel ditulis satu orang dan dibaca **semua** pengguna tenant, jadi
HTML mentah dari editor adalah stored XSS begitu ada satu penulis yang
akunnya diambil alih — dan halaman yang paling mungkin dibuka semua
orang justru halaman bantuan. Pembersihannya dilakukan **saat
menyimpan**, bukan saat menampilkan: yang tersimpan di database harus
sudah aman, kalau tidak setiap pembaca baru (API, ekspor, PDF) harus
ingat membersihkannya lagi.

Ditulis tangan memakai `HTMLParser` bawaan, tanpa `bleach`/`nh3` —
menambah dependensi untuk satu fungsi ini tidak sepadan, dan daftar
tag yang boleh lewat di sini memang sengaja pendek: apa yang bisa
dihasilkan toolbar editor, tidak lebih.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from django.conf import settings


ALLOWED_TAGS: dict[str, set[str]] = {
    "p": set(),
    "br": set(),
    "strong": set(),
    "b": set(),
    "em": set(),
    "i": set(),
    "u": set(),
    "s": set(),
    "mark": set(),
    "code": set(),
    "pre": set(),
    "blockquote": set(),
    "h1": set(),
    "h2": set(),
    "h3": set(),
    "h4": set(),
    "ul": set(),
    "ol": {"start"},
    "li": set(),
    "hr": set(),
    "table": set(),
    "thead": set(),
    "tbody": set(),
    "tr": set(),
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height"},
    "span": {"style"},

    # Satu-satunya elemen sematan yang diizinkan, dan **hanya** kalau
    # `src`-nya lolos `youtube_embed_url()`. Bukan whitelist nama host:
    # yang diperiksa bentuk URL-nya sampai ke id videonya, karena
    # "mengandung youtube.com" gampang dipalsukan lewat subdomain atau
    # parameter. Selebihnya lihat catatan di `_Sanitizer`.
    "iframe": {
        "src",
        "title",
        "width",
        "height",
        "allow",
        "allowfullscreen",
        "frameborder",
    },
}

VOID_TAGS = {"br", "hr", "img"}

# Tag yang **isinya ikut dibuang**, bukan cuma tag-nya. Menghapus
# `<script>` tapi membiarkan teks di dalamnya menghasilkan artikel yang
# tiba-tiba memuat baris `alert(1)` di tengah paragraf — aman, tapi
# terbaca seperti isi artikel yang rusak.
#
# `iframe` **tidak** di sini lagi: ia diperiksa satu per satu di
# `handle_starttag`, dan yang gagal diperlakukan sama seperti daftar
# ini (isinya ikut dibuang).
DROP_CONTENT_TAGS = {"script", "style", "object", "embed", "template"}

# Skema yang boleh muncul di `href`/`src`. `javascript:` jelas tidak;
# `data:` juga tidak — data URI bisa membawa SVG berisi script.
SAFE_URL_PREFIXES = ("http://", "https://", "mailto:", "/", "#")

# Whitelist properti CSS. `style` dibiarkan hidup karena editor
# memakainya untuk warna teks dan highlight, tapi properti bebas
# membuka `expression()` dan `url(javascript:...)` di browser lama.
ALLOWED_CSS_PROPERTIES = {"color", "background-color", "text-align"}


# Id video YouTube: 11 karakter base64url. Dipakai sebagai satu-satunya
# hal yang benar-benar diambil dari URL kiriman — sisanya dibuang dan
# URL sematannya **dibangun ulang**, bukan diteruskan apa adanya.
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def youtube_embed_url(value: str | None) -> str | None:
    """
    Mengubah bentuk URL YouTube apa pun jadi URL sematan yang aman,
    atau `None` kalau bukan YouTube.

    **URL-nya dibangun ulang dari nol**, hanya membawa id video dan
    (kalau ada) detik mulainya. Meneruskan URL kiriman apa adanya
    berarti parameter yang tidak pernah diperiksa ikut masuk ke atribut
    `src` sebuah iframe di halaman yang dibaca seluruh tenant — dan
    daftar parameter YouTube bukan sesuatu yang bisa dijaga tetap
    lengkap di sini.

    Memakai domain `youtube-nocookie.com`: pemutarnya sama, tapi tidak
    menanam cookie pelacak sampai videonya benar-benar diputar.
    """

    if not value:
        return None

    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    if (parsed.hostname or "").lower() not in YOUTUBE_HOSTS:
        return None

    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    params = parse_qs(parsed.query or "")

    video_id: str | None = None

    if host.endswith("youtu.be"):
        video_id = path.strip("/").split("/")[0]
    elif path.startswith("/embed/"):
        video_id = path[len("/embed/"):].split("/")[0]
    elif path.startswith("/shorts/"):
        video_id = path[len("/shorts/"):].split("/")[0]
    elif path == "/watch":
        video_id = (params.get("v") or [None])[0]

    if not video_id or not YOUTUBE_ID.match(video_id):
        return None

    start = _start_seconds(params)

    url = f"https://www.youtube-nocookie.com/embed/{video_id}"

    return f"{url}?start={start}" if start else url


def _start_seconds(params: dict[str, list[str]]) -> int | None:
    """
    Detik mulai dari `?t=` atau `?start=`.

    Berguna untuk tutorial: satu video panjang bisa ditunjuk beberapa
    kali dari langkah yang berbeda. `t` bisa berbentuk `90` atau `1m30s`.
    """

    raw = (params.get("start") or params.get("t") or [""])[0]

    if not raw:
        return None

    if raw.isdigit():
        return int(raw)

    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw.strip())

    if not match or not any(match.groups()):
        return None

    hours, minutes, seconds = (int(g or 0) for g in match.groups())

    return hours * 3600 + minutes * 60 + seconds


def _safe_url(value: str) -> bool:
    candidate = value.strip().lower()

    if not candidate:
        return False

    # Menolak karakter kendali yang lazim dipakai menyelundupkan
    # `java\nscript:` melewati pemeriksaan awalan.
    if any(ord(char) < 32 for char in candidate):
        return False

    return candidate.startswith(SAFE_URL_PREFIXES)


def normalize_image_src(value: str | None) -> str | None:
    """
    Menyimpan sumber gambar sebagai **jalur relatif di bawah MEDIA_URL**,
    atau `None` kalau bukan berkas media milik sistem ini.

    Dua alasan membatasinya:

    1. Gambar dari domain luar berarti setiap pembaca panduan menembak
       server orang lain — siapa membaca artikel apa jadi terbaca di
       sana, dan host yang mati menggantungkan halaman bantuan tepat
       saat penggunanya sedang kesulitan.
    2. **URL absolut membuat artikel tidak bisa berpindah lingkungan.**
       Gambar yang diunggah di `demo.localhost:8000` akan tersimpan
       lengkap dengan host itu, dan di produksi seluruhnya rusak.

    Tapi URL absolut ke media sendiri **diterima lalu diperkecil**
    jadi relatif, bukan ditolak — dan itu bukan kelonggaran, itu
    syarat. Isi artikel dikirim ke editor dalam bentuk absolut (kalau
    tidak, gambarnya tidak muncul: frontend beda origin dari backend),
    jadi bentuk itulah yang dikirim balik saat disimpan. Menolaknya
    berarti **membuka artikel bergambar lalu menekan Save menghapus
    seluruh gambarnya**, tanpa satu pun pesan.

    Kalau nanti media pindah ke CDN/S3, di sinilah host-nya
    didaftarkan — satu tempat, bukan tersebar di tiap pemanggil.
    """

    candidate = (value or "").strip()

    if not candidate or any(ord(char) < 32 for char in candidate):
        return None

    media_url = getattr(settings, "MEDIA_URL", "/media/") or "/media/"

    # `//host/x` adalah URL protokol-relatif — tetap keluar server ini.
    if candidate.startswith("//"):
        return None

    if candidate.startswith("/"):
        return candidate if candidate.startswith(media_url) else None

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    # Host-nya sengaja **tidak** diperiksa: yang menentukan berkasnya
    # milik sistem ini adalah jalurnya, dan host backend berbeda-beda
    # per tenant (subdomain) dan per lingkungan. Yang tersimpan tetap
    # jalur relatifnya, jadi host apa pun yang dikirim tidak pernah
    # ikut masuk ke isi artikel.
    if not parsed.path.startswith(media_url):
        return None

    return parsed.path


def _safe_style(value: str) -> str:
    kept = []

    for declaration in value.split(";"):
        if ":" not in declaration:
            continue

        prop, _, val = declaration.partition(":")
        prop = prop.strip().lower()
        val = val.strip()

        if prop not in ALLOWED_CSS_PROPERTIES:
            continue

        if "(" in val or "@" in val:
            continue

        kept.append(f"{prop}: {val}")

    return "; ".join(kept)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_tags: list[str] = []

        # Tumpukan elemen yang sedang dibuang **beserta isinya**.
        # Bukan penghitung: `iframe` yang ditolak juga masuk ke sini,
        # dan dengan penghitung, `</iframe>` di dalam sebuah `<script>`
        # akan mengakhiri pembuangan satu tingkat terlalu awal.
        self.drop_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.drop_stack:
            # Tag sejenis yang bersarang tetap dicatat supaya
            # penutupnya tidak mengakhiri pembuangan lebih awal.
            if tag in DROP_CONTENT_TAGS:
                self.drop_stack.append(tag)

            return

        if tag in DROP_CONTENT_TAGS:
            self.drop_stack.append(tag)
            return

        if tag not in ALLOWED_TAGS:
            return

        # `iframe` satu-satunya elemen yang boleh disematkan, dan hanya
        # kalau `src`-nya benar-benar sebuah video YouTube. Yang gagal
        # dibuang **beserta isinya** — isi sebuah iframe adalah teks
        # cadangan yang tidak pernah tampil, jadi meloloskannya sebagai
        # teks biasa cuma menyisipkan kalimat asing ke tengah artikel.
        if tag == "iframe":
            src = youtube_embed_url(dict(attrs).get("src"))

            if not src:
                self.drop_stack.append(tag)
                return

            self.open_tags.append(tag)
            self.parts.append(
                f'<iframe src="{escape(src, quote=True)}"'
                ' loading="lazy"'
                ' frameborder="0"'
                ' allowfullscreen="true"'
                ' allow="accelerometer; clipboard-write; encrypted-media;'
                ' gyroscope; picture-in-picture">'
            )
            return

        rendered = []
        kept: set[str] = set()

        for name, value in attrs:
            if value is None:
                continue

            if name not in ALLOWED_TAGS[tag]:
                continue

            if name == "src" and tag == "img":
                normalized = normalize_image_src(value)

                if not normalized:
                    continue

                # Yang tersimpan **selalu** jalur relatif, apa pun
                # bentuk yang dikirim. Lihat `normalize_image_src`.
                value = normalized

            elif name in {"href", "src"} and not _safe_url(value):
                continue

            if name == "style":
                value = _safe_style(value)

                if not value:
                    continue

            rendered.append(f' {name}="{escape(value, quote=True)}"')
            kept.add(name)

        # Gambar yang `src`-nya ditolak dibuang seluruhnya. Kalau
        # tag-nya tetap ditulis, pembaca melihat ikon gambar rusak dan
        # menyangka artikelnya gagal dimuat.
        if tag == "img" and "src" not in kept:
            return

        attr_text = "".join(rendered)

        # Artikel bergambar per langkah lazimnya memuat sepuluh
        # tangkapan layar. Tanpa `lazy`, sepuluh berkas itu ditarik
        # sekaligus saat halaman dibuka — dan pembaca di site dengan
        # koneksi satelit menunggu seluruhnya hanya untuk membaca
        # langkah pertama.
        if tag == "img":
            attr_text += ' loading="lazy"'

        # Tautan keluar selalu dibuka di tab baru tanpa membocorkan
        # `window.opener` ke halaman tujuan.
        if tag == "a":
            attr_text += ' rel="noopener noreferrer"'

        if tag in VOID_TAGS:
            self.parts.append(f"<{tag}{attr_text} />")
            return

        self.open_tags.append(tag)
        self.parts.append(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag):
        if self.drop_stack:
            if self.drop_stack[-1] == tag:
                self.drop_stack.pop()

            return

        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return

        if tag not in self.open_tags:
            return

        # Menutup tag yang sempat dibiarkan menganga di antaranya,
        # supaya keluarannya tetap berimbang walau masukannya tidak.
        while self.open_tags:
            open_tag = self.open_tags.pop()
            self.parts.append(f"</{open_tag}>")

            if open_tag == tag:
                break

    def handle_data(self, data):
        if self.drop_stack:
            return

        self.parts.append(escape(data, quote=False))

    def close_all(self) -> None:
        while self.open_tags:
            self.parts.append(f"</{self.open_tags.pop()}>")

    def result(self) -> str:
        return "".join(self.parts)


def sanitize_html(value: str | None) -> str:
    if not value:
        return ""

    parser = _Sanitizer()
    parser.feed(value)
    parser.close()
    parser.close_all()

    return parser.result()


def absolutize_media(value: str | None, base_url: str | None) -> str:
    """
    Menjadikan `src` gambar absolut terhadap host backend, untuk
    dikirim ke klien.

    **Wajib**, dan bukan kenyamanan: frontend berjalan di origin yang
    berbeda dari backend (`localhost:3000` vs `demo.localhost:8000`),
    jadi `/media/x.png` di halaman Nuxt diselesaikan terhadap Nuxt dan
    berakhir 404 — gambarnya tampil sebagai ikon pecah, dan penulis
    artikelnya menyangka unggahannya gagal.

    Yang **tersimpan** tetap relatif supaya artikelnya bisa dipindah
    antar lingkungan; bentuk absolut hanya ada di perjalanan menuju
    klien. `normalize_image_src` yang mengembalikannya jadi relatif
    saat isi yang sama dikirim balik untuk disimpan.

    Penggantiannya `str.replace` polos, dan itu cukup: bentuk yang
    diganti dihasilkan `sanitize_html()` sendiri — selalu `src="`
    diikuti MEDIA_URL, tanpa spasi dan tanpa kutip tunggal — bukan
    HTML sembarangan dari luar.
    """

    if not value or not base_url:
        return value or ""

    media_url = getattr(settings, "MEDIA_URL", "/media/") or "/media/"

    return value.replace(
        f'src="{media_url}',
        f'src="{base_url.rstrip("/")}{media_url}',
    )


def strip_tags(value: str | None) -> str:
    """
    Versi teks polos, dipakai pencarian dan cuplikan hasil cari.

    Pencarian `icontains` pada HTML mentah akan mencocokkan nama tag
    dan atribut — mengetik "table" memunculkan tiap artikel yang
    kebetulan punya tabel.
    """

    if not value:
        return ""

    collected: list[str] = []

    class _Stripper(HTMLParser):
        def handle_data(self, data):
            collected.append(data)

        def handle_startendtag(self, tag, attrs):
            collected.append(" ")

        def handle_starttag(self, tag, attrs):
            if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
                collected.append(" ")

    stripper = _Stripper(convert_charrefs=True)
    stripper.feed(value)
    stripper.close()

    return " ".join("".join(collected).split())
