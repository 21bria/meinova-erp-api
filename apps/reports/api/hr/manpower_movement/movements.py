"""
Jenis pergerakan, dan **suku mana yang masuk identitas**.

Ditulis sekali di sini lalu dibaca KPI, chart, tabel, dan filter —
alasan yang sama dengan `statuses.py` milik Contract Expiry. Ambang dan
tanda (+/−) yang tersebar di empat berkas adalah cara paling mudah
membuat KPI dan tabel berbeda pendapat tanpa satu pun test merah.

Identitas yang dijaga laporan ini:

```
Opening Headcount + Join + Transfer In − Transfer Out − Exit
    = Closing Headcount
```

`INTERNAL_MOVE` **tidak** ada di dalamnya, dan itu disengaja: mutasi
yang kedua ujungnya berada di dalam populasi yang dilaporkan tidak
mengubah jumlah kepala sama sekali. Ia tetap diterbitkan sebagai baris
tabel karena yang membaca laporan ini ingin melihat pergerakannya, tapi
menambahkannya ke suku mana pun akan membuat Closing meleset persis
sebanyak mutasi internal yang terjadi.
"""

from __future__ import annotations


class MovementType:
    JOIN = "join"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    INTERNAL_MOVE = "internal_move"
    EXIT = "exit"


MOVEMENT_LABELS = {
    MovementType.JOIN: "Join",
    MovementType.TRANSFER_IN: "Transfer In",
    MovementType.TRANSFER_OUT: "Transfer Out",
    MovementType.INTERNAL_MOVE: "Internal Move",
    MovementType.EXIT: "Exit",
}


# Tanda tiap jenis di dalam identitas. `INTERNAL_MOVE` bernilai 0 —
# ditulis sebagai baris, bukan dihilangkan dari peta, supaya jenis baru
# yang ditambahkan tanpa memikirkan tandanya gagal di test dan bukan
# diam-diam ikut terjumlah.
MOVEMENT_SIGNS = {
    MovementType.JOIN: 1,
    MovementType.TRANSFER_IN: 1,
    MovementType.TRANSFER_OUT: -1,
    MovementType.INTERNAL_MOVE: 0,
    MovementType.EXIT: -1,
}


# Urutan tampil: masuk dulu, keluar terakhir, dan itu urutan yang sama
# dengan jembatan Opening → Closing di chart. Tabel yang urutan
# jenisnya berbeda dari chart di atasnya membuat pembacanya
# mencocokkan dua daftar.
MOVEMENT_ORDER = [
    MovementType.JOIN,
    MovementType.TRANSFER_IN,
    MovementType.TRANSFER_OUT,
    MovementType.INTERNAL_MOVE,
    MovementType.EXIT,
]


def movement_label(code: str) -> str:
    return MOVEMENT_LABELS.get(code, code)


def movement_options() -> list[dict]:
    """Isi dropdown filter Movement Type — bentuk lookup yang sama
    dengan `expiry-status/` milik Contract Expiry."""
    return [
        {"value": code, "label": MOVEMENT_LABELS[code]}
        for code in MOVEMENT_ORDER
    ]
