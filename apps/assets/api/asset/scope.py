"""
Peta cakupan data Asset Register — dipakai viewset dan lookup aset.

`location` di aset adalah lokasi custody yang sedang terbuka (ACTIVE)
atau penempatan awal (DRAFT): satu jalur ORM untuk keduanya, dan tidak
pernah kosong, jadi draft tidak hilang dari layar walau
`DATA_SCOPE_INCLUDE_NULL=False`.
"""

ASSET_SCOPE = {
    "company": "company",
    "branch": "location__branch",
    "location": "location",
}
