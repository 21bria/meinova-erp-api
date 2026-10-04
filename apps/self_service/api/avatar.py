"""
`GET /api/me/avatar/` — foto pegawai yang sedang login, disajikan sendiri.

Kenapa Self Service menyajikannya sendiri, bukan menunjuk `preview/`
-------------------------------------------------------------------
`FileAccessService` menurunkan hak baca sebuah berkas dari **record yang
memuatnya**. Begitu `Employee.avatar_file` ada, foto pegawai otomatis
ikut aturan baca `EmployeeViewSet` — termasuk `hr.view_employee` dan
cakupan data. Akibatnya `/api/me/` yang sengaja lepas dari izin
administratif (keputusan Stage 2) akan mengirim alamat foto yang justru
menuntut izin itu: halaman terbuka, gambarnya 404, dan gejalanya terbaca
seperti gangguan jaringan alih-alih seperti izin.

Endpoint ini memutus rantai itu pada **satu titik saja**: fotonya sendiri.
Yang dipakai bukan pelonggaran `FileAccessService` — berkas itu tetap
tertutup untuk siapa pun lewat `/api/uploads/`. Yang berubah cuma bahwa
ada satu jalur tambahan yang dijaga **identitas**, bukan izin model, dan
jalur itu secara konstruksi tidak bisa menunjuk berkas orang lain.

Kenapa ia tidak bisa menunjuk berkas orang lain
-----------------------------------------------
Ia tidak menerima **satu pun** pengenal. Tidak `employee_id`, tidak
`public_id`, tidak id berkas, tidak jalur. Berkasnya ditemukan dengan
menelusuri `request.user → CurrentEmployeeService → employee.avatar_file`,
dan tidak ada tempat di jalur itu yang bisa dititipi nilai dari luar.
Parameter yang tidak pernah dibaca tidak bisa lupa divalidasi.

Isinya dialirkan, bukan dialihkan
---------------------------------
Redirect ke `preview/` akan mengembalikan persis masalah yang sedang
diperbaiki — pengalihan itu mendarat di penjagaan yang sama. Jadi
berkasnya dibuka dan dikirim dari sini.
"""

from __future__ import annotations

import mimetypes

from django.http import FileResponse
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound

from apps.hr.avatar import employee_photo
from apps.self_service.api.views import SelfServiceAPIView


class AvatarNotSet(NotFound):
    """
    Pegawainya belum punya foto.

    404, dan bukan gambar bawaan: yang menentukan seperti apa tampilan
    "tanpa foto" adalah layar, bukan API — dan `/api/me/` sudah
    mengirimkan `initials` untuk itu. Mengirim gambar bawaan dari sini
    berarti dua tempat memutuskan hal yang sama.
    """

    default_detail = "Pegawai ini belum punya foto."
    default_code = "avatar_not_set"


class AvatarUnavailable(APIException):
    """
    Barisnya ada, berkas fisiknya tidak.

    Dibedakan dari `AvatarNotSet` karena artinya berbeda: yang ini
    kerusakan penyimpanan, bukan data yang memang belum diisi, dan yang
    menanganinya bukan pegawainya melainkan yang mengurus sistem.
    """

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = (
        "Foto tersimpan tapi berkasnya tidak ditemukan di penyimpanan. "
        "Hubungi administrator."
    )
    default_code = "avatar_unavailable"


def _content_type(name: str, fallback: str = "application/octet-stream") -> str:
    guessed, _encoding = mimetypes.guess_type(name or "")

    return guessed or fallback


def _stream(file_field, *, filename: str, content_type: str) -> FileResponse:
    """
    Mengirim isi berkas dengan kepala yang sama ketatnya dengan
    `uploads`: jangan ditebak tipenya, jangan disimpan cache bersama.
    """
    storage = file_field.storage
    name = file_field.name

    if not name or not storage.exists(name):
        raise AvatarUnavailable()

    response = FileResponse(
        storage.open(name, "rb"),
        as_attachment=False,
        filename=filename,
        content_type=content_type,
    )

    response["X-Content-Type-Options"] = "nosniff"

    # `private`: foto pegawai tidak boleh mendarat di cache bersama
    # milik proxy. Cache di browser pemiliknya sendiri tidak masalah,
    # tapi membedakan keduanya butuh validator; sampai ada kebutuhannya,
    # yang paling aman yang dipakai.
    response["Cache-Control"] = "private, no-store"

    return response


class SelfAvatarView(SelfServiceAPIView):
    """
    Foto pegawai yang sedang login.

    Urutannya sama persis dengan yang dipakai layar lain — ia dibaca
    dari `apps.hr.avatar.employee_photo()`, bukan ditulis ulang di sini:

        avatar_file → Employee.avatar (lama) → 404 (layar pakai inisial)
    """

    def get(self, request):
        employee = self.employee

        source, obj = employee_photo(employee)

        if source == "upload":
            return _stream(
                obj.file,
                filename=obj.original_name or "avatar",
                content_type=(
                    obj.mime_type
                    or _content_type(obj.original_name, "image/*")
                ),
            )

        if source == "legacy":
            return _stream(
                obj,
                filename=obj.name.rsplit("/", 1)[-1] or "avatar",
                content_type=_content_type(obj.name),
            )

        raise AvatarNotSet()
