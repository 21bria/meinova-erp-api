"""
Cakupan data rekrutmen — satu tempat, dipakai tabel dan dropdown.

`Candidate` tidak menyimpan satu pun kolom organisasi: tidak ada
`company`, tidak ada `location`. Yang menghubungkannya ke organisasi
adalah **lowongan yang dilamarnya** (`vacancy`), dan `JobVacancy`
memang membawa company/branch/location/division/department.

Jadi otoritasnya diturunkan lewat relasi itu — bukan ditambahkan
sebagai kolom baru. Tidak ada migration di sini, dan memang tidak
seharusnya ada: relasinya sudah ada sejak awal, cuma tidak pernah
dipakai untuk menjawab "pelamar siapa yang boleh saya lihat".

Satu hal yang harus disadari: **`vacancy` boleh kosong.** Pelamar
lepas — yang mengirim lamaran tanpa menunjuk lowongan — tidak punya
jalur organisasi sama sekali. Untuk pemegang cakupan terbatas, baris
seperti itu **tidak** terlihat: `DATA_SCOPE_INCLUDE_NULL` bawaannya
`False`, jadi kolom kosong berarti "tidak cocok", bukan "cocok untuk
semua". Itu arah kegagalan yang benar — tidak adanya otoritas yang
bisa dihitung tidak boleh berarti terbuka. Yang bercakupan penuh tetap
melihatnya, dan merekalah yang menugaskannya ke lowongan.
"""

from __future__ import annotations


CANDIDATE_SCOPE: dict[str, str] = {
    "company": "vacancy__company",
    "branch": "vacancy__branch",
    "location": "vacancy__location",
    "division": "vacancy__division",
    "department": "vacancy__department",
}


# Lowongan itu sendiri. Ditulis terpisah, bukan diturunkan dengan
# memotong awalan `vacancy__`: penurunan otomatis semacam itu benar
# hari ini dan diam-diam salah begitu salah satu peta bergeser.
JOB_VACANCY_SCOPE: dict[str, str] = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "division",
    "department": "department",
}


# Wawancara menunjuk pelamarnya, jadi cakupannya cakupan pelamar itu,
# digeser satu relasi. Perlu ditulis: catatan wawancara memuat nama
# dan penilaian orang yang sama, jadi membiarkannya terbuka membatalkan
# penjagaan di `Candidate`.
CANDIDATE_INTERVIEW_SCOPE: dict[str, str] = {
    key: f"candidate__{path}"
    for key, path in CANDIDATE_SCOPE.items()
}
