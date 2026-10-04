"""
Mengisi kewenangan tiap penugasan dari konfigurasi Role yang lama.

**Nol perubahan perilaku.** Yang membaca kewenangan saat migration ini
ditulis masih `DataScopeService` lewat `Role`/`RoleDataPermission`;
kolom yang diisi di sini belum dibaca siapa pun sampai Stage 4D.

Dibekukan di Stage 4J
---------------------
Versi sebelumnya memanggil `apps.accounts.services.authority_backfill`,
yang mengimpor model **nyata**. Docstring aslinya sudah menyebut syarat
ini: "kalau model-modelnya nanti berubah bentuk, migration ini harus
dibekukan jadi salinan statis." Syaratnya sekarang terpenuhi — gelombang
C akan menghapus `RoleDataPermission` dan `Role.data_scope_*`.

Yang membuatnya mendesak bukan sejarah, melainkan **tenant baru**:
`django-tenants` memutar ulang seluruh rantai migration untuk setiap
schema tenant yang dibuat. Jadi sesudah modelnya dihapus, migration yang
mengimpor service akan menggagalkan **pembuatan tenant**, bukan sekadar
pemutaran ulang riwayat. Kegagalannya pun muncul di tempat yang jauh
dari sebabnya.

Sekarang seluruhnya memakai `apps.get_model()` — model historis, yang
tetap ada di state migration ini sesudah model nyatanya dihapus — dan
nilai enum ditulis sebagai literal.

Balikannya: mengosongkan kembali kolom dan membuang baris kewenangan —
tidak ada data lama yang hilang karena tidak ada data lama yang
disentuh.
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
    RoleAssignment = apps.get_model("accounts", "RoleAssignment")
    RoleAssignmentAuthority = apps.get_model(
        "accounts", "RoleAssignmentAuthority")

    RoleAssignmentAuthority.objects.all().delete()

    RoleAssignment.objects.update(authority_mode="", authority_level="")


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_roleassignment_authority_level_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
