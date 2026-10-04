"""
Katalog role dibersihkan: empat role `*-SITE` dikonsolidasikan/di-rename.

**Kenapa sekarang, dan kenapa ini aman.**

Role `*-SITE` lahir waktu WHERE masih tinggal di `Role`. Bedanya dengan
kembarannya memang **cuma cakupan**: `HR-ADMIN-SITE` dan `HR-ADMIN`
punya daftar izin yang sama persis, begitu juga `HR-MANAGER-SITE` dan
`EXECUTIVE-SITE`. Yang membedakannya kolom `data_scope_*` — dan kolom itu
sudah tidak ada. Jadi sesudah gelombang C keduanya **tidak bisa
dibedakan sama sekali**: dua baris di layar Roles yang berarti hal yang
persis sama, dan pilihan di antara keduanya harus ditebak orang.

**Kewenangan tidak perlu dipindahkan, dan itu intinya.** WHERE menempel
pada `RoleAssignment`, bukan pada `Role`. Jadi memindahkan penugasan ke
role target cuma mengganti `role_id`-nya: `authority_mode`,
`authority_level`, dan seluruh baris `RoleAssignmentAuthority` ikut apa
adanya karena semuanya menggantung di penugasan itu, bukan di role-nya.
Nol baris kewenangan ditulis, nol dihapus, nol ditafsirkan ulang.

Kalau konsolidasi ini dikerjakan **sebelum** gelombang C, ia justru
mustahil dilakukan dengan aman: cakupan pemegang `HR-ADMIN-SITE`
diturunkan dari role-nya, jadi memindahkannya ke `HR-ADMIN` — yang
cakupan lamanya "seluruh data" — akan **melebarkan** akses orang itu ke
seluruh tenant. Urutannya bukan kebetulan.

**Izin tidak disentuh.** Kalau role sumber ternyata punya izin yang
tidak dimiliki target, izin itu **tidak** ditambahkan: menambahkannya
melebarkan WHAT untuk **seluruh** pemegang target, bukan cuma yang
dipindahkan. Kasus itu dilaporkan, bukan ditambal.

**Bentrokan ditinggalkan, tidak ditebak.** Kalau seseorang memegang role
sumber **dan** targetnya sekaligus, penugasannya tidak dipindahkan:
`UNIQUE(user, role)` menolak barisnya, dan menggabungkan kewenangan
keduanya berarti memilih salah satu kewenangan atau menggabungkannya —
yang pertama membuang pembatasan yang sengaja dipasang, yang kedua
melebarkan akses. Keduanya keputusan orang. Penugasan sumbernya
dibiarkan utuh **dan role sumbernya tetap aktif**, supaya tidak ada yang
kehilangan akses tanpa ada yang memutuskannya.

Idempoten: sesudah dijalankan, role sumbernya sudah tidak ada lagi, jadi
pemutaran kedua tidak mengerjakan apa pun. Pada schema tenant yang baru
dibuat role itu tidak pernah ada sejak awal — dan itu jalur yang paling
sering ditempuh, karena `django-tenants` memutar ulang seluruh rantai
untuk tiap tenant baru.

Tidak mengimpor satu pun kode aplikasi (pelajaran Stage 4J): seluruhnya
`apps.get_model()`, nilai sebagai literal.
"""

from django.db import migrations


# (kode sumber, kode target) — sumber dipindahkan lalu dinonaktifkan.
CONSOLIDATE = (
    ("EXECUTIVE-SITE", "EXECUTIVE"),
    ("HR-ADMIN-SITE", "HR-ADMIN"),
    ("HR-MANAGER-SITE", "HR-MANAGER"),
)

# (kode lama, kode baru, nama baru) — satu baris `Role` yang sama,
# cuma kodenya berganti. Seluruh FK yang menunjuknya — termasuk
# `WorkflowStep.approver_role` — tetap utuh karena yang berubah bukan
# barisnya melainkan isi kolomnya.
RENAME = (
    ("KTT-SITE", "KTT", "Kepala Teknik Tambang"),
)

