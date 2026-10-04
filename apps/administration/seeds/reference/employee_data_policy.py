"""
Aturan kerahasiaan bawaan untuk riwayat kepegawaian.

**Bawaannya diseed, bukan dibiarkan kosong** — dan itu keputusan yang
berbeda dari mekanismenya. Mekanismenya berbunyi "tanpa baris = terlihat",
konsisten dengan seluruh sistem ini (role tanpa baris menu = tanpa
batasan): tenant yang belum mengatur apa pun tidak boleh mendadak
kehilangan tab History. Tapi membiarkan gaji terbuka sampai ada yang
sempat mengaturnya berarti kebocorannya berlaku sejak menit pertama,
di setiap tenant baru.

Jadi keamanannya datang dari **baris yang terlihat di layar setting**
dan bisa diubah, bukan dari aturan yang tertanam di kode. Bedanya nyata:
tenant yang memang ingin riwayat gajinya terbuka tinggal mematikan
barisnya, dan keputusan itu tercatat.

Dua kelompok yang dibatasi, dan yang membedakannya bukan sensitif atau
tidak, melainkan **apakah orang di sekitarnya perlu tahu untuk
bekerja**:

* **Gaji** → yang bersangkutan, atasan langsung, HR Manager. Admin site
  memasukkan absensi dan menyusun roster; tidak satu pun pekerjaan itu
  membutuhkan angka gaji rekannya.
* **Pengunduran diri & terminasi** → sama. Alasan seseorang berhenti
  lazimnya memuat hal yang tidak pernah dimaksudkan untuk dibaca satu
  kantor.
* **Dokumen** → yang bersangkutan, HR Admin, HR Manager. Yang
  mengarsipkan berkasnya perlu membukanya; rekan sedepartemennya tidak.
  Atasan langsung sengaja tidak ikut — surat peringatan sering justru
  dibuat tentang dirinya.

Yang **tidak** dibatasi: riwayat kontrak/status dan riwayat
transfer/promosi. Keduanya justru dipakai sehari-hari — admin site perlu
tahu kontrak siapa yang akan habis, dan penempatan seseorang memang
bukan rahasia dari rekan kerjanya.
"""

from apps.accounts.models import Role
from apps.administration.models import (
    EmployeeDataPolicy,
    EmployeeDataSubject,
)


# (kode, kelompok, nama, kode role yang boleh melihat, penyetelan lain)
#
# **Satu kelompok boleh punya lebih dari satu baris**, dan sejak Stage
# 3A.1 baris-baris itu benar-benar menambah: yang berlaku adalah
# gabungannya, bukan yang pertama saja. Sebelumnya baris global kedua
# tidak pernah dinilai — jadi menuliskannya di sini justru akan
# mencabut hak role di baris pertama tanpa berbunyi.
POLICIES = [
    (
        "EDP-SALARY",
        EmployeeDataSubject.HISTORY_SALARY,
        "Salary History — HR Manager, Direct Manager, Employee",
        "HR-MANAGER",
        {},
    ),
    (
        "EDP-SEPARATION",
        EmployeeDataSubject.HISTORY_SEPARATION,
        "Separation History — HR Manager, Direct Manager, Employee",
        "HR-MANAGER",
        {},
    ),

    # Menutup riwayat kenaikan gaji tidak ada gunanya kalau angka
    # gajinya sendiri terbaca di tab sebelah — dan tab Payroll adalah
    # endpoint tersendiri, jadi ia perlu barisnya sendiri.
    (
        "EDP-PAYROLL",
        EmployeeDataSubject.FIELD_PAYROLL,
        "Payroll & Salary — HR Manager, Direct Manager, Employee",
        "HR-MANAGER",
        {},
    ),

    # Meja kedua alur payroll. Ia menyatakan uangnya tersedia, dan itu
    # tidak bisa dilakukan tanpa membuka angkanya per orang.
    #
    # Baris **tersendiri**, bukan mengganti role di `EDP-PAYROLL`:
    # menggantinya berarti mencabut HR Manager. Barisnya sengaja tidak
    # menambah apa pun di luar role-nya (`allow_self` dan
    # `allow_manager` mati) — swalayan dan atasan langsung sudah
    # dinyatakan `EDP-PAYROLL`, dan menyalakannya lagi di sini cuma
    # membuat dua baris yang harus dimatikan untuk satu keputusan.
    #
    # Batas company-nya **bukan** dari baris ini: yang menjawab "orang
    # perusahaan mana" adalah cakupan data role-nya (Stage 3A), dan
    # baris ini menjawab "jenis data apa".
    (
        "EDP-PAYROLL-FINANCE",
        EmployeeDataSubject.FIELD_PAYROLL,
        "Payroll & Salary — Finance Manager",
        "FINANCE-MANAGER",
        {"allow_self": False, "allow_manager": False},
    ),

    # Nomor rekening dipakai untuk membayar orang; yang tidak membayar
    # tidak perlu membacanya.
    (
        "EDP-BANK",
        EmployeeDataSubject.FIELD_BANK,
        "Bank Accounts — HR Manager, Employee",
        "HR-MANAGER",
        {},
    ),

    # Rekam medis: **atasan pun tidak**. Ini satu-satunya kelompok yang
    # atasannya sengaja dimatikan — kondisi kesehatan bukan bahan
    # penilaian kinerja, dan tidak ada pekerjaan atasan yang
    # membutuhkannya.
    (
        "EDP-MEDICAL",
        EmployeeDataSubject.FIELD_MEDICAL,
        "Medical — HR Manager, Employee",
        "HR-MANAGER",
        {},
    ),

    # Dokumen pegawai: KTP, ijazah, kontrak, surat peringatan.
    #
    # Sampai Stage 3A.1 kelompok ini **tidak punya baris sama sekali**,
    # dan "tanpa aturan = terlihat" berarti berkasnya terbaca siapa pun
    # yang barisnya masuk cakupan. Dua baris, karena yang mengarsipkan
    # dan yang memutuskan bukan meja yang sama — dan sebelum 3A.1 dua
    # baris memang belum bisa ditulis.
    #
    # Atasan langsung **tidak** ikut: tidak ada pekerjaan atasan yang
    # membutuhkan salinan KTP atau ijazah bawahannya, dan surat
    # peringatan justru sering dibuat tentang dirinya.
    (
        "EDP-DOCUMENT-ADMIN",
        EmployeeDataSubject.FIELD_DOCUMENT,
        "Documents — HR Admin, Employee",
        "HR-ADMIN",
        {"allow_manager": False},
    ),
    (
        "EDP-DOCUMENT-MANAGER",
        EmployeeDataSubject.FIELD_DOCUMENT,
        "Documents — HR Manager",
        "HR-MANAGER",
        {"allow_self": False, "allow_manager": False},
    ),
]


