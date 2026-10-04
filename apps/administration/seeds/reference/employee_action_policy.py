"""
Aturan pengusul bawaan per jenis Employee Action.

Matriksnya **titik awal, bukan kebijakan** — sesudah diseed seluruh
pengaturannya pindah ke layar setting, per tenant, tanpa rilis kode.
Alasan yang sama dengan matriks `seed_security_roles`: sistem tidak
boleh lumpuh di menit pertama, tapi juga tidak boleh memaksakan
struktur satu klien ke klien lain.

Yang membedakan barisnya bukan besar-kecilnya perubahan, melainkan
**siapa yang tahu duduk perkaranya**:

* Gaji, promosi, demosi, mutasi jabatan → **Kepala Departemen**. Ia
  yang menilai kinerja dan memegang anggaran departemennya. HR admin
  tidak punya dasar untuk mengusulkannya.
* Transfer antar unit → **Atasan Langsung**. Perpindahan orang
  diusulkan dari garis pelaporan, bukan dari kepala departemen tujuan.
* Pengunduran diri → **pegawainya sendiri**. Tidak ada orang lain yang
  berhak mengundurkan diri atas nama seseorang.
* Perpanjangan kontrak dan perubahan jenis kepegawaian → **role
  HR-ADMIN**. Keduanya memang administrasi kepegawaian, dan itu
  justru alasan keduanya harus disebut: selama tidak ada barisnya,
  "tidak dibatasi" berarti **siapa pun yang punya izin tambah** —
  termasuk pegawainya sendiri. Niatnya HR, tapi aturannya tidak
  pernah mengatakannya, dan di tenant peragaan hasilnya tiga dokumen
  yang Requested By-nya pegawai yang bersangkutan sendiri.
* Perubahan kontrak, probation, status, dan terminasi → **tidak
  dibatasi**. Terminasi sengaja ikut, karena keputusannya sudah
  dijaga tiga meja persetujuan dan yang menerbitkan dokumennya
  lazimnya memang HR.

Semua baris mengizinkan pengisian **atas nama** (`allow_on_behalf`):
kepala departemen yang menyampaikan usulan lewat rapat atau pesan
tetap harus bisa dilayani, asalkan namanya disebut di kolom Requested
By. Klien yang menuntut usulannya diketik sendiri tinggal mematikan
penanda itu di layar setting.
"""

from apps.administration.models import (
    ActionInitiator,
    EmployeeActionPolicy,
)


# Role pengusul untuk baris bertipe ROLE. Dicari lewat `code`, dan
# tenant yang belum punya role-nya **dilewati** — bukan dibuatkan baris
# tanpa role. `qualifies()` menolak siapa pun untuk baris ROLE yang
# rolenya kosong, jadi baris cacat begitu tidak melonggarkan aturannya
# melainkan membuat jenis action-nya tidak bisa diusulkan siapa pun.
HR_ADMIN_ROLE = "HR-ADMIN"


# (kode, jenis action, nama, tipe pengusul, kode role atau None)
POLICIES = [
    (
        "EAP-SALARY",
        "salary_change",
        "Salary Change — Department Head",
        ActionInitiator.DEPARTMENT_HEAD,
        None,
    ),
    (
        "EAP-PROMOTION",
        "promotion",
        "Promotion — Department Head",
        ActionInitiator.DEPARTMENT_HEAD,
        None,
    ),
    (
        "EAP-DEMOTION",
        "demotion",
        "Demotion — Department Head",
        ActionInitiator.DEPARTMENT_HEAD,
        None,
    ),
    (
        "EAP-POSITION",
        "position_change",
        "Position Change — Department Head",
        ActionInitiator.DEPARTMENT_HEAD,
        None,
    ),
    (
        "EAP-TRANSFER",
        "transfer",
        "Transfer — Direct Manager",
        ActionInitiator.MANAGER,
        None,
    ),
    (
        "EAP-RESIGNATION",
        "resignation",
        "Resignation — The Employee",
        ActionInitiator.EMPLOYEE,
        None,
    ),
    (
        "EAP-CONTRACT-EXT",
        "contract_extension",
        "Contract Extension — HR Admin",
        ActionInitiator.ROLE,
        HR_ADMIN_ROLE,
    ),
    (
        "EAP-EMPTYPE",
        "employment_type_change",
        "Employment Type Change — HR Admin",
        ActionInitiator.ROLE,
        HR_ADMIN_ROLE,
    ),
]


DESCRIPTION = (
    "Aturan bawaan. Kosongkan Company/Location/Employee Group berarti "
    "berlaku untuk semua — bukan tidak berlaku."
)


def seed(*, log=print) -> dict:
    from apps.accounts.models import Role

    created = 0
    updated = 0
    skipped: list[str] = []

    for order, (code, action_type, name, initiator, role_code) in enumerate(
        POLICIES,
        start=1,
    ):
        role = None

        if role_code:
            role = Role.objects.filter(
                code=role_code,
                is_deleted=False,
            ).first()

            if role is None:
                # Dilewati, bukan dibuat tanpa role — lihat catatan di
                # `HR_ADMIN_ROLE`. Dilaporkan supaya tenant yang belum
                # menjalankan `seed_security_roles` tahu apa yang
                # belum berlaku, bukan menemukannya bulan depan.
                skipped.append(
                    f"{code}: role {role_code} belum ada di tenant ini"
                )

                continue

        policy = EmployeeActionPolicy.objects.filter(
            code=code,
            is_deleted=False,
        ).first()

        values = {
            "name": name,
            "description": DESCRIPTION,
            "action_type": action_type,
            "initiator_type": initiator,
            "initiator_role": role,
            "allow_on_behalf": True,
            "sort_order": order * 10,
            "is_active": True,
        }

        if policy is None:
            EmployeeActionPolicy.objects.create(code=code, **values)

            created += 1

            log(f"  + {code} — {name}")

            continue

        # Yang sudah disunting orang **tidak** dikembalikan ke bawaan.
        # Seed ini aman diulang justru karena tidak menimpa: tenant
        # yang memindahkan usulan gaji dari Kepala Departemen ke Atasan
        # Langsung tidak boleh kehilangan keputusannya setiap kali
        # seed dijalankan lagi.
        changed = False

        for field_name in ("name", "description", "action_type"):
            if getattr(policy, field_name) != values[field_name]:
                setattr(policy, field_name, values[field_name])

                changed = True

        if changed:
            policy.save()

            updated += 1

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }
