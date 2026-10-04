"""
Menutup penugasan berkewenangan kosong — sebelum runtime menutupnya.

Kenapa ini perlu padahal 0011 sudah melakukannya
------------------------------------------------
0011 mengisi kewenangan pada keadaan saat itu. Di antara 0011 dan
sekarang, penugasan baru masih bisa lahir kosong: `assign_roles()`
sengaja tidak mengisinya selama Stage 4C-4F supaya penugasan lama tetap
mengikuti konfigurasi `Role` selama transisi. Jadi tenant mana pun bisa
membawa baris kosong ke sini.

Dan di sini artinya berubah. Sebelum Stage 4G, `authority_mode` kosong
berarti "ikut `Role`" — termasuk arti lama `explicit` tanpa baris, yakni
**tanpa batasan**. Sesudah 4G, kosong berarti **tertutup**. Tanpa
migration ini, memasang 4G membuat setiap penugasan kosong kehilangan
akses mendadak tanpa satu baris pun yang menjelaskannya.

Yang dikerjakannya menuliskan keputusan itu, bukan menundanya:
penugasan kosong diturunkan dari `Role`-nya, sehingga keadaan akhirnya
**tercatat** (`unrestricted`, `placement`, atau `explicit` berisi baris)
alih-alih cuma kosong. Satu kelompok memang berubah arti, dan itu
sengaja: role `explicit` tanpa satu pun baris jadi `EXPLICIT` tanpa
baris, yakni **tanpa kewenangan**. Itulah lubang yang ditutup Stage 4G.
`audit_assignment_cutover` memperlihatkan kelompok itu satu per satu
supaya bisa diputuskan orang, bukan ditebak.

Tidak menimpa apa pun: penugasan yang `authority_mode`-nya sudah terisi
dilewati, jadi kewenangan yang disunting orang di layar User Role tetap
utuh. Aman dijalankan ulang.

Dibekukan di Stage 4J dengan alasan yang sama seperti 0011, dan
salinannya sengaja **berdiri sendiri**: migration yang mengimpor
migration lain mengikat keduanya pada satu nasib, dan yang dibekukan
justru supaya tidak ada lagi yang bisa berubah di bawahnya.
"""

from django.db import migrations


# ----------------------------------------------------------------------
# Salinan beku aturan turunan — sengaja tidak memanggil service
# ----------------------------------------------------------------------
#
# Nilai ditulis sebagai **literal**, bukan lewat `AuthorityMode` /
# `DataScopeMode`. Itu bukan kelalaian gaya: enum adalah kode yang
# hidup, dan migration harus tetap berarti sama sepuluh rilis lagi —
# termasuk sesudah enum-nya dihapus.

MODE_UNRESTRICTED = "unrestricted"
MODE_PLACEMENT = "placement"
MODE_EXPLICIT = "explicit"

LEGACY_ALL = "all"
LEGACY_OWN = "own"


def _authority_for_role(role) -> tuple[str, str]:
    """`(authority_mode, authority_level)` menurut konfigurasi lama."""
    if role.data_scope_mode == LEGACY_ALL:
        return MODE_UNRESTRICTED, ""

    if role.data_scope_mode == LEGACY_OWN:
        return MODE_PLACEMENT, role.data_scope_level or ""

    return MODE_EXPLICIT, ""


def _backfill(apps):
    """
    Mengisi kewenangan penugasan yang masih kosong, dari Role-nya.

    Idempoten: penugasan yang `authority_mode`-nya sudah terisi
    dilewati, jadi menjalankannya lagi tidak menimpa apa pun yang
    sudah disunting orang. Pada schema tenant yang baru dibuat tidak
    ada satu pun penugasan, jadi ia tidak mengerjakan apa-apa — dan
    itu justru jalur yang paling sering ditempuh.
    """
    Role = apps.get_model("accounts", "Role")
    RoleAssignment = apps.get_model("accounts", "RoleAssignment")
    RoleAssignmentAuthority = apps.get_model(
        "accounts", "RoleAssignmentAuthority")
    RoleDataPermission = apps.get_model("accounts", "RoleDataPermission")

    pending = list(
        RoleAssignment.objects.filter(authority_mode="").order_by("pk")
    )

    if not pending:
        return

    roles = {role.pk: role for role in Role.objects.all()}

    scope_rows: dict[int, set] = {}

    for role_id, resource_type, resource_id in (
        RoleDataPermission.objects
        .filter(is_deleted=False)
        .values_list("role_id", "resource_type", "resource_id")
    ):
        scope_rows.setdefault(role_id, set()).add((resource_type, resource_id))

    for assignment in pending:
        role = roles.get(assignment.role_id)

        if role is None:
            # Penugasan yatim: tidak diturunkan, dan tidak diisi
            # tebakan. Kosong berarti tertutup, dan itu jawaban yang
            # benar untuk role yang tidak ada.
            continue

        mode, level = _authority_for_role(role)

        assignment.authority_mode = mode
        assignment.authority_level = level

        assignment.save(update_fields=["authority_mode", "authority_level"])

        if mode != MODE_EXPLICIT:
            # Mode non-EXPLICIT tidak memakai baris kewenangan.
            continue

        wanted = scope_rows.get(assignment.role_id, set())

        if not wanted:
            # `EXPLICIT` tanpa baris = **tanpa kewenangan**. Tidak
            # dipetakan diam-diam jadi "tanpa batasan"; itu persis
            # lubang yang ditutup Stage 4G.
            continue

        held = set(
            RoleAssignmentAuthority.objects
            .filter(assignment_id=assignment.pk)
            .values_list("resource_type", "resource_id")
        )

        RoleAssignmentAuthority.objects.bulk_create(
            [
                RoleAssignmentAuthority(
                    assignment_id=assignment.pk,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
                for resource_type, resource_id in sorted(
                    wanted - held, key=lambda row: (row[0], row[1] or 0),
                )
            ],
            ignore_conflicts=True,
        )


def forwards(apps, schema_editor):
    _backfill(apps)


def backwards(apps, schema_editor):
    """
    Tidak mengosongkan apa pun.

    Mengosongkan kembali kolomnya akan membuka lagi jalur yang justru
    dibuang — dan pada kode 4G kosong berarti tertutup, jadi hasilnya
    bukan "kembali seperti sebelumnya" melainkan "semua orang kehilangan
    akses". Membalik ini berarti membalik 0011.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_backfill_assignment_authority'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
