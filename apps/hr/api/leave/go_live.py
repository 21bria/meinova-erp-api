"""
Mencari tanggal go-live cuti yang berlaku untuk seorang pegawai.

Dipisah dari `entitlement.py` karena dipakai empat pemanggil yang tidak
saling kenal — kalkulator jatah, importer saldo awal, service posting,
dan perintah manajemen — dan tiga di antaranya tidak berurusan dengan
jatah sama sekali.

Aturannya satu kalimat: **tanggal itu milik company pegawainya**, dan
company tempat seseorang bekerja diambil dari penempatan organisasinya.
Tidak ada penjenjangan seperti `LeavePolicy` — go-live bukan kebijakan
yang bisa dibedakan per lokasi atau per golongan; ia tanggal sebuah
badan usaha menyerahkan pencatatannya, dan setengah perusahaan tidak
bisa pindah sementara setengahnya belum.
"""

from __future__ import annotations

from datetime import date

from apps.hr.models import LeaveGoLive


class LeaveGoLiveResolver:
    @staticmethod
    def company_id_of(employee) -> int | None:
        organization = getattr(employee, "organization", None)

        return getattr(organization, "company_id", None)

    @classmethod
    def for_employee(cls, employee, *, go_live_map: dict | None = None):
        """
        Baris go-live yang berlaku, atau None.

        `go_live_map` adalah peta `{company_id: LeaveGoLive}` hasil
        **satu** query di pemanggil, dipakai generator yang memutar
        ratusan pegawai. Dikosongkan = di-resolve sendiri, satu query
        per pemanggilan — benar untuk pemakaian satuan, mahal untuk
        perulangan. Pola yang sama dengan `opening_balance_map`.
        """
        company_id = cls.company_id_of(employee)

        if company_id is None:
            return None

        if go_live_map is not None:
            return go_live_map.get(company_id)

        return (
            LeaveGoLive.objects
            .filter(
                company_id=company_id,
                is_active=True,
                is_deleted=False,
            )
            .first()
        )

    @staticmethod
    def map_all(*, companies=None) -> dict:
        """Satu query untuk seluruh company yang sudah bermigrasi."""
        queryset = LeaveGoLive.objects.filter(
            is_active=True,
            is_deleted=False,
        )

        if companies is not None:
            queryset = queryset.filter(company__in=companies)

        return {row.company_id: row for row in queryset}

    @staticmethod
    def owns_year(go_live, *, year: int, join_date: date | None) -> bool:
        """
        Apakah **sistem lama** yang memegang jatah tahun itu.

        True berarti jatahnya tidak diterbitkan di sini: angkanya datang
        dari Leave Opening Balance.

        Tiga cabangnya, dan yang ketiga yang paling gampang terlewat:

        * Tahun **sebelum** tahun go-live — sistem ini belum berjalan
          sama sekali. Menerbitkan jatah untuk tahun yang tidak pernah
          dipegangnya berarti mengarang hak.
        * Tahun go-live, pegawai yang **sudah bekerja** sebelum tanggal
          itu — inilah kasus utamanya. Jatah tahun berjalan sudah
          sebagian terpakai di sistem lama, dan yang tersisa persis apa
          yang diserahkan HR lewat saldo awal.
        * Tahun go-live, pegawai yang masuk **pada atau sesudah**
          tanggal go-live — sistem ini yang memegangnya sejak hari
          pertama, jadi jatahnya dihitung normal (prorata menurut
          policy). Melewatkan cabang ini membuat pegawai yang direkrut
          bulan depan mendapat jatah nol tanpa satu pun saldo awal yang
          menjelaskannya.
        """
        if go_live is None or go_live.go_live_date is None:
            return False

        go_live_year = go_live.go_live_date.year

        if year < go_live_year:
            return True

        if year > go_live_year:
            return False

        # Join date kosong: pegawai lama yang datanya belum lengkap.
        # Diperlakukan sebagai bawaan sistem lama — menerbitkan jatah
        # penuh untuk orang yang tanggal masuknya saja belum diketahui
        # adalah tebakan, dan tebakan itu menempel di kartu cutinya.
        if join_date is None:
            return True

        return join_date < go_live.go_live_date
