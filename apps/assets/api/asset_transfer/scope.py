"""
Cakupan Asset Transfer — **lihat = asal ∪ tujuan; aksi per sisi**
(wewenang kanonik Transfer, `docs/claude/assets.md` §17).

| Hak | Sisi |
| --- | --- |
| lihat (list/detail/export), approve/reject (engine) | asal atau tujuan |
| sunting/hapus draft, submit, cancel | **asal** |
| complete (barang diterima) | **tujuan** |

Transfer di lokasi yang sama: satu cakupan memenuhi kedua sisi. Kedua
sisi selalu milik company pemilik (lokasi tujuan wajib milik pemilik,
juga untuk pegawai tujuan lintas company — O-8), jadi admin company
penerima tidak melihat dokumen pemilik.
"""

TRANSFER_SOURCE_SCOPE = {
    "company": "company",
    "branch": "source_location__branch",
    "location": "source_location",
}

TRANSFER_TARGET_SCOPE = {
    "company": "company",
    "branch": "target_location__branch",
    "location": "target_location",
}

SOURCE_ONLY_ACTIONS = (
    "update",
    "partial_update",
    "destroy",
    "bulk_delete",
    "submit",
    "cancel",
)

TARGET_ONLY_ACTIONS = ("complete",)
