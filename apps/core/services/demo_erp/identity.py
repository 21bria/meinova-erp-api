"""
Identitas & data pribadi EMP001–EMP040 (DEMO-1E, 28 Sep 2026).

**Sumber kanonik.** Tabel di bawah ditulis tangan dan dibaca apa adanya —
tidak ada acak, tidak ada jam, tidak ada PK. Sumber yang sama selalu
menghasilkan identitas yang sama.

**Fiktif dan terlihat fiktif.** Nama keluarga, alamat jalan, dan tanggal
lahir dikarang. Nomor identitas diturunkan dari nomor urut pegawai dengan
pola yang tidak mungkin milik orang sungguhan:

    NIK          99 + urut(4) + DDMMYY (perempuan: DD+40) + 0001
                 kode provinsi 99 tidak ada di Kemendagri.
    NPWP         = NIK (NPWP 16 digit penduduk = NIK, PMK 112/2022).
    BPJS Kes.    99 + 000000 + urut(5)          — 13 digit
    BPJS TK      99 + 0000 + urut(4+1)          — 11 digit
    Paspor       X99 + urut(5)                  — hanya pegawai yang bepergian
    Ponsel       +62 800-0000-1nnn  (blok 0800-0000 tidak pernah menjadi nomor ponsel)
    Kontak darurat +62 800-0000-3nnn
    Telepon rumah  +62 <kode area domisili>-0000-2nnn
    Rekening     99… sepanjang format bank (BCA/BNI/BSI 10, Mandiri 13, BRI 15)
    Surel pribadi  <nama>@mail.demo-erp.meinova.example (domain .example, RFC 2606)

**Wilayah** (provinsi/kabupaten/kecamatan/kelurahan) memakai kode
Kemendagri yang sungguh ada di master tenant, dirujuk lewat **kode**, bukan
PK. Kode yang tidak ada = blocker perencana, bukan FK karangan.

**Locality** workbook tidak menjadi kolom ERP: ia hanya memilih domisili —
pegawai site Local tinggal di Halmahera Tengah, pegawai site Non-local di
kota asalnya, pegawai HO di Jabodetabek. Semua WNI.

**Status pajak tidak diubah di sini.** `derived_tax_status` menghitung
status PTKP yang *seharusnya* dari data keluarga; PayrollAssignment tetap
TK/0 (keputusan DEMO-1E §E) sampai dampaknya pada payroll disetujui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .constants import COMPANY_EMAIL_DOMAIN, DOCUMENT_NOTE_PREFIX

PERSONAL_EMAIL_DOMAIN = f"mail.{COMPANY_EMAIL_DOMAIN}"

#: Penanda kepemilikan baris data pribadi (keluarga, rekening, pendidikan).
PERSONAL_NOTE_PREFIX = DOCUMENT_NOTE_PREFIX

NATIONALITY = "ID"

#: Kode area telepon rumah per kabupaten/kota domisili.
AREA_CODE = {
    "31.71": "21", "31.73": "21", "31.74": "21", "31.75": "21",
    "32.75": "21", "32.76": "21", "36.74": "21",
    "32.73": "22", "35.78": "31", "53.71": "380", "71.71": "431",
    "73.71": "411", "82.02": "921",
}

#: Panjang nomor rekening per bank (format umum, bukan validasi bank).
ACCOUNT_LENGTH = {"BCA": 10, "BNI": 10, "BSI": 10, "MANDIRI": 13, "BRI": 15}

#: Degree kanonik hanya AMD/SKOM/ST/SE/MT: S2 non-teknik dan S1 Hukum tidak
#: punya kode gelar di master — dibiarkan kosong, bukan dikarang.
SPOUSE, CHILD, PARENT = "SPOUSE", "CHILD", "PARENT"


@dataclass(frozen=True)
class Relative:
    relationship: str
    full_name: str
    gender: str
    birth_date: date | None = None


@dataclass(frozen=True)
class Education:
    level: str
    institution: str
    city: str
    graduation_year: int
    study_field: str | None = None
    degree: str | None = None


@dataclass(frozen=True)
class Identity:
    employee_id: str
    gender: str
    birth_place: str
    birth_date: date
    religion: str
    marital_status: str
    blood_type: str
    village: str  # kode Kemendagri kelurahan/desa; provinsi→kecamatan diturunkan
    street: str
    education: Education
    bank: str
    bank_branch: str
    relatives: tuple[Relative, ...] = field(default_factory=tuple)
    passport: bool = False

    # --- turunan -----------------------------------------------------

    @property
    def sequence(self) -> int:
        return int(self.employee_id[3:])

    @property
    def district(self) -> str:
        return self.village.rsplit(".", 1)[0]

    @property
    def city(self) -> str:
        return self.district.rsplit(".", 1)[0]

    @property
    def province(self) -> str:
        return self.city.split(".", 1)[0]

    @property
    def nik(self) -> str:
        day = self.birth_date.day + (40 if self.gender == "F" else 0)
        return (
            f"99{self.sequence:04d}"
            f"{day:02d}{self.birth_date.month:02d}{self.birth_date.year % 100:02d}"
            "0001"
        )

    @property
    def tax_number(self) -> str:
        return self.nik

    @property
    def passport_number(self) -> str:
        return f"X99{self.sequence:05d}" if self.passport else ""

    @property
    def bpjs_kesehatan(self) -> str:
        return f"99000000{self.sequence:05d}"

    @property
    def bpjs_ketenagakerjaan(self) -> str:
        return f"990000{self.sequence:05d}"

    @property
    def mobile(self) -> str:
        return f"+62 800-0000-1{self.sequence:03d}"

    @property
    def phone(self) -> str:
        return f"+62 {AREA_CODE[self.city]}-0000-2{self.sequence:03d}"

    @property
    def emergency_phone(self) -> str:
        return f"+62 800-0000-3{self.sequence:03d}"

    @property
    def emergency_contact(self) -> Relative:
        spouse = [r for r in self.relatives if r.relationship == SPOUSE]

        return spouse[0] if spouse else next(r for r in self.relatives if r.relationship == PARENT)

    @property
    def children(self) -> tuple[Relative, ...]:
        return tuple(r for r in self.relatives if r.relationship == CHILD)

    @property
    def account_number(self) -> str:
        width = ACCOUNT_LENGTH[self.bank]

        return "99" + f"{self.sequence:d}".zfill(width - 2)

    def personal_email(self, first_name: str, last_name: str) -> str:
        local = f"{first_name}.{last_name}".lower().replace(" ", "")

        return f"{local}@{PERSONAL_EMAIL_DOMAIN}"


def derived_tax_status(identity: Identity) -> str:
    """
    Status PTKP menurut data keluarga (PER-16/PJ/2016): pegawai laki-laki
    kawin = K/<anak, maks 3>; pegawai perempuan = TK/0 (tanggungannya
    melekat pada suami); belum kawin = TK/0 (tidak ada tanggungan di sini).
    **Tidak dipakai payroll** — PayrollAssignment tetap TK/0 (DEMO-1E §E).
    """
    if identity.gender == "F":
        return "TK/0"

    if identity.marital_status == "M":
        return f"K/{min(len(identity.children), 3)}"

    return f"TK/{min(len(identity.children), 3)}"


def _r(relationship, name, gender, born=None):
    return Relative(relationship, name, gender, born)


def _e(level, institution, city, year, study_field=None, degree=None):
    return Education(level, institution, city, year, study_field, degree)


# ======================================================================
# Tabel kanonik — satu baris per pegawai, urut nomor
# ======================================================================

IDENTITIES: tuple[Identity, ...] = (
    # --- HO Jakarta: GRP / MMN / MIN ------------------------------------
    Identity("EMP001", "M", "Bandung", date(1972, 3, 14), "ISLAM", "M", "O",
             "31.74.07.1009", "Jl. Gandaria Tengah III No. 18, RT 004/RW 002",
             _e("S2", "Universitas Indonesia", "Jakarta", 1999, "MANAGEMENT"),
             "BCA", "KCU Sudirman",
             (_r(SPOUSE, "Sari Pratiwi", "F", date(1975, 7, 2)),
              _r(CHILD, "Nadia Pratama", "F", date(2001, 6, 10)),
              _r(CHILD, "Rafi Pratama", "M", date(2004, 9, 2))),
             passport=True),
    Identity("EMP002", "F", "Yogyakarta", date(1976, 11, 22), "CATHOLIC", "M", "A",
             "31.74.06.1003", "Jl. Pondok Labu Raya No. 7, RT 008/RW 005",
             _e("S2", "Universitas Gadjah Mada", "Yogyakarta", 2003, "MANAGEMENT"),
             "MANDIRI", "KC Jakarta Fatmawati",
             (_r(SPOUSE, "Yohanes Sutanto", "M", date(1974, 4, 9)),
              _r(CHILD, "Clara Sutanto", "F", date(2006, 2, 18))),
             passport=True),
    Identity("EMP003", "M", "Semarang", date(1982, 5, 8), "ISLAM", "M", "B",
             "31.75.07.1004", "Jl. Pondok Kelapa Raya No. 45, RT 010/RW 007",
             _e("S1", "Universitas Diponegoro", "Semarang", 2004, "ACCOUNTING", "SE"),
             "BNI", "KC Jakarta Rawamangun",
             (_r(SPOUSE, "Rini Handayani", "F", date(1984, 2, 16)),
              _r(CHILD, "Aditya Santoso", "M", date(2011, 1, 20)),
              _r(CHILD, "Kirana Santoso", "F", date(2014, 7, 11)))),
    Identity("EMP004", "M", "Denpasar", date(1977, 8, 30), "HINDU", "M", "AB",
             "31.74.02.1003", "Jl. Karet Pedurenan No. 21, RT 003/RW 004",
             _e("S2", "Universitas Indonesia", "Jakarta", 2004, "LAW"),
             "BCA", "KCU Sudirman",
             (_r(SPOUSE, "Ni Luh Ayu Wulandari", "F", date(1980, 12, 5)),
              _r(CHILD, "Made Arya Mahendra", "M", date(2008, 4, 15))),
             passport=True),
    # --- Site Sagea: Non-local (domisili kota asal) ---------------------
    Identity("EMP005", "M", "Makassar", date(1978, 2, 12), "ISLAM", "M", "O",
             "73.71.09.1003", "Jl. Tello Baru No. 12, RT 002/RW 006",
             _e("S2", "Institut Teknologi Bandung", "Bandung", 2005, "MINING", "MT"),
             "MANDIRI", "KC Makassar Panakkukang",
             (_r(SPOUSE, "Nurul Hidayah", "F", date(1981, 9, 27)),
              _r(CHILD, "Fatimah Halim", "F", date(2005, 10, 5)),
              _r(CHILD, "Ilham Halim", "M", date(2009, 3, 21)),
              _r(CHILD, "Zahra Halim", "F", date(2013, 12, 8))),
             passport=True),
    Identity("EMP006", "M", "Bandung", date(1983, 9, 17), "ISLAM", "M", "A",
             "32.73.02.1004", "Jl. Dago Pojok No. 33, RT 005/RW 003",
             _e("S1", "Institut Teknologi Bandung", "Bandung", 2005, "MINING", "ST"),
             "BCA", "KCU Bandung Dago",
             (_r(SPOUSE, "Lia Rosmawati", "F", date(1986, 3, 3)),
              _r(CHILD, "Fikri Kurniawan", "M", date(2012, 5, 30)))),
    Identity("EMP007", "M", "Makassar", date(1984, 12, 3), "ISLAM", "M", "B",
             "73.71.10.1006", "Jl. Balang Baru No. 9, RT 001/RW 004",
             _e("S1", "Universitas Hasanuddin", "Makassar", 2006, "MINING", "ST"),
             "BRI", "KC Makassar Tamalate",
             (_r(SPOUSE, "Andi Rahmawati", "F", date(1987, 6, 19)),
              _r(CHILD, "Naufal Nurdin", "M", date(2013, 8, 14)),
              _r(CHILD, "Aisyah Nurdin", "F", date(2017, 2, 27)))),
    # --- Site Sagea: Local (domisili Halmahera Tengah) -------------------
    Identity("EMP008", "M", "Weda", date(1988, 6, 21), "PROTESTANT", "M", "O",
             "82.02.04.2002", "Jl. Trans Halmahera, Desa Sagea, RT 002/RW 001",
             _e("D3", "Politeknik Negeri Ambon", "Ambon", 2009, "MINING", "AMD"),
             "BRI", "BRI Unit Weda",
             (_r(SPOUSE, "Yuliana Tawulo", "F", date(1990, 1, 11)),
              _r(CHILD, "Kezia Tawulo", "F", date(2016, 9, 9)))),
    Identity("EMP009", "M", "Ternate", date(1996, 4, 11), "PROTESTANT", "S", "A",
             "82.02.07.2004", "Jl. Kobe Pantai, Desa Kobe, RT 003/RW 001",
             _e("SMA", "SMA Negeri 1 Halmahera Tengah", "Weda", 2014),
             "BRI", "BRI Unit Weda",
             (_r(PARENT, "Yohana Gabi", "F"),)),
    Identity("EMP010", "M", "Weda", date(1994, 10, 27), "PROTESTANT", "M", "O",
             "82.02.01.2022", "Jl. Nurweda No. 4, RT 001/RW 002",
             _e("SMA", "SMA Negeri 1 Halmahera Tengah", "Weda", 2012),
             "BRI", "BRI Unit Weda",
             (_r(SPOUSE, "Ester Sani", "F", date(1996, 8, 3)),
              _r(CHILD, "Yosua Sani", "M", date(2021, 5, 16)))),
    Identity("EMP011", "M", "Manado", date(1993, 1, 19), "PROTESTANT", "S", "B",
             "71.71.04.1006", "Jl. Sam Ratulangi Lorong 5 No. 2, RT 004/RW 002",
             _e("S1", "Universitas Sam Ratulangi", "Manado", 2015, "GEOLOGY", "ST"),
             "BCA", "KCU Manado",
             (_r(PARENT, "Hendra Wijaya", "M"),)),
    Identity("EMP012", "M", "Tobelo", date(1999, 7, 5), "PROTESTANT", "S", "O",
             "82.02.04.2001", "Jl. Gemaf No. 11, RT 001/RW 001",
             _e("SMA", "SMA Negeri 2 Halmahera Tengah", "Weda", 2017),
             "BRI", "BRI Unit Weda",
             (_r(PARENT, "Agustina Lema", "F"),)),
    Identity("EMP013", "F", "Soasio", date(1989, 2, 25), "CATHOLIC", "M", "A",
             "82.02.01.2023", "Jl. Wedana No. 16, RT 002/RW 003",
             _e("S1", "Universitas Khairun", "Ternate", 2011, "MANAGEMENT", "SE"),
             "BNI", "KCP Weda",
             (_r(SPOUSE, "Paulus Wadu", "M", date(1987, 5, 14)),
              _r(CHILD, "Maria Wadu", "F", date(2018, 3, 3)))),
    Identity("EMP014", "F", "Larantuka", date(1998, 12, 12), "CATHOLIC", "S", "B",
             "82.02.05.2002", "Jl. Sosowomo No. 3, RT 001/RW 002",
             _e("D3", "Universitas Khairun", "Ternate", 2019, "MANAGEMENT", "AMD"),
             "BRI", "BRI Unit Weda",
             (_r(PARENT, "Theresia Kleden", "F"),)),
    Identity("EMP015", "M", "Surabaya", date(1985, 3, 28), "ISLAM", "M", "AB",
             "35.78.08.1004", "Jl. Kertajaya Indah Timur No. 27, RT 006/RW 008",
             _e("S1", "Institut Teknologi Sepuluh Nopember", "Surabaya", 2007, "CIVIL", "ST"),
             "MANDIRI", "KC Surabaya Kertajaya",
             (_r(SPOUSE, "Dian Puspitasari", "F", date(1988, 10, 7)),
              _r(CHILD, "Arkan Ananta", "M", date(2015, 11, 11)))),
    Identity("EMP016", "M", "Weda", date(1995, 8, 8), "PROTESTANT", "M", "O",
             "82.02.07.2002", "Jl. Lelilef Sawai No. 8, RT 002/RW 001",
             _e("D3", "Universitas Khairun", "Ternate", 2016, "MINING", "AMD"),
             "BRI", "BRI Unit Weda",
             (_r(SPOUSE, "Debora Meko", "F", date(1997, 12, 1)),)),
    # --- HO Jakarta: MMN / MIN ------------------------------------------
    Identity("EMP017", "F", "Bogor", date(1993, 5, 14), "ISLAM", "M", "A",
             "32.76.06.1002", "Jl. Kukusan Raya No. 52, RT 003/RW 006",
             _e("S1", "Universitas Padjadjaran", "Bandung", 2015, "MANAGEMENT", "SE"),
             "BCA", "KCP Depok Margonda",
             (_r(SPOUSE, "Hendra Saputra", "M", date(1991, 7, 23)),
              _r(CHILD, "Alya Saputri", "F", date(2022, 1, 9)))),
    Identity("EMP018", "M", "Surakarta", date(1981, 10, 2), "ISLAM", "M", "B",
             "36.74.03.1010", "Jl. Jurangmangu Barat No. 14, RT 005/RW 002",
             _e("S1", "Universitas Sebelas Maret", "Surakarta", 2003, "MANAGEMENT", "SE"),
             "BCA", "KCP Bintaro Jaya",
             (_r(SPOUSE, "Wulan Sari", "F", date(1983, 1, 28)),
              _r(CHILD, "Dimas Setiawan", "M", date(2010, 6, 6)),
              _r(CHILD, "Laras Setiawan", "F", date(2013, 9, 19)))),
    Identity("EMP019", "F", "Medan", date(1984, 7, 23), "BUDDHA", "M", "O",
             "31.73.05.1006", "Jl. Kedoya Raya No. 88, RT 007/RW 004",
             _e("S1", "Institut Teknologi Bandung", "Bandung", 2006, "MECHANICAL", "ST"),
             "BCA", "KCP Kebon Jeruk",
             (_r(SPOUSE, "Hendrik Tanoto", "M", date(1982, 11, 30)),
              _r(CHILD, "Jessica Tanoto", "F", date(2014, 4, 4)))),
    Identity("EMP020", "F", "Padang", date(1986, 1, 30), "ISLAM", "M", "A",
             "31.74.04.1006", "Jl. Pejaten Barat No. 19, RT 002/RW 007",
             _e("S1", "Universitas Andalas", "Padang", 2008, "MANAGEMENT", "SE"),
             "MANDIRI", "KC Jakarta Pasar Minggu",
             (_r(SPOUSE, "Rudi Hartanto", "M", date(1984, 8, 12)),
              _r(CHILD, "Nayla Hartanto", "F", date(2016, 8, 18)))),
    Identity("EMP021", "M", "Jakarta", date(1999, 3, 9), "CATHOLIC", "S", "B",
             "32.75.04.1001", "Jl. Pekayon Raya No. 6, RT 004/RW 011",
             _e("D3", "Politeknik Negeri Jakarta", "Depok", 2020, "MECHANICAL", "AMD"),
             "BNI", "KCP Bekasi Pekayon",
             (_r(PARENT, "Yulia Saputra", "F"),)),
    Identity("EMP022", "F", "Surabaya", date(2000, 9, 15), "PROTESTANT", "S", "O",
             "31.73.02.1002", "Jl. Tanjung Duren Barat II No. 3, RT 009/RW 005",
             _e("S1", "Universitas Tarumanagara", "Jakarta", 2022, "ACCOUNTING", "SE"),
             "BCA", "KCP Tanjung Duren",
             (_r(PARENT, "Budi Hartono", "M"),)),
    # --- Site Sagea: campuran ------------------------------------------
    Identity("EMP023", "M", "Kupang", date(1991, 11, 4), "CATHOLIC", "M", "A",
             "53.71.04.1010", "Jl. Liliba No. 21, RT 012/RW 004",
             _e("S1", "Universitas Nusa Cendana", "Kupang", 2014, "GEOLOGY", "ST"),
             "BRI", "KC Kupang",
             (_r(SPOUSE, "Magdalena Neno", "F", date(1993, 6, 6)),
              _r(CHILD, "Kristo Neno", "M", date(2019, 12, 25)))),
    Identity("EMP024", "M", "Weda", date(1997, 2, 14), "CATHOLIC", "S", "O",
             "82.02.04.2003", "Jl. Fritu No. 5, RT 001/RW 001",
             _e("SMA", "SMA Negeri 1 Halmahera Tengah", "Weda", 2015),
             "BRI", "BRI Unit Weda",
             (_r(PARENT, "Martha Leki", "F"),)),
    Identity("EMP025", "M", "Tobelo", date(1995, 5, 20), "PROTESTANT", "M", "B",
             "82.02.01.2021", "Jl. Sidanga No. 10, RT 002/RW 001",
             _e("SMA", "SMA Negeri 2 Halmahera Tengah", "Weda", 2013),
             "BRI", "BRI Unit Weda",
             (_r(SPOUSE, "Ribka Dula", "F", date(1997, 4, 22)),
              _r(CHILD, "Natan Dula", "M", date(2020, 10, 10)),
              _r(CHILD, "Grace Dula", "F", date(2023, 3, 15)))),
    Identity("EMP026", "M", "Larantuka", date(1990, 9, 1), "CATHOLIC", "M", "A",
             "82.02.09.2001", "Jl. Dotte No. 2, RT 001/RW 001",
             _e("SMA", "SMA Negeri 1 Larantuka", "Larantuka", 2008),
             "BRI", "BRI Unit Weda",
             (_r(SPOUSE, "Veronika Koten", "F", date(1992, 2, 2)),
              _r(CHILD, "Benediktus Koten", "M", date(2016, 6, 29)),
              _r(CHILD, "Angela Koten", "F", date(2019, 1, 12)),
              _r(CHILD, "Paskalis Koten", "M", date(2022, 4, 17)))),
    Identity("EMP027", "M", "Maumere", date(2000, 8, 28), "CATHOLIC", "S", "O",
             "82.02.07.2003", "Jl. Sawai Itepo No. 7, RT 001/RW 002",
             _e("SMA", "SMA Negeri 1 Halmahera Tengah", "Weda", 2018),
             "BRI", "BRI Unit Weda",
             (_r(PARENT, "Yosefina Lado", "F"),)),
    Identity("EMP028", "M", "Weda", date(2001, 12, 6), "PROTESTANT", "S", "B",
             "82.02.04.2004", "Jl. Waleh No. 13, RT 002/RW 001",
             _e("SMA", "SMA Negeri 2 Halmahera Tengah", "Weda", 2019),
             "BRI", "BRI Unit Weda",
             (_r(PARENT, "Yakob Bere", "M"),)),
    # --- HO Jakarta: staf -----------------------------------------------
    Identity("EMP029", "F", "Jakarta", date(1994, 6, 26), "ISLAM", "M", "A",
             "31.74.01.1001", "Jl. Tebet Timur Dalam VI No. 11, RT 006/RW 010",
             _e("S1", "Universitas Indonesia", "Depok", 2016, "ACCOUNTING", "SE"),
             "MANDIRI", "KC Jakarta Tebet",
             (_r(SPOUSE, "Fahmi Ramadhan", "M", date(1992, 3, 17)),)),
    Identity("EMP030", "M", "Cirebon", date(1998, 4, 4), "ISLAM", "S", "O",
             "32.76.05.1001", "Jl. Sukmajaya Raya No. 29, RT 002/RW 012",
             _e("S1", "Universitas Gunadarma", "Depok", 2020, "ACCOUNTING", "SE"),
             "BNI", "KCP Depok",
             (_r(PARENT, "Suharti", "F"),)),
    Identity("EMP031", "F", "Tegal", date(1999, 10, 18), "ISLAM", "S", "B",
             "31.75.09.1002", "Jl. Cibubur Indah No. 17, RT 003/RW 004",
             _e("S1", "Universitas Negeri Jakarta", "Jakarta", 2021, "MANAGEMENT", "SE"),
             "BSI", "KCP Cibubur",
             (_r(PARENT, "Rahmat Hidayat", "M"),)),
    Identity("EMP032", "M", "Malang", date(1992, 2, 2), "ISLAM", "M", "O",
             "36.74.04.1006", "Jl. Jombang Raya No. 40, RT 001/RW 003",
             _e("S1", "Universitas Brawijaya", "Malang", 2014, "MANAGEMENT", "SE"),
             "BRI", "KC Ciputat",
             (_r(SPOUSE, "Anggun Lestari", "F", date(1994, 9, 9)),
              _r(CHILD, "Raka Prakoso", "M", date(2021, 7, 7)))),
    Identity("EMP033", "F", "Jakarta", date(2001, 1, 25), "ISLAM", "S", "A",
             "32.75.09.1002", "Jl. Jatiasih Raya No. 22, RT 005/RW 001",
             _e("D3", "Politeknik Negeri Jakarta", "Depok", 2021, "MANAGEMENT", "AMD"),
             "BCA", "KCP Jatiasih",
             (_r(PARENT, "Sri Wahyuni", "F"),)),
    Identity("EMP034", "M", "Jakarta", date(1990, 12, 10), "CATHOLIC", "M", "B",
             "31.74.03.1004", "Jl. Tegal Parang Utara No. 5, RT 008/RW 002",
             _e("S1", "Universitas Katolik Parahyangan", "Bandung", 2012, "LAW"),
             "BCA", "KCP Mampang",
             (_r(SPOUSE, "Stefani Kurnia", "F", date(1992, 5, 5)),
              _r(CHILD, "Nathan Gunawan", "M", date(2020, 2, 20)))),
    Identity("EMP035", "F", "Bekasi", date(2000, 5, 5), "ISLAM", "S", "O",
             "31.75.03.1005", "Jl. Cipinang Cempedak IV No. 9, RT 010/RW 003",
             _e("S1", "Universitas Trisakti", "Jakarta", 2022, "LAW"),
             "MANDIRI", "KC Jakarta Jatinegara",
             (_r(PARENT, "Nurhayati", "F"),)),
    Identity("EMP036", "M", "Pontianak", date(1991, 8, 19), "BUDDHA", "M", "A",
             "31.73.08.1003", "Jl. Meruya Selatan No. 36, RT 004/RW 006",
             _e("S1", "Universitas Trisakti", "Jakarta", 2013, "MECHANICAL", "ST"),
             "BCA", "KCP Meruya",
             (_r(SPOUSE, "Melisa Tan", "F", date(1993, 10, 30)),
              _r(CHILD, "Kenzo Wijaya", "M", date(2019, 5, 25)))),
    Identity("EMP037", "F", "Manado", date(1997, 12, 24), "PROTESTANT", "S", "B",
             "36.74.01.1004", "Jl. Lengkong Gudang Timur No. 15, RT 002/RW 005",
             _e("S1", "Universitas Pelita Harapan", "Tangerang", 2019, "MANAGEMENT", "SE"),
             "BCA", "KCP Serpong",
             (_r(PARENT, "Johny Rumengan", "M"),)),
    Identity("EMP038", "M", "Palembang", date(1983, 4, 17), "ISLAM", "M", "O",
             "31.74.10.1002", "Jl. Bintaro Permai No. 31, RT 003/RW 009",
             _e("S1", "Universitas Sriwijaya", "Palembang", 2005, "ACCOUNTING", "SE"),
             "MANDIRI", "KC Jakarta Bintaro",
             (_r(SPOUSE, "Ayu Kartika", "F", date(1985, 7, 21)),
              _r(CHILD, "Farel Mahardika", "M", date(2012, 10, 1)),
              _r(CHILD, "Salsabila Mahardika", "F", date(2016, 1, 14)))),
    Identity("EMP039", "F", "Jakarta", date(1996, 3, 3), "BUDDHA", "S", "AB",
             "31.73.07.1005", "Jl. Kemanggisan Ilir No. 20, RT 006/RW 008",
             _e("S1", "Universitas Bina Nusantara", "Jakarta", 2018, "ACCOUNTING", "SE"),
             "BCA", "KCP Kemanggisan",
             (_r(PARENT, "Susanto Halim", "M"),)),
    Identity("EMP040", "F", "Bandung", date(1980, 10, 11), "ISLAM", "M", "B",
             "31.75.01.1002", "Jl. Utan Kayu Raya No. 64, RT 007/RW 002",
             _e("S2", "Universitas Padjadjaran", "Bandung", 2008, "MANAGEMENT"),
             "BNI", "KC Jakarta Rawamangun",
             (_r(SPOUSE, "Agus Permadi", "M", date(1978, 6, 1)),
              _r(CHILD, "Bayu Permadi", "M", date(2007, 3, 30)),
              _r(CHILD, "Citra Permadi", "F", date(2010, 11, 22)))),
)

BY_EMPLOYEE = {identity.employee_id: identity for identity in IDENTITIES}


def reference_codes() -> dict[str, set[str]]:
    """Seluruh kode master yang dirujuk tabel — untuk pemeriksaan perencana."""
    codes: dict[str, set[str]] = {
        "Gender": set(), "Religion": set(), "MaritalStatus": set(), "BloodType": set(),
        "Nationality": {NATIONALITY}, "Province": set(), "City": set(), "District": set(),
        "Village": set(), "Bank": set(), "FamilyRelationship": set(), "Education": set(),
        "Degree": set(), "StudyField": set(),
    }

    for i in IDENTITIES:
        codes["Gender"] |= {i.gender} | {r.gender for r in i.relatives}
        codes["Religion"].add(i.religion)
        codes["MaritalStatus"].add(i.marital_status)
        codes["BloodType"].add(i.blood_type)
        codes["Province"].add(i.province)
        codes["City"].add(i.city)
        codes["District"].add(i.district)
        codes["Village"].add(i.village)
        codes["Bank"].add(i.bank)
        codes["FamilyRelationship"] |= {r.relationship for r in i.relatives}
        codes["Education"].add(i.education.level)
        codes["Degree"] |= {i.education.degree} - {None}
        codes["StudyField"] |= {i.education.study_field} - {None}

    return codes
