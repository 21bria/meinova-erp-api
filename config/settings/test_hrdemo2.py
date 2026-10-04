"""
Settings sekali pakai untuk test presensi HR-DEMO-2.

Alasannya sama dengan `test_selfservice` dan `test_uat_cleanup`:
**database test dipakai bersama**, dan dua run yang berjalan bersamaan
saling menjatuhkan — yang satu menghapus schema tenant yang sedang
dipakai yang lain.
"""

from .local import *  # noqa: F401,F403
from .local import DATABASES


DATABASES["default"]["TEST"] = {"NAME": "test_meinova_hrdemo2"}
