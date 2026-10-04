"""
Kosakata kode wilayah Kemendagri, dan satu-satunya tempat yang tahu
bentuknya.

Kode wilayah **berjenjang lewat awalannya**, dan itu satu-satunya
penghubung yang dipakai importer ini:

    11              -> Aceh                    (Province)
    11.01           -> Aceh Selatan            (Kabupaten/Kota)
    11.01.01        -> Bakongan                (Kecamatan)
    11.01.01.2002   -> Ujong Mangki            (Kelurahan/Desa)

**Jangan pernah menentukan induk lewat nama.** Nama wilayah tidak unik
("Kota Sorong" ada di dua provinsi pada rentang tahun yang berbeda),
sering ditulis dengan ejaan berbeda antar berkas ("Ujong" vs "Ujung"),
dan sebagian membawa keterangan dalam kurung. Kecocokan berbasis nama
akan tetap menghasilkan angka yang terlihat masuk akal — itu yang
membuatnya berbahaya: barisnya tersimpan, induknya salah, dan tidak ada
satu pun pesan yang menyebutkannya.

Kode disimpan sebagai **string, apa adanya**. `11` bukan sebelas, dan
`11.01` bukan bilangan pecahan — begitu ada yang mengubahnya jadi angka,
leading zero-nya hilang dan `01.01` tidak bisa lagi dibedakan dari
`1.1`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


PROVINCE = "province"
CITY = "city"
DISTRICT = "district"
VILLAGE = "village"


@dataclass(frozen=True)
class GeographyLevel:
    """
    Satu tingkat wilayah beserta seluruh yang membedakannya dari tingkat
    lain: bentuk kodenya, modelnya, induknya, dan nama berkas sumbernya.

    Dibuat sebagai data, bukan empat cabang `if`, supaya validator dan
    importer bisa ditulis sekali lalu dijalankan untuk keempatnya. Satu
    salinan logika per tingkat adalah persis cara aturan yang sudah
    dibetulkan di satu tempat tetap salah di tiga tempat lain.
    """

    key: str
    label: str
    pattern: re.Pattern[str]

    # Nama model di app `administration`. Disebut lewat string supaya
    # modul ini tidak perlu mengimpor model — ia dipakai juga oleh
    # validator yang sengaja tidak menyentuh database sama sekali.
    model_name: str

    # Tingkat induknya. `None` untuk Province: induknya Country, dan
    # Country tidak punya kode berjenjang.
    parent_key: str | None

    # Nama field FK ke induknya pada model tingkat ini.
    parent_field: str

    # Nama berkas CSV bawaan.
    filename: str

    def matches(self, aid: str) -> bool:
        return bool(self.pattern.fullmatch(aid))


LEVELS: dict[str, GeographyLevel] = {
    PROVINCE: GeographyLevel(
        key=PROVINCE,
        label="Province",
        pattern=re.compile(r"\d{2}"),
        model_name="Province",
        parent_key=None,
        parent_field="country",
        filename="provinsi.csv",
    ),
    CITY: GeographyLevel(
        key=CITY,
        label="Kabupaten/Kota",
        pattern=re.compile(r"\d{2}\.\d{2}"),
        model_name="City",
        parent_key=PROVINCE,
        parent_field="province",
        filename="kabupaten_kota.csv",
    ),
    DISTRICT: GeographyLevel(
        key=DISTRICT,
        label="Kecamatan",
        pattern=re.compile(r"\d{2}\.\d{2}\.\d{2}"),
        model_name="District",
        parent_key=CITY,
        parent_field="city",
        filename="kecamatan.csv",
    ),
    VILLAGE: GeographyLevel(
        key=VILLAGE,
        label="Kelurahan/Desa",
        pattern=re.compile(r"\d{2}\.\d{2}\.\d{2}\.\d{4}"),
        model_name="Village",
        parent_key=DISTRICT,
        parent_field="district",
        filename="kelurahan.csv",
    ),
}


# Urutan import, dan urutannya bukan selera: anak tidak bisa ditulis
# sebelum induknya ada. Dipakai apa adanya oleh service dan perintah
# manajemen — jangan diurutkan ulang di pemanggil.
LEVEL_ORDER: tuple[str, ...] = (
    PROVINCE,
    CITY,
    DISTRICT,
    VILLAGE,
)


def get_level(key: str) -> GeographyLevel:
    level = LEVELS.get(str(key or "").strip().lower())

    if level is None:
        raise ValueError(
            f"Tingkat wilayah '{key}' tidak dikenal. "
            f"Pilihannya: {', '.join(LEVEL_ORDER)}."
        )

    return level


def clean_aid(value: Any) -> str:
    """
    Membersihkan kode dari berkas **tanpa** mengubah bentuknya.

    Yang dibuang cuma spasi di kedua ujung dan tanda kutip yang ikut
    terbawa dari sebagian ekspor spreadsheet. Digit-nya tidak pernah
    disentuh: tidak di-`int()`, tidak di-`lstrip("0")`, dan tidak
    dinormalkan panjangnya.
    """

    text = str(value if value is not None else "").strip()

    # Excel lazim menuliskan sel teks sebagai '="11.01"' atau '"11.01"'
    # saat berkasnya disimpan ulang. Yang tersisa setelah ini tetap
    # string apa adanya.
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]

    return text.strip().strip('"').strip("'").strip()


def parent_aid(aid: str) -> str:
    """
    Kode induk = kode ini dikurangi satu segmen terakhir.

    `11.01.01.2002` -> `11.01.01`
    `11`            -> `""` (induknya Country, bukan wilayah)

    Ini satu-satunya cara induk ditentukan di seluruh modul import.
    """

    aid = clean_aid(aid)

    if "." not in aid:
        return ""

    return aid.rsplit(".", 1)[0]


def is_child_of(aid: str, parent: str) -> bool:
    """
    Apakah `aid` benar-benar anak langsung dari `parent`.

    Diperiksa lewat pemenggalan segmen, **bukan** `startswith`.
    `startswith` menerima `11.011` sebagai anak `11.01`, dan kekeliruan
    seperti itu justru yang paling sulit terlihat di data yang benar
    99% -nya.
    """

    return parent_aid(aid) == clean_aid(parent)


def level_for_aid(aid: str) -> GeographyLevel | None:
    """
    Menebak tingkat dari bentuk kodenya. Dipakai untuk pesan kesalahan
    yang menyebutkan tingkat apa yang sebenarnya ditulis di berkas.
    """

    aid = clean_aid(aid)

    for key in LEVEL_ORDER:
        if LEVELS[key].matches(aid):
            return LEVELS[key]

    return None
