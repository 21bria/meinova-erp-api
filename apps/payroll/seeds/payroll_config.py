"""
Konfigurasi payroll di atas master existing.

Dipisah dari `seed_payroll` dan **tidak** ikut dipanggil olehnya. Isinya
angka uang, dan menyiramkannya ke master milik tenant yang sudah
berjalan adalah perubahan yang tidak diminta siapa pun:

    python manage.py tenant_command seed_payroll_config --schema=demo
    python manage.py tenant_command seed_payroll_config --schema=demo \
        --with-components

**Dua kelompok, dan pemisahannya disengaja.**

*Bawaan* hanya menyeed yang sumbernya **peraturan**, bukan kebijakan
perusahaan: PTKP (PMK 101/2016) dan lapisan tarif PPh21 (UU HPP
7/2021 Pasal 17). Angka itu sama untuk semua tenant, dan tenant yang
belum mengisinya lebih baik memakainya daripada nol.

*`--with-components`* menyeed contoh komponen tunjangan dan potongan.
Nominalnya **bukan aturan perusahaan mana pun** — ia data peragaan
supaya mesin hitung punya sesuatu untuk dihitung dan hasilnya bisa
dicocokkan manual. Berapa tunjangan transport, iuran apa saja yang
dipotong, dan berapa plafonnya adalah keputusan tiap perusahaan, dan
menyeednya sebagai bawaan membuat angka karangan terbaca seperti
kebijakan yang sudah disetujui. Lihat "BUSINESS DECISION REQUIRED" di
`docs/claude/payroll.md`.

Seluruhnya **non-destruktif**: baris yang sudah ada tidak ditimpa
nilainya. Yang mengubah angka tetap orang lewat layarnya, dan seed yang
dijalankan ulang tidak mengembalikannya ke bawaan.
"""

from decimal import Decimal

from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    DeductionTemplate,
    DeductionTemplateLine,
    PayrollBasis,
    PayrollTaxBracket,
    TaxStatus,
)


# PTKP tahunan (PMK 101/2016). Diisi **hanya kalau masih nol** — tenant
# yang sudah menyetel sendiri tidak dikembalikan ke bawaan.
PTKP = {
    "TK/0": "54000000",
    "TK/1": "58500000",
    "TK/2": "63000000",
    "TK/3": "67500000",
    "K/0": "58500000",
    "K/1": "63000000",
    "K/2": "67500000",
    "K/3": "72000000",
}


# Lapisan tarif PPh21 progresif, dalam rupiah **setahun**
# (UU HPP 7/2021 Pasal 17).
TAX_BRACKETS = [
    (1, "0", "60000000", "5"),
    (2, "60000000", "250000000", "15"),
    (3, "250000000", "500000000", "25"),
    (4, "500000000", "5000000000", "30"),
    (5, "5000000000", None, "35"),
]


# Komponen tunjangan per paket. Paketnya sendiri (`AllowanceTemplate`)
# sudah ada dan tidak disentuh — yang ditambah cuma isinya.
#
# **Nominalnya data peragaan, bukan kebijakan.** Ia ada supaya mesin
# hitung punya sesuatu untuk dihitung dan hasilnya bisa dicocokkan
# manual. Hanya diseed lewat `--with-components`.
ALLOWANCE_COMPONENTS = {
    "STANDARD": [
        {
            "code": "TRANSPORT",
            "name": "Tunjangan Transport",
            "sequence": 10,
            "basis": PayrollBasis.PER_ATTENDANCE_DAY,
            "amount": "25000",
            "is_taxable": True,
            "is_prorated": False,
        },
        {
            "code": "MEAL",
            "name": "Tunjangan Makan",
            "sequence": 20,
            "basis": PayrollBasis.PER_ATTENDANCE_DAY,
            "amount": "30000",
            "is_taxable": True,
            "is_prorated": False,
        },
    ],
    "STAFF": [
        {
            "code": "TRANSPORT",
            "name": "Tunjangan Transport",
            "sequence": 10,
            "basis": PayrollBasis.PER_ATTENDANCE_DAY,
            "amount": "35000",
            "is_taxable": True,
            "is_prorated": False,
        },
        {
            "code": "POSITION",
            "name": "Tunjangan Jabatan",
            "sequence": 20,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "10",
            "is_taxable": True,
            "is_prorated": True,
        },
    ],
    "SUPERVISOR": [
        {
            "code": "POSITION",
            "name": "Tunjangan Jabatan",
            "sequence": 10,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "20",
            "is_taxable": True,
            "is_prorated": True,
        },
        {
            "code": "COMM",
            "name": "Tunjangan Komunikasi",
            "sequence": 20,
            "basis": PayrollBasis.FIXED,
            "amount": "500000",
            "is_taxable": True,
            "is_prorated": True,
        },
    ],
}