# Nama yang masih menjanjikan cakupan padahal cakupan tidak lagi tinggal
# di `Role`. Dibetulkan bersama konsolidasinya: sesudah `EXECUTIVE`
# memegang penugasan bercakupan company **dan** lokasi, nama yang
# menyebut salah satunya menyesatkan.
RELABEL = (
    ("EXECUTIVE", "Executive"),
)


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RoleAssignment = apps.get_model("accounts", "RoleAssignment")

    # ------------------------------------------------------------------
    # 1. Rename — satu baris, kode baru
    # ------------------------------------------------------------------

    for old_code, new_code, new_name in RENAME:
        source = Role.objects.filter(code=old_code).first()

        if source is None:
            continue

        if Role.objects.filter(code=new_code, is_deleted=False).exists():
            # Kode barunya sudah dipakai role lain. Tidak ditimpa dan
            # tidak digabung diam-diam — `UNIQUE(code) WHERE NOT
            # is_deleted` memang menolaknya, dan menebak mana yang
            # dimaksud bukan urusan migration.
            continue

        source.code = new_code
        source.name = new_name

        source.save(update_fields=["code", "name", "updated_at"])

    # ------------------------------------------------------------------
    # 2. Konsolidasi — penugasan dipindahkan, kewenangannya ikut
    # ------------------------------------------------------------------

    for source_code, target_code in CONSOLIDATE:
        source = Role.objects.filter(code=source_code, is_deleted=False).first()

        if source is None:
            continue

        target = Role.objects.filter(code=target_code, is_deleted=False).first()

        if target is None:
            # Tanpa target, menonaktifkan sumber cuma mencabut akses
            # pemegangnya. Dibiarkan apa adanya.
            continue

        held_by_target = set(
            RoleAssignment.objects
            .filter(role_id=target.pk)
            .values_list("user_id", flat=True)
        )

        stranded = 0

        for assignment in RoleAssignment.objects.filter(
                role_id=source.pk).order_by("pk"):

            if assignment.user_id in held_by_target:
                # Bentrok. Lihat docstring: ini keputusan orang.
                stranded += 1

                continue

            # **Cuma role_id.** `authority_mode`, `authority_level`, dan
            # baris `RoleAssignmentAuthority` menggantung di penugasan
            # ini, jadi semuanya ikut tanpa disentuh.
            assignment.role_id = target.pk

            assignment.save(update_fields=["role"])

            held_by_target.add(assignment.user_id)

        if stranded:
            # Masih ada yang memegangnya: dibiarkan aktif supaya tidak
            # ada yang kehilangan akses sebelum bentrokannya diputuskan.
            continue

        source.is_active = False

        source.save(update_fields=["is_active", "updated_at"])

    # ------------------------------------------------------------------
    # 3. Nama target yang menjanjikan cakupan
    # ------------------------------------------------------------------

    for code, name in RELABEL:
        Role.objects.filter(code=code, is_deleted=False).update(name=name)


def backwards(apps, schema_editor):
    """
    Penggabungannya **tidak** dibatalkan, dan itu bukan kelalaian.

    Keterangan yang dibutuhkan untuk memisahkannya kembali — penugasan
    mana yang tadinya milik role sumber — persis yang dihapus oleh
    penggabungan itu. Membalikkannya dengan menebak berarti memindahkan
    orang ke role yang tidak pernah ia pegang.

    Yang bisa dibalik dan memang dibalik: role sumbernya diaktifkan
    kembali (tidak pernah dihapus, cuma dinonaktifkan) dan kodenya
    dipulihkan. Penugasan tetap berada di role target; memindahkannya
    kembali pekerjaan layar User Role, dengan kewenangan yang dinyatakan
    orang.
    """
    Role = apps.get_model("accounts", "Role")

    for new_code, old_code, old_name in (
        ("KTT", "KTT-SITE", "Kepala Teknik Tambang — Site"),
    ):
        role = Role.objects.filter(code=new_code, is_deleted=False).first()

        if role is None or Role.objects.filter(
                code=old_code, is_deleted=False).exists():
            continue

        role.code = old_code
        role.name = old_name

        role.save(update_fields=["code", "name", "updated_at"])

    for source_code, _ in CONSOLIDATE:
        Role.objects.filter(code=source_code, is_deleted=False).update(
            is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_drop_legacy_data_scope'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
