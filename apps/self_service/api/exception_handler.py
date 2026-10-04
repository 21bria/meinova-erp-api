"""
Kode mesin pada balasan galat Self Service.

`/me` punya tiga kegagalan yang **harus dibedakan frontend**, dan
membedakannya lewat kalimat berarti satu perbaikan tata bahasa mematahkan
satu cabang kode. Status HTTP sendirian juga tidak cukup: 404 di sini
berarti "akun belum ditautkan", sementara 404 di endpoint lain berarti
barisnya memang tidak ada.

**Dipasang per-view, bukan mengganti `EXCEPTION_HANDLER` global.**
Menambah kunci ke handler global mengubah bentuk balasan setiap endpoint
di sistem ini demi tiga kelas galat di satu app — perubahan yang
permukaannya jauh lebih luas daripada manfaatnya. `APIView.get_exception_handler()`
memang disediakan DRF untuk keperluan ini.

Handler lama tetap yang mengerjakan pembungkusannya; berkas ini hanya
menambahkan satu kunci di atas hasilnya.
"""

from rest_framework.exceptions import APIException

from apps.core.exceptions import meinova_exception_handler


def self_service_exception_handler(exc, context):
    response = meinova_exception_handler(exc, context)

    if response is None:
        return None

    if not isinstance(exc, APIException):
        return response

    code = getattr(exc, "default_code", None)

    # `get_codes()` memulangkan kode yang sebenarnya terpasang pada
    # detail — yang bisa berbeda dari `default_code` kalau pemanggilnya
    # menyetel sendiri. Untuk galat berisi banyak field ia memulangkan
    # dict/list; yang seperti itu tidak punya satu kode tunggal, jadi
    # dilewati alih-alih dipaksa jadi string yang tidak berarti.
    try:
        codes = exc.get_codes()
    except Exception:
        codes = None

    if isinstance(codes, str):
        code = codes

    if code and isinstance(response.data, dict):
        response.data["code"] = str(code)

    return response
