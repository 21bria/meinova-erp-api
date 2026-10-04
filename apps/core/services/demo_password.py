"""
Password akun peragaan/UAT — **selalu** datang dari luar kode.

Repositori ini publik. Password bawaan yang tertulis di sumber berarti
setiap tenant peragaan yang diseed bisa dimasuki siapa pun yang membaca
GitHub, jadi seeder dan perintah pembentuk akun membaca password dari
`--password` (kalau perintahnya punya) atau variabel lingkungan
`DEMO_PASSWORD`, dan **menolak berjalan** kalau keduanya kosong — bukan
diam-diam jatuh ke password yang sudah dikenal.

Dipanggil di awal perintah (sebelum menulis apa pun), supaya yang lupa
menyetelnya mendapat satu pesan jelas, bukan seed yang gagal di tengah.
"""

import os

from django.core.management.base import CommandError


DEMO_PASSWORD_ENV = "DEMO_PASSWORD"


# `CommandError`: seeder dipanggil dari perintah manajemen, dan yang
# menjalankannya cukup melihat satu baris pesan, bukan traceback.
class DemoPasswordMissing(CommandError):
    pass


def demo_password(explicit: str | None = None) -> str:
    value = explicit or os.environ.get(DEMO_PASSWORD_ENV, "")

    if not value:
        raise DemoPasswordMissing(
            f"{DEMO_PASSWORD_ENV} environment variable is required "
            "(atau oper --password bila perintahnya mendukung). "
            "Tidak ada password bawaan untuk akun peragaan."
        )

    return value
