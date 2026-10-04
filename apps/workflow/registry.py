"""
Pendaftaran modul ke engine.

Kotak masuk approval satu untuk semua modul, jadi saat approver menekan
tombol dari sana, engine harus bisa memberi tahu modul pemilik dokumen
bahwa alurnya berhenti — tanpa mengenal modul itu. Registry ini
jembatannya: modul mendaftarkan satu fungsi per jenis dokumen, engine
memanggilnya.

Kenapa bukan `import apps.hr...` langsung di engine: itu membuat
`workflow` bergantung pada `hr`, dan modul kedua yang memakainya harus
menambah baris `if` di dalam engine. Pola yang sama dengan registry
importer dan registry lookup di codebase ini.

Daftarkan dari `AppConfig.ready()` — kalau lupa, tombol Approve di
kotak masuk tetap jalan tapi status dokumennya tidak ikut berpindah,
dan gagalnya diam.
"""

from __future__ import annotations

import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)


CompletionHandler = Callable[[Any, str], Any]


_HANDLERS: dict[tuple[str, str], CompletionHandler] = {}


def register_completion(module: str, document_type: str):
    """
    Mendaftarkan apa yang harus terjadi saat alur satu jenis dokumen
    berhenti.

    Fungsinya menerima `(instance, status)` — `status` adalah nilai
    `InstanceStatus`, dan modulnya yang memetakan itu ke kolom status
    miliknya sendiri.
    """
    key = (module.strip().lower(), document_type.strip().lower())

    def wrapper(handler: CompletionHandler) -> CompletionHandler:
        if key in _HANDLERS:
            logger.warning(
                "Handler workflow untuk %s/%s didaftarkan dua kali — "
                "yang terakhir menang.",
                *key,
            )

        _HANDLERS[key] = handler

        return handler

    return wrapper


def completion_handler(
    *,
    module: str,
    document_type: str,
) -> CompletionHandler | None:
    """
    Handler modul, atau None kalau belum ada yang mendaftar.

    None bukan kesalahan: modul yang cuma butuh jejak persetujuan tanpa
    kolom status sendiri memang tidak perlu mendaftar.
    """
    return _HANDLERS.get(
        (module.strip().lower(), document_type.strip().lower()),
    )


def registered() -> dict[tuple[str, str], CompletionHandler]:
    return dict(_HANDLERS)


# ----------------------------------------------------------------------
# Rute dokumen di frontend
# ----------------------------------------------------------------------
#
# Kotak masuk dan layar monitoring menampilkan dokumen dari modul mana
# pun, jadi keduanya butuh jalan untuk membukanya. Engine tidak boleh
# menebak rutenya — `hr/leave_request` yang halamannya `/hr/leave/<id>`
# tidak bisa disimpulkan dari nama modul. Jadi modulnya yang
# mendaftarkan, sama seperti handler penyelesaian di atas.
#
# Pola memakai `{id}`, diisi `WorkflowInstance.object_id`.

_ROUTES: dict[tuple[str, str], str] = {}


def register_route(module: str, document_type: str, pattern: str) -> None:
    """
    Mendaftarkan pola rute frontend untuk satu jenis dokumen.

    Contoh: ``register_route("hr", "leave_request", "/hr/leave/{id}/edit")``
    """
    if "{id}" not in pattern:
        raise ValueError(
            f"Pola rute '{pattern}' harus memuat placeholder '{{id}}'.",
        )

    _ROUTES[(module.strip().lower(), document_type.strip().lower())] = pattern


def document_url(*, module: str, document_type: str, object_id) -> str | None:
    """
    Rute dokumen, atau None kalau modulnya belum mendaftar.

    None bukan kesalahan — frontend cukup tidak menampilkan tombolnya.
    Menebak rute yang salah jauh lebih buruk: tombolnya tampak berfungsi
    lalu mendarat di halaman 404.
    """
    pattern = _ROUTES.get(
        (module.strip().lower(), document_type.strip().lower()),
    )

    if pattern is None:
        return None

    return pattern.replace("{id}", str(object_id))
