"""
Nomor pegawai otomatis.

Formatnya `<KODE COMPANY><YY><4 digit>` — `KW260001`. Deretnya terpisah
per **company dan per tahun**: KW dan IMM berjalan sendiri-sendiri, dan
tahun berikutnya mulai lagi dari 0001.

**Tidak ada penghitung baru di modul HR.** Yang dipakai
`NumberingSequence` + `DocumentSeries` yang sudah lama ada dan sudah
dipakai nomor Cuti, Travel Request, dan Roster — lengkap dengan
`select_for_update` pada baris deretnya. Membuat penghitung sendiri
berarti dua mesin penomoran dengan dua perilaku penguncian, dan yang
baru pasti yang salah.

Kenapa **bukan** `Employee.objects.count() + 1`, yang selalu jadi
godaan pertama:

* pegawai yang dihapus membuat nomornya dipakai ulang, dan nomor
  pegawai muncul di slip gaji, kontrak, dan mesin absensi — dipakai
  ulang berarti dua orang berbagi identitas;
* dua orang yang menekan Simpan bersamaan mendapat angka yang sama,
  dan yang kalah baru tahu saat constraint uniknya meledak;
* penghitungnya global, sedangkan yang diminta per company per tahun.

Baris `NumberingSequence` per company dibuat saat pertama kali dipakai.
Sesudah itu ia jadi baris master biasa: HR bisa mengubah prefix,
padding, atau jumlah digit tahunnya dari layar Numbering tanpa
menyentuh kode.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.administration.models import NumberingSequence


MODULE = "hr"
DOCUMENT_TYPE = "employee"


class EmployeeNumberService:
    @staticmethod
    def sequence_for(company) -> NumberingSequence | None:
        """
        Baris deret milik company ini, dibuat kalau belum ada.

        Prefixnya diambil dari `Company.code` **saat baris deretnya
        dibuat**, lalu berhenti di situ. Company yang berganti kode
        tidak boleh membuat nomor pegawai lama jadi tidak konsisten
        dengan yang baru tanpa ada yang memutuskan — kalau memang mau
        diganti, barisnya disunting dari layar Numbering.
        """
        if company is None:
            return None

        code = str(getattr(company, "code", "") or "").strip().upper()

        if not code:
            return None

        defaults = {
            "code": f"EMP-{code}",
            "name": f"Employee Number — {company.name}",
            "prefix": code,
            "suffix": "",
            # Menempel tanpa pemisah: KW260001, bukan KW/26/0001.
            "separator": "",
            "padding": 4,
            "year_digits": 2,
            "reset_yearly": True,
            "reset_monthly": False,
        }

        try:
            with transaction.atomic():
                sequence, _ = NumberingSequence.objects.get_or_create(
                    company=company,
                    module=MODULE,
                    document_type=DOCUMENT_TYPE,
                    defaults=defaults,
                )

        except IntegrityError:
            # Dua pembuatan pegawai yang bersamaan pada company yang
            # sama, dan keduanya melihat barisnya belum ada. Yang kalah
            # membaca ulang; constraint uniknya sudah menjamin cuma ada
            # satu. Dibungkus atomic sendiri supaya kegagalannya tidak
            # ikut membatalkan transaksi pembuatan pegawainya.
            sequence = (
                NumberingSequence.objects
                .filter(
                    company=company,
                    module=MODULE,
                    document_type=DOCUMENT_TYPE,
                )
                .first()
            )

        return sequence

    @staticmethod
    def preview(company) -> str:
        """
        Nomor yang **akan** terbit untuk company ini — tanpa
        mengambilnya.

        Dipakai form: begitu Company dipilih, kolom Employee Number
        langsung memperlihatkan `KW260007` alih-alih kotak kosong
        berlabel "terisi otomatis" yang tidak memberi tahu apa-apa.

        Tidak menyentuh apa pun. Tidak membuat baris `NumberingSequence`
        (membuat master hanya karena ada yang membuka form akan
        menghasilkan baris deret untuk company yang tidak pernah dipakai),
        tidak menaikkan `last_number`, tidak mengunci. Konsekuensinya
        angka ini **tebakan**: dua orang yang membuka form bersamaan
        melihat angka yang sama, dan yang benar-benar terbit tetap
        ditentukan `next_number()` saat Simpan ditekan. Karena itu
        kolomnya read-only selama Auto menyala — angka yang bisa
        diketik ulang oleh pengguna tapi diabaikan server lebih buruk
        daripada tidak ditampilkan.
        """
        from datetime import date

        from apps.administration.models import DocumentSeries

        if company is None:
            return ""

        code = str(getattr(company, "code", "") or "").strip().upper()

        if not code:
            return ""

        sequence = (
            NumberingSequence.objects
            .filter(
                company=company,
                module=MODULE,
                document_type=DOCUMENT_TYPE,
                is_deleted=False,
            )
            .first()
        )

        year = date.today().year

        if sequence is None:
            # Company yang belum pernah punya pegawai. Angkanya dirakit
            # dari bawaan yang sama dengan `sequence_for()` supaya yang
            # dilihat di layar sama dengan yang nanti terbit.
            return f"{code}{str(year)[-2:]}0001"

        last = (
            DocumentSeries.objects
            .filter(
                sequence=sequence,
                year=year if sequence.reset_yearly else 0,
                month=None,
            )
            .order_by("pk")
            .values_list("last_number", flat=True)
            .first()
            or 0
        )

        return DocumentNumberService.format(
            sequence=sequence,
            number=last + 1,
            year=year if sequence.reset_yearly else 0,
            month=None,
        )

    @classmethod
    def next_number(cls, *, company) -> str:
        """
        Nomor berikutnya untuk company ini, atau string kosong.

        Kosong dikembalikan kalau companynya belum diisi atau belum
        punya kode — pemanggil yang memutuskan itu error atau bukan.
        Di jalur pembuatan pegawai, itu error: nomor pegawai wajib.
        """
        sequence = cls.sequence_for(company)

        if sequence is None:
            return ""

        # Penguncian barisnya ada di sini — `DocumentSeries` diambil
        # dengan `select_for_update`, jadi dua permintaan bersamaan
        # antre, bukan mendapat angka yang sama.
        return DocumentNumberService.next(
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            company=company,
        )
