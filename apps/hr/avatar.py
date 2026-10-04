"""
Foto pegawai: satu urutan resolusi, dipakai semua layar.

Tiga layar membutuhkan jawaban yang sama — Self Service, kartu pegawai
HR, dan avatar di sidebar — dan kalau masing-masing menyusun urutannya
sendiri, yang terjadi bukan error melainkan **ketidaksepakatan yang
diam**: sidebar menampilkan inisial sementara halaman profil di sebelahnya
menampilkan foto, untuk orang yang sama, pada saat yang sama.

Urutannya:

    avatar_file  →  avatar (lama)  →  inisial

Kenapa `avatar_file` lebih dulu
-------------------------------
Ia berkas yang berdiri di `uploads.UploadedFile`, jadi penyajiannya lewat
`preview/` yang menuntut login. Kolom `avatar` yang lama sebuah
`ImageField` yang dilayani `MEDIA_URL` statis — jalurnya bisa dibuka
siapa pun yang menebaknya. Selama dua-duanya masih ada, yang berautentikasi
harus menang.

Kenapa yang lama tetap dibaca
-----------------------------
Menghapusnya berarti tenant yang kolomnya sudah terisi kehilangan foto
pegawainya pada hari rilis, tanpa satu pun pesan. Ia dibaca, tidak pernah
ditulis; foto baru selalu masuk lewat `avatar_file`.

Inisial, bukan kotak kosong
---------------------------
Pegawai tanpa foto mendapat inisialnya. Kotak kosong terbaca seperti
gambar yang gagal dimuat, dan itu mengirim orang mencari masalah yang
tidak ada.
"""

from __future__ import annotations


def employee_initials(employee) -> str:
    """
    Dua huruf dari nama pegawai. `Bimo Nugroho` → `BN`.

    Nama satu kata tetap menghasilkan satu huruf, bukan kotak kosong —
    dan pegawai yang belum punya nama sama sekali mendapat `?`, yang
    setidaknya menyatakan dirinya sebagai ketiadaan data alih-alih
    sebagai kegagalan render.
    """
    source = (getattr(employee, "full_name", "") or "").strip()

    parts = [part for part in source.split() if part]

    if not parts:
        return "?"

    if len(parts) == 1:
        return parts[0][:2].upper()

    return (parts[0][0] + parts[-1][0]).upper()


def employee_photo(employee) -> tuple[str | None, object | None]:
    """
    **Urutan resolusinya, tanpa alamat.** `(source, objek)`.

    Dipisah dari `resolve_employee_avatar()` di Stage 3 karena dua
    audiens merakit alamat yang berbeda untuk foto yang sama:

    * kartu pegawai HR dan sidebar memakai `/api/uploads/<id>/preview/`,
      yang hak bacanya diturunkan dari hak baca baris Employee-nya;
    * Self Service memakai `/api/me/avatar/`, yang dijaga identitas —
      pegawai selalu boleh melihat fotonya sendiri, sekalipun ia tidak
      punya `hr.view_employee`.

    Yang **tidak boleh** berbeda antar keduanya adalah urutannya, dan
    itulah yang tinggal di fungsi ini. Alamatnya boleh berbeda; jawaban
    "foto yang mana" tidak.

    `(None, None)` berarti tidak ada foto — pemanggilnya jatuh ke
    inisial.
    """
    uploaded = getattr(employee, "avatar_file", None)

    if uploaded is not None:
        # Berkas yang sudah dihapus atau yang barisnya ada tapi
        # berkasnya tidak, tidak punya gambar untuk ditampilkan. Jatuh
        # ke jalur berikutnya, bukan dibalas alamat yang pasti 404.
        if (
            not getattr(uploaded, "is_deleted", False)
            and getattr(uploaded, "file", None)
        ):
            return "upload", uploaded

    legacy = getattr(employee, "avatar", None)

    if legacy:
        return "legacy", legacy

    return None, None


def _upload_url(uploaded, request) -> str | None:
    """
    Alamat penyajian berautentikasi sebuah `UploadedFile`.

    **Bukan `uploaded.file.url`.** Yang itu jalur penyimpanan mentah dan
    dilayani tanpa pemeriksaan siapa pun; `preview/` melewati
    `FileAccessService`, yang menurunkan hak bacanya dari record yang
    memuat berkasnya.

    Dirakit dari `public_id`, bukan dari pk: pk berkas tidak pernah
    muncul di API unggahan, dan `UploadedFileViewSet` memang mencarinya
    lewat `public_id` (`lookup_field`).
    """
    if uploaded is None:
        return None

    # Berkas yang sudah dihapus atau belum selesai diproses tidak punya
    # gambar untuk ditampilkan. Dibalas `None` supaya pemanggilnya jatuh
    # ke jalur berikutnya — bukan alamat yang pasti membalas 404.
    if getattr(uploaded, "is_deleted", False):
        return None

    if not getattr(uploaded, "file", None):
        return None

    path = f"/api/uploads/{uploaded.public_id}/preview/"

    if request is None:
        return path

    return request.build_absolute_uri(path)


def _legacy_url(employee, request) -> str | None:
    """Kolom `avatar` lama, kalau memang terisi."""
    legacy = getattr(employee, "avatar", None)

    if not legacy:
        return None

    try:
        url = legacy.url
    except ValueError:
        # `ImageField` tanpa berkas fisik melempar saat `.url` dibaca.
        return None

    if request is None:
        return url

    return request.build_absolute_uri(url)


def resolve_employee_avatar(employee, *, request=None) -> dict:
    """
    Foto pegawai dalam bentuk yang siap dikirim ke layar.

    Selalu mengembalikan dict dengan bentuk yang sama, termasuk untuk
    pegawai tanpa foto — layar yang menerimanya tidak perlu membedakan
    "tidak ada foto" dari "field-nya tidak dikirim", dan `initials`
    selalu ada sehingga fallback-nya tidak pernah perlu dihitung ulang
    di frontend.

    `source` bukan hiasan: ia yang memungkinkan kita menghitung berapa
    tenant yang masih bersandar pada kolom lama sebelum memutuskan kapan
    kolom itu boleh dihapus.
    """
    initials = employee_initials(employee)

    source, obj = employee_photo(employee)

    url = None

    if source == "upload":
        url = _upload_url(obj, request)
    elif source == "legacy":
        url = _legacy_url(employee, request)

    # Berkas yang lolos `employee_photo()` tapi gagal dirakit alamatnya
    # (mis. `ImageField` yang berkas fisiknya hilang) tidak boleh
    # tertinggal sebagai `source` tanpa `url` — pasangan itu terbaca
    # oleh layar sebagai "ada foto" lalu merender kotak kosong.
    if url is None:
        source = None

    return {
        "url": url,
        "source": source,
        "initials": initials,
    }
