"""
Tujuh dimensi inti.

Barisnya **ada** walau nilainya disimpan sebagai kolom, bukan sebagai
baris dimensi. Alasannya bukan kerapian: layar Accounting Dimensions
harus memperlihatkan seluruh dimensi yang berlaku dalam satu daftar.
Kalau tujuh yang paling sering dipakai justru tidak muncul di sana,
layarnya membaca seperti daftar yang hampir kosong — dan orang yang
mencari "cost center" lalu tidak menemukannya akan menambahkannya
sebagai dimensi tambahan, sehingga satu hal punya dua tempat tinggal.

Aman diulang: `update_or_create` per kode, dan kolom yang boleh
disunting tenant (`is_required`, `sort_order`) **tidak** ikut ditimpa.
"""

from __future__ import annotations

from apps.finance.models import AccountingDimension, DimensionDataType


ORG_LOOKUP = "/api/administration/organization/lookup"


CORE_DIMENSION_SEED = [
    ("company", "Company", f"{ORG_LOOKUP}/companies/", 10),
    ("branch", "Branch", f"{ORG_LOOKUP}/branches/", 20),
    ("location", "Site", f"{ORG_LOOKUP}/locations/", 30),
    ("division", "Division", f"{ORG_LOOKUP}/divisions/", 40),
    ("department", "Department", f"{ORG_LOOKUP}/departments/", 50),
    ("section", "Section", f"{ORG_LOOKUP}/sections/", 60),
    ("cost_center", "Cost Center", f"{ORG_LOOKUP}/cost-centers/", 70),
]


def seed_dimensions() -> dict:
    created = 0
    updated = 0

    for code, name, endpoint, order in CORE_DIMENSION_SEED:
        row = AccountingDimension.objects.filter(code=code).first()

        if row is None:
            AccountingDimension.objects.create(
                code=code,
                name=name,
                data_type=DimensionDataType.REFERENCE,
                lookup_endpoint=endpoint,
                is_core=True,
                # **Tidak** wajib secara bawaan. Mewajibkan cost center
                # di setiap baris jurnal sejak menit pertama akan
                # menolak jurnal pembukaan dan jurnal kas — dua hal yang
                # memang tidak punya unit biaya.
                is_required=False,
                sort_order=order,
                # `is_deleted=False` disebut eksplisit: seed lain di
                # codebase ini pernah menghidupkan kembali baris
                # terhapus tanpa menyebutnya, dan hasilnya master yang
                # "berhasil diseed" tapi tetap kosong di dropdown.
                is_deleted=False,
            )

            created += 1

            continue

        # Yang ditimpa hanya yang **bukan** keputusan tenant. `name`,
        # `is_required`, dan `sort_order` sengaja tidak ikut: tenant
        # yang menamai dimensinya "Departemen" tidak boleh kehilangan
        # namanya tiap kali seed dijalankan ulang.
        changed = False

        for field, value in (
            ("is_core", True),
            ("data_type", DimensionDataType.REFERENCE),
            ("is_deleted", False),
        ):
            if getattr(row, field) != value:
                setattr(row, field, value)

                changed = True

        if not row.lookup_endpoint:
            row.lookup_endpoint = endpoint

            changed = True

        if changed:
            row.save()

            updated += 1

    return {"created": created, "updated": updated}