# Komponen potongan. `maximum_base` adalah bentuk plafon BPJS —
# batas **dasar** perhitungan, bukan batas hasilnya.
#
# **Persentase dan plafonnya data peragaan.** Iuran mana yang dipotong
# dari pegawai, berapa persen, dan berapa plafon dasarnya berbeda per
# perusahaan dan per tahun. Hanya diseed lewat `--with-components`.
DEDUCTION_COMPONENTS = {
    "STANDARD": [
        {
            "code": "BPJS-KES",
            "name": "BPJS Kesehatan (Pegawai 1%)",
            "sequence": 10,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "1",
            "maximum_base": "12000000",
            "reduces_taxable": True,
        },
        {
            "code": "BPJS-JHT",
            "name": "BPJS JHT (Pegawai 2%)",
            "sequence": 20,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "2",
            "reduces_taxable": True,
        },
        # Porsi **perusahaan**. Diseed supaya kartu Beban Perusahaan
        # dan Total Biaya Payroll punya angka di data peragaan —
        # kartu yang selalu nol terbaca sebagai "perusahaan tidak
        # menanggung apa-apa", bukan sebagai "belum dikonfigurasi".
        # Persentasenya tetap **data peragaan**, sama seperti porsi
        # pegawai di atasnya.
        {
            "code": "BPJS-JHT-ER",
            "name": "BPJS JHT (Perusahaan 3,7%)",
            "sequence": 30,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "3.7",
            "is_employer_cost": True,
        },
        {
            "code": "BPJS-KES-ER",
            "name": "BPJS Kesehatan (Perusahaan 4%)",
            "sequence": 40,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "4",
            "maximum_base": "12000000",
            "is_employer_cost": True,
        },
        {
            "code": "PPH21",
            "name": "PPh 21",
            "sequence": 90,
            "basis": PayrollBasis.PPH21_PROGRESSIVE,
        },
    ],
    "OUTSOURCE": [
        {
            "code": "BPJS-KES",
            "name": "BPJS Kesehatan (Pegawai 1%)",
            "sequence": 10,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": "1",
            "maximum_base": "12000000",
            "reduces_taxable": True,
        },
    ],
}


def seed_ptkp() -> int:
    """PTKP tahunan, hanya untuk baris yang nilainya masih nol."""
    filled = 0

    for code, amount in PTKP.items():
        updated = (
            TaxStatus.objects
            .filter(code=code, is_deleted=False, non_taxable_income=0)
            .update(non_taxable_income=Decimal(amount))
        )

        filled += updated

    return filled


def seed_tax_brackets() -> int:
    created = 0

    for sequence, income_from, income_to, rate in TAX_BRACKETS:
        _, was_created = PayrollTaxBracket.objects.get_or_create(
            sequence=sequence,
            is_deleted=False,
            defaults={
                "income_from": Decimal(income_from),
                "income_to": (
                    Decimal(income_to) if income_to is not None else None
                ),
                "rate": Decimal(rate),
                "is_active": True,
            },
        )

        created += int(was_created)

    return created


def _seed_lines(*, template_model, line_model, mapping) -> int:
    created = 0

    for template_code, rows in mapping.items():
        template = (
            template_model.objects
            .filter(code=template_code, is_deleted=False)
            .first()
        )

        if template is None:
            continue

        for row in rows:
            payload = dict(row)
            code = payload.pop("code")

            defaults = {
                key: (
                    Decimal(value)
                    if key in {
                        "amount", "rate", "minimum_amount",
                        "maximum_amount", "minimum_base", "maximum_base",
                    }
                    else value
                )
                for key, value in payload.items()
            }
            defaults["is_active"] = True

            _, was_created = line_model.objects.get_or_create(
                template=template,
                code=code,
                is_deleted=False,
                defaults=defaults,
            )

            created += int(was_created)

    return created


def seed_allowance_components() -> int:
    return _seed_lines(
        template_model=AllowanceTemplate,
        line_model=AllowanceTemplateLine,
        mapping=ALLOWANCE_COMPONENTS,
    )


def seed_deduction_components() -> int:
    return _seed_lines(
        template_model=DeductionTemplate,
        line_model=DeductionTemplateLine,
        mapping=DEDUCTION_COMPONENTS,
    )


def seed_payroll_config(*, with_components: bool = False) -> dict:
    result = {
        "ptkp": seed_ptkp(),
        "tax_brackets": seed_tax_brackets(),
        "allowance_components": 0,
        "deduction_components": 0,
    }

    if with_components:
        result["allowance_components"] = seed_allowance_components()
        result["deduction_components"] = seed_deduction_components()

    return result