# Kelompok yang atasan langsungnya **tidak** ikut boleh melihat.
# Bawaan per kelompok; tiap baris masih bisa menimpanya sendiri.
MANAGER_EXCLUDED = {
    str(EmployeeDataSubject.FIELD_BANK),
    str(EmployeeDataSubject.FIELD_MEDICAL),
    str(EmployeeDataSubject.FIELD_DOCUMENT),
}


DESCRIPTION = (
    "Aturan bawaan. Kosongkan Company/Location/Employee Group berarti "
    "berlaku untuk semua — bukan tidak berlaku."
)


def seed(*, log=print) -> dict:
    created = 0
    updated = 0

    for order, (code, subject, name, role_code, overrides) in enumerate(
        POLICIES,
        start=1,
    ):
        role = Role.objects.filter(
            code=role_code,
            is_deleted=False,
        ).first()

        if role is None:
            # Role-nya belum ada = barisnya tetap dibuat, cuma tanpa
            # role. Melewatkannya justru meninggalkan riwayat gaji
            # terbuka, dan kegagalannya tidak berbunyi di mana pun.
            log(
                f"  ! role {role_code} belum ada — {code} dibuat tanpa "
                f"role. Jalankan seed_workflows lalu ulangi."
            )

        values = {
            "name": name,
            "description": DESCRIPTION,
            "subject": str(subject),
            "allow_self": True,
            "allow_manager": str(subject) not in MANAGER_EXCLUDED,
            "manager_levels": 1,
            "allow_department_head": False,
            "role": role,
            "sort_order": order * 10,
            "is_active": True,
        }

        values.update(overrides)

        policy = EmployeeDataPolicy.objects.filter(
            code=code,
            is_deleted=False,
        ).first()

        if policy is None:
            EmployeeDataPolicy.objects.create(code=code, **values)

            created += 1

            log(f"  + {code} — {name}")

            continue

        # Yang sudah disunting orang **tidak** dikembalikan ke bawaan.
        # Seed ini aman diulang justru karena tidak menimpa: tenant
        # yang membuka riwayat gajinya untuk HR-ADMIN tidak boleh
        # kehilangan keputusannya setiap kali seed dijalankan lagi.
        #
        # Kecuali `role` yang masih kosong: itu bukan keputusan, itu
        # akibat seed dijalankan sebelum role-nya ada.
        changed = False

        for field_name in ("name", "description", "subject"):
            if getattr(policy, field_name) != values[field_name]:
                setattr(policy, field_name, values[field_name])

                changed = True

        if policy.role_id is None and role is not None:
            policy.role = role

            changed = True

        if changed:
            policy.save()

            updated += 1

    return {"created": created, "updated": updated}
