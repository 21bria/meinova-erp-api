"""
Cakupan data Asset Return — **sisi asal ∪ sisi tujuan**.

Return memindahkan barang dari lokasi pemakaian (`source_location`) ke
penyimpanan (`destination_location`), dan keduanya boleh berbeda. Dokumen
terlihat oleh pengguna berwenang di salah satu sisi; tidak pernah
di-scope lewat lokasi aset saat ini (berubah begitu dokumennya selesai).

`DataScopeService.filter` hanya menerima satu jalur per jenis scope, jadi
viewset menggabungkan dua pemanggilan (pola O-3, §17). Kedua sisi selalu
milik company pemilik (lokasi custody tetap milik pemilik, juga untuk
pemegang lintas company — O-8), jadi `company` sama di keduanya.

**Lihat ≠ wewenang aksi:** `complete` (barang diterima di penyimpanan)
hanya dari sisi tujuan (`action_sides` di viewset).
"""

RETURN_SOURCE_SCOPE = {
    "company": "company",
    "branch": "source_location__branch",
    "location": "source_location",
}

RETURN_DESTINATION_SCOPE = {
    "company": "company",
    "branch": "destination_location__branch",
    "location": "destination_location",
}
