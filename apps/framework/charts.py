"""
Deret chart dashboard — **kode kanonik di samping labelnya**.

Sebelum berkas ini, satu-satunya identitas sebuah deret adalah teks
`label` ("Hadir", "Telat"). Teks itu dirakit di Python, jadi ia selalu
berbahasa yang dipilih penulisnya — dan pengguna English membaca legenda
chart berbahasa Indonesia tanpa satu pun error yang menandainya.

Yang **tidak** boleh jadi jalan keluarnya: frontend mencocokkan teks
label lalu menukarnya. Label yang sama juga membawa nama tenant — nama
departemen, nama tipe cuti — dan pencocokan teks akan ikut
menerjemahkannya begitu salah satunya kebetulan sebunyi.

Jadi backend menyebut **kodenya**; frontend menerjemahkan kode itu
(`common.series.<kode>`) dan memakai `label` apa adanya kalau kodenya
belum dikenal. Kodenya adalah kode metrik yang sudah ada (`present`,
`late`, `ot_regular`), bukan kosakata baru.

Aditif: `label` tetap dikirim seperti sebelumnya, jadi klien lama dan
dashboard yang belum mengadopsi helper ini tidak berubah sedikit pun.
"""

from __future__ import annotations

from typing import Any, Sequence


def dataset(
    *,
    code: str,
    label: str,
    data: Sequence[Any],
    color: str | None = None,
) -> dict[str, Any]:
    """Satu deret chart bertumpuk/garis (`datasets`)."""
    result: dict[str, Any] = {
        "label": label,
        "data": list(data),
        "code": code,
    }

    if color:
        result["color"] = color

    return result


def point(
    *,
    code: str,
    label: str,
    value: Any,
    **extra: Any,
) -> dict[str, Any]:
    """
    Satu titik/irisan (`series`).

    Dipakai donut yang irisannya adalah **kategori sistem** (Annual,
    Sick, Field Break). Irisan yang isinya nama milik tenant — nama
    department, nama tipe cuti mentah — tidak boleh diberi kode: kode
    yang tidak ada di katalog memang jatuh ke label, tapi kode yang
    kebetulan bertabrakan dengan kode sistem akan menerjemahkan nama
    orang lain.
    """
    return {"label": label, "value": value, "code": code, **extra}
