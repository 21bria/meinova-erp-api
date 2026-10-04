"""
Cakupan data Asset Assignment — **sisi pemilik**.

`source_location` adalah lokasi penyimpanan asal, selalu milik company
pemilik aset. Satu jalur, sengaja tanpa union asal/tujuan (itu Transfer,
ASSET-5). Penerima lintas company tidak memberi admin company penerima
akses ke dokumen maupun register company pemilik (O-8).
"""

ASSIGNMENT_SCOPE = {
    "company": "company",
    "branch": "source_location__branch",
    "location": "source_location",
}
