"""
Cakupan data untuk tabel anak milik Employee.

Seluruh sub-resource kartu pegawai (rekening, keluarga, pendidikan,
dokumen, sertifikat, pengalaman, medis, pelatihan, penempatan payroll)
adalah baris yang menunjuk satu `employee`. Cakupannya karena itu sama
persis dengan cakupan Employee, cuma menembus satu relasi.

**Kenapa satu konstanta, bukan sembilan salinan.** Peta ini harus tetap
sama dengan `EmployeeViewSet.data_scope`; kalau tidak, admin yang
dicakup ke satu lokasi membaca sepuluh pegawai di tabel Employee lalu
membaca dua puluh rekening di tab Bank — dan selisih itu tidak berbunyi,
ia cuma memperlihatkan data yang seharusnya tertutup. Sembilan salinan
yang harus dijaga tetap sama adalah persis cara selisih semacam itu
lahir di salah satunya saja.

**Ini lapisan yang berbeda dari `EmployeeDataPolicy`, dan keduanya
memang harus ada.** `data_subject` menjawab "**jenis** data apa yang
boleh dilihat" (gaji, rekening, medis) dan **bawaannya terbuka** —
subject tanpa satu pun baris policy berarti terlihat semua orang.
`data_scope` menjawab "**baris milik siapa**" dan bawaannya menutup.
Menyandarkan keamanan baris pada policy berarti keamanannya hilang
begitu ada yang menghapus satu baris master.

Sudah terbukti sekali: `EmployeeEducation` tidak punya keduanya, dan
pegawai biasa membaca riwayat pendidikan **seluruh** tenant lewat
`GET /api/hr/employee-educations/`. Tiga tabel lain berkonfigurasi sama
persis dan hanya selamat karena kebetulan masih kosong.
"""

from __future__ import annotations


# Peta cakupan Employee itu sendiri. Dulu hidup sebagai literal di
# `EmployeeViewSet.data_scope`; dipindah ke sini supaya pemakai di luar
# viewset — importer absensi, misalnya — menyaring dengan peta yang
# **sama**, bukan dengan salinan yang harus dijaga tetap sama.
EMPLOYEE_SCOPE: dict[str, str] = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}


# Peta cakupan Employee, digeser satu relasi ke `employee`.
#
# Sengaja ditulis sebagai literal, bukan diturunkan otomatis dari
# `EMPLOYEE_SCOPE` dengan menempelkan awalan: `own` di sana bernilai
# `user_id` dan di sini harus `employee__user_id`, jadi penurunan
# otomatis akan menghasilkan satu kunci yang salah tanpa ada yang
# menyadarinya.
EMPLOYEE_CHILD_SCOPE: dict[str, str] = {
    "company": "employee__organization__company",
    "branch": "employee__organization__branch",
    "location": "employee__organization__location",
    "division": "employee__organization__division",
    "department": "employee__organization__department",
    "section": "employee__organization__section",
    "own": "employee__user_id",
}
