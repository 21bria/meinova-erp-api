"""
WHERE bawaan tiap role yang di-seed — dinyatakan, bukan diturunkan.

Kenapa berkas ini ada
---------------------
Sejak Stage 4H, `Role` menjawab **WHAT** saja. Kewenangan data sebuah
penugasan dinyatakan **saat penugasan itu dibuat**, dan yang tidak
dinyatakan berakhir tertutup — tidak melihat apa pun.

Itu benar untuk keamanan dan menyusahkan untuk seed: sebelumnya seed
cukup memberi role, dan cakupannya mengikuti konfigurasi `Role` yang
kebetulan berlaku saat itu. Sekarang tiap pemberian role harus menyebut
maksudnya. Kalau tiap seed menyebutnya sendiri, delapan berkas akan
punya delapan pendapat tentang arti `HR-ADMIN`, dan yang menyimpang
adalah yang paling jarang dijalankan.

Jadi maksudnya ditulis **sekali**, di sini.

Ini **bukan** menyimpulkan cakupan dari nama role
-------------------------------------------------
Perbedaannya penting. Yang dilarang adalah menebak: melihat string
"HR-ADMIN" lalu memutuskan ia pantas se-tenant. Yang dikerjakan di sini
sebaliknya — keputusan organisasi yang **sudah** diambil dan sudah
tertulis beserta alasannya di `seed_data_scopes`, dipindahkan ke bentuk
yang bisa dipakai saat penugasan dibuat. Tenant sungguhan tidak memakai
tabel ini sama sekali; ia hanya berlaku untuk katalog role hasil seed.

Role yang **tidak** ada di sini sengaja dibiarkan tanpa kewenangan.
Pemegangnya tidak melihat apa pun lewat role itu sampai seseorang
menentukannya di layar User Role → Kewenangan. Itu arah kegagalan yang
benar: yang salah tebak melebar, dan pelebaran tidak ada yang
melaporkan.

Hubungannya dengan `Role.data_scope_*`
--------------------------------------
`seed_data_scopes` masih menulis kolom lama itu — layar Roles
menampilkannya dan perkakas cutover membacanya untuk tenant yang belum
dialihkan. Keduanya harus tetap sepakat, dan itu **diuji**
(`SeedAuthorityAgreesWithLegacyConfigTests`), bukan diharapkan.
"""

from __future__ import annotations

from apps.accounts.models import AuthorityMode, DataScopeLevel


# Meja yang datanya se-tenant. Bukan karena namanya terdengar tinggi,
# melainkan karena pekerjaannya memang lintas wilayah: HR pusat menyusun
# headcount seluruh grup, Security Admin mengatur akun siapa pun,
# Workflow Admin memperbaiki alur yang macet di mana pun.
_UNRESTRICTED = (
    "HR-ADMIN",
    "HR-MANAGER",
    "HRGA",
    "SYSTEM-ADMIN",
    "SECURITY-ADMIN",
    "WORKFLOW-ADMIN",
    "HR-ADMIN-ALL",
)

# Meja yang cakupannya **dihitung dari penempatan pemegangnya**. Inilah
# yang menghapus kebutuhan role per wilayah: yang disimpan aturannya
# ("sebatas lokasinya"), bukan nilainya ("Gebe").
_PLACEMENT = {
    "KTT": DataScopeLevel.LOCATION,
    "ADMIN-SECTION": DataScopeLevel.LOCATION,
    "ADMIN-DEPARTMENT": DataScopeLevel.LOCATION,
    "SECURITY-GATE": DataScopeLevel.LOCATION,
    "FINANCE-MANAGER": DataScopeLevel.COMPANY,
    "EXECUTIVE": DataScopeLevel.COMPANY,
}

# `HR-ADMIN-SITE`, `HR-MANAGER-SITE`, dan `EXECUTIVE-SITE` **dibuang dari
# tabel ini** bersama role-nya.
#
# Ketiganya kembaran role induknya yang bedanya cuma cakupan, dan sejak
# cakupan tidak lagi tinggal di `Role` tidak ada yang membedakannya.
# Yang hilang bersamanya kemampuan menyatakan "HR Admin sebatas
# lokasinya" **lewat kode role** — dan itu memang yang seharusnya
# hilang: kombinasi seperti itu sekarang dinyatakan pada penugasannya,
# per orang.
#
# Perhatikan bahwa tabel ini menyatakan bawaan **per role**, jadi ia
# tidak bisa memberi dua pemegang role yang sama kewenangan yang
# berbeda. Pemanggil yang memang butuh itu menyebutnya sendiri di entri
# `assign_roles()`-nya — lihat `placement_level_by_role` di
# `apps.hr.seeds.demo_org_scope`.

# Layanan mandiri. **Datanya sendiri**, bukan unitnya — itu yang
# membedakannya dari role fungsional, dan itu yang membuat baris `own`
# tidak boleh hilang. Tanpanya pegawai biasa tidak bisa membuka
# pengajuan cutinya sendiri.
_OWN = ("EMPLOYEE",)


SEED_ROLE_AUTHORITY: dict[str, dict] = {
    **{
        code: {"authority_mode": AuthorityMode.UNRESTRICTED}
        for code in _UNRESTRICTED
    },
    **{
        code: {
            "authority_mode": AuthorityMode.PLACEMENT,
            "authority_level": level,
        }
        for code, level in _PLACEMENT.items()
    },
    **{
        code: {
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [{"resource_type": "own", "resource_id": None}],
        }
        for code in _OWN
    },
}


def authority_entry(role) -> dict:
    """
    Entri untuk `assign_roles()`: `{"role": id, ...}`.

    Role di luar katalog seed dikirim sebagai id telanjang — artinya
    "tanpa kewenangan", dan pemegangnya tidak melihat apa pun lewat role
    itu sampai ada yang menentukannya. Disengaja; lihat docstring modul.
    """
    config = SEED_ROLE_AUTHORITY.get(role.code)

    if config is None:
        return {"role": role.pk}

    return {"role": role.pk, **config}


def authority_entries(roles) -> list[dict]:
    return [authority_entry(role) for role in roles]
