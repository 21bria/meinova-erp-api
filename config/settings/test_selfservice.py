"""
Settings sekali pakai untuk menjalankan test Self Service sendirian.

Alasannya satu: **database test dipakai bersama**. Dua run yang berjalan
bersamaan di database test yang sama saling menjatuhkan — yang satu
menghapus schema tenant yang sedang dipakai yang lain, dan kegagalannya
muncul sebagai galat yang sama sekali tidak menyebut sebabnya.

`TEST["NAME"]` menamai databasenya sendiri, jadi run ini tidak pernah
bertabrakan dengan run lain di mesin yang sama.
"""

from .local import *  # noqa: F401,F403
from .local import DATABASES


DATABASES["default"]["TEST"] = {"NAME": "test_meinova_selfservice"}
