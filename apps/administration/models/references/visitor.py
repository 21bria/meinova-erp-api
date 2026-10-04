"""
Master referensi modul Visitor Management.

Dua master saja, dan keduanya memang belum ada di tenant mana pun:

* ``VisitPurpose`` — alasan kunjungan (Business Meeting, Audit, …)
* ``VisitType``    — sifat kunjungannya (Official, Vendor, Personal, …)

Yang **tidak** dibuat di sini, karena masternya sudah ada dan dipakai
modul Travel Request: `TransportMode`, `AccommodationType`, `Gender`,
`Nationality`, `City`, `Country`. Dua master moda angkutan di satu
tenant berarti dropdown perjalanan pegawai dan dropdown perjalanan tamu
diisi daftar yang berbeda, dan bedanya baru ketahuan saat ada yang
membandingkan dua laporan.

Sengaja master referensi, bukan `TextChoices`: daftar alasan kunjungan
berbeda per klien — tambang menerima inspeksi Dinas ESDM, pabrik
menerima audit pelanggan — dan menambah satu baris tidak boleh menunggu
rilis.
"""

from django.db import models

from apps.core.models.base_reference import BaseReference


class VisitPurpose(BaseReference):
    """
    Alasan kunjungan. Dipakai `VisitorRequest.visit_purpose`.

    `requires_approval` ada supaya kunjungan rutin yang tidak perlu
    tanda tangan siapa pun tidak dipaksa lewat alur — tapi **belum
    dibaca siapa pun** hari ini: seluruh Visitor Request masih melewati
    alur yang sama. Ditulis sekarang karena mengubah master yang sudah
    terisi jauh lebih mahal daripada menambah kolom yang menunggu.
    """

    requires_approval = models.BooleanField(
        default=True,
        help_text=(
            "Kunjungan dengan alasan ini wajib lewat alur persetujuan. "
            "Belum dibaca — seluruh Visitor Request hari ini tetap "
            "melewati alurnya."
        ),
    )

    class Meta(BaseReference.Meta):
        db_table = "master_visit_purpose"


class VisitType(BaseReference):
    """
    Sifat kunjungan — Official, Vendor, Customer, Personal.

    Dibedakan dari `VisitPurpose` karena keduanya menjawab pertanyaan
    yang berbeda: "kenapa datang" (rapat, audit) dan "datang sebagai
    apa" (vendor, pelanggan). Satu master yang merangkap keduanya
    menghasilkan daftar perkalian silang — "Rapat Vendor", "Rapat
    Pelanggan", "Audit Vendor" — yang tidak bisa dilaporkan per salah
    satu sumbunya.
    """

    class Meta(BaseReference.Meta):
        db_table = "master_visit_type"
