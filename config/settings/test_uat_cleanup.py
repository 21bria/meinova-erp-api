"""
Settings sekali pakai untuk menjalankan test pembuangan dataset UAT.

Alasannya sama dengan `test_selfservice`: **database test dipakai
bersama**, dan dua run yang berjalan bersamaan saling menjatuhkan —
yang satu menghapus schema tenant yang sedang dipakai yang lain.

Di sini taruhannya lebih besar dari biasa: yang diuji perkakas yang
pekerjaannya menghapus baris. Databasenya diberi nama sendiri supaya
run ini tidak pernah menyentuh apa pun milik run lain.
"""

from .local import *  # noqa: F401,F403
from .local import DATABASES


DATABASES["default"]["TEST"] = {"NAME": "test_meinova_uat_cleanup"}
