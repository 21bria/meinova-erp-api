"""
Satu jalur untuk mengubah role yang dipegang seseorang.

Kenapa dipusatkan, padahal `.set()` sudah benar
------------------------------------------------
Perlu dinyatakan lurus, karena dugaan awalnya keliru: `.set()` milik
Django **tidak** membuang lalu membuat ulang baris yang tetap dipegang.
Dengan `clear=False` — bawaannya — ia menghitung selisih sendiri,
menghapus yang hilang dan menambah yang baru saja, dan **PK baris yang
bertahan tidak berubah**. Itu dibuktikan langsung, bukan dibaca dari
dokumentasi, dan dikunci `RetainedRowTests`.

Yang benar-benar rapuh bukan `.set()`-nya, melainkan **cara id-nya
sampai ke sana**. `UserRoleService.save()` sebelumnya:

* menelan id yang tidak bisa jadi angka (`except (TypeError,
  ValueError): continue`), lalu
* menyaring sisanya dengan `Role.objects.filter(pk__in=ids)`.

Dua-duanya membuang id **diam-diam**. Dan karena daftar yang dikirim
adalah daftar **utuh** — bukan perintah tambah — id yang terbuang tidak
berarti "abaikan", melainkan **"cabut role itu"**. Satu id kedaluwarsa
di layar, atau satu role yang baru di-soft-delete, dan penyimpanan yang
menjawab sukses justru mencabut kewenangan orang. Tidak ada satu pun
pesan yang menyebutkannya.

Karena itu di sini id yang tidak dikenal **ditolak**, bukan
dilewati, dan hasilnya menyebut apa yang ditambah **dan apa yang
dicabut**. Pencabutan kewenangan tidak boleh jadi efek samping yang
senyap.

Kontrak pembuatan penugasan (Stage 4H)
--------------------------------------
`Role` menjawab **WHAT** saja. `RoleAssignment` menjawab **WHERE** saja.
Tidak ada lagi yang menurunkan WHERE dari konfigurasi cakupan lama
saat penugasan dibuat — penurunan itu tinggal di
perkakas backfill, untuk tenant yang belum dialihkan.

Karena itu daftar role boleh dikirim dua bentuk, dan boleh dicampur:

* `5` / `"5"` / objek `Role` — **beri rolenya, tanpa kewenangan.**
  Penugasannya lahir `authority_mode` kosong, dan kosong berarti
  **tidak melihat apa pun**. Bentuk lama ini tetap sah supaya pemanggil
  yang ada tidak patah; artinya yang berubah, dan berubah ke arah
  tertutup.
* `{"role": 5, "authority_mode": ..., "authority_level": ...,
  "authorities": [...]}` — beri rolenya **berikut** WHERE-nya, dalam
  satu transaksi.

Yang **tidak** disediakan: bentuk yang diam-diam melebar. Konfigurasi
yang belum lengkap harus berakhir tertutup, bukan terbuka — itu satu-
satunya arah kegagalan yang tidak perlu ditemukan orang lewat kebocoran.

Penugasan yang **bertahan** tidak pernah disentuh kewenangannya oleh
penyimpanan daftar role, bentuk mana pun. Kewenangannya berdiri sendiri
begitu dibuat.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.accounts.models import Role, RoleAssignment


@dataclass(frozen=True)
class AssignmentDelta:
    """Apa yang berubah — termasuk yang sengaja dibiarkan."""

    added: list[int]
    removed: list[int]
    kept: list[int]

    def as_dict(self) -> dict:
        return {
            "added": sorted(self.added),
            "removed": sorted(self.removed),
            "kept": sorted(self.kept),
        }


class UnknownRoleError(ValueError):
    """Ada id role yang tidak bisa dipakai. Tidak ada yang disimpan."""

    def __init__(self, values):
        self.values = list(values)

        super().__init__(
            "Role tidak dikenal atau sudah dihapus: "
            + ", ".join(str(value) for value in self.values),
        )


@dataclass(frozen=True)
class InitialAuthority:
    """
    WHERE sebuah penugasan **saat dibuat**, dinyatakan pemanggilnya.

    `None` (bukan instance ini) berarti "tidak dinyatakan", dan itu
    berakhir `authority_mode` kosong — tidak melihat apa pun. Dua
    keadaan itu sengaja tidak diwakili satu nilai: "sengaja tanpa
    kewenangan" (`EXPLICIT` tanpa baris) harus bisa dibedakan dari
    "belum diatur", karena yang pertama keputusan dan yang kedua
    pekerjaan yang belum selesai.
    """

    mode: str
    level: str = ""
    authorities: tuple = ()


def _authority_from(payload) -> InitialAuthority | None:
    """`InitialAuthority` dari satu entri dict, atau `None`."""
    mode = payload.get("authority_mode") or payload.get("mode")

    if not mode:
        return None

    rows = payload.get("authorities") or ()

    return InitialAuthority(
        mode=mode,
        level=payload.get("authority_level") or payload.get("level") or "",
        authorities=tuple(
            (
                row["resource_type"],
                (
                    int(row["resource_id"])
                    if row.get("resource_id") not in (None, "")
                    else None
                ),
            )
            if isinstance(row, dict) else tuple(row)
            for row in rows
        ),
    )


def resolve_role_ids(role_ids) -> list[int]:
    """Id role saja — bentuk apa pun entrinya. Menolak, bukan menyaring."""
    return [role_id for role_id, _ in resolve_assignments(role_ids)]


def resolve_assignments(role_ids) -> list[tuple[int, InitialAuthority | None]]:
    """
    Mengubah daftar mentah jadi `(role_id, kewenangan-awal | None)`.

    Menolak, bukan menyaring. Lihat alasannya di docstring modul: daftar
    yang dikirim adalah daftar **utuh**, jadi id yang terbuang diam-diam
    terbaca sebagai perintah mencabut role.
    """
    wanted: list[tuple[int, InitialAuthority | None]] = []
    invalid: list = []

    for value in role_ids or []:
        authority = None

        # Tiga rupa pemanggil, satu jalur penulisan: layar User Role
        # mengirim id mentah dari JSON, serializer User mengirim objek
        # `Role` yang sudah divalidasi DRF, dan pemanggil yang menyertakan
        # WHERE sekaligus mengirim dict.
        if isinstance(value, dict):
            authority = _authority_from(value)

            value = value.get("role", value.get("id"))

        if isinstance(value, Role):
            wanted.append((value.pk, authority))

            continue

        try:
            wanted.append((int(value), authority))
        except (TypeError, ValueError):
            invalid.append(value)

    if invalid:
        raise UnknownRoleError(invalid)

    # Entri pertama menang kalau role yang sama disebut dua kali; yang
    # penting keduanya tidak diam-diam jadi dua penugasan.
    unique: dict[int, InitialAuthority | None] = {}

    for role_id, authority in wanted:
        unique.setdefault(role_id, authority)

    found = set(
        Role.objects
        .filter(pk__in=list(unique), is_deleted=False)
        .values_list("pk", flat=True)
    )

    missing = [value for value in unique if value not in found]

    if missing:
        raise UnknownRoleError(missing)

    return list(unique.items())


@transaction.atomic
def assign_roles(user, role_ids) -> AssignmentDelta:
    """
    Menyamakan role yang dipegang `user` dengan `role_ids`.

    Dikerjakan sebagai **selisih**: baris yang tetap dipegang tidak
    disentuh sama sekali, jadi PK-nya bertahan. Itu yang membuat
    kewenangan bisa menempel pada baris ini tanpa hilang setiap kali
    seseorang menyimpan layar role.

    Entri boleh berupa id saja atau dict berisi WHERE-nya sekaligus —
    lihat docstring modul. Keduanya dalam **satu** transaksi: tidak ada
    jendela waktu ketika penugasannya sudah ada tapi kewenangannya
    belum. Kalaupun ada, arahnya tertutup, bukan terbuka.

    Kewenangan hanya ditulis untuk penugasan yang **baru dibuat**.
    Menyimpan daftar role tidak boleh menulis ulang kewenangan yang
    sudah ada — itu milik pasangan (orang, role), bukan milik daftar.
    """
    resolved = resolve_assignments(role_ids)

    wanted = {role_id for role_id, _ in resolved}

    held = set(
        RoleAssignment.objects
        .filter(user=user)
        .values_list("role_id", flat=True)
    )

    to_add = wanted - held
    to_remove = held - wanted

    if to_remove:
        RoleAssignment.objects.filter(
            user=user,
            role_id__in=to_remove,
        ).delete()

    if to_add:
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(user=user, role_id=role_id)
                for role_id in sorted(to_add)
            ],
            # Dua admin yang menyimpan layar yang sama pada saat yang
            # sama tidak boleh membuat salah satunya gagal dengan
            # IntegrityError. `UNIQUE(user, role)` tetap yang menjaga
            # kebenarannya — ini cuma menentukan siapa yang menang
            # tanpa ribut.
            ignore_conflicts=True,
        )

        # WHERE-nya **cuma yang dinyatakan pemanggil**. Tidak ada yang
        # dibaca dari konfigurasi cakupan lama
        # di sini — itu justru yang dibuang Stage 4H. Yang tidak
        # dinyatakan tetap `authority_mode` kosong, dan kosong berarti
        # tidak melihat apa pun sampai seseorang menentukannya.
        for role_id, authority in resolved:
            if role_id in to_add and authority is not None:
                _write_authority(
                    user,
                    role_id,
                    mode=authority.mode,
                    level=authority.level,
                    rows=authority.authorities,
                )

    return AssignmentDelta(
        added=sorted(to_add),
        removed=sorted(to_remove),
        kept=sorted(wanted & held),
    )


@transaction.atomic
def grant_role(user, role, *, mode, level="", authorities=()) -> RoleAssignment:
    """
    Memberi **satu** role berikut WHERE-nya, sekali jalan.

    Untuk pemanggil non-interaktif — seed, perintah manajemen, UAT —
    yang sebelumnya menulis `user.roles.add(role)` lalu bergantung pada
    kewenangan yang diturunkan dari `Role`. Turunan itu sudah tidak ada,
    jadi maksudnya harus disebut di tempat pemanggilnya: siapa yang
    memberi role juga yang tahu sejauh mana role itu berlaku baginya.

    Kalau penugasannya **sudah ada**, kewenangannya tidak disentuh.
    Menjalankan seed dua kali tidak boleh mengembalikan kewenangan yang
    sudah disunting orang ke nilai awalnya.
    """
    role_id = role.pk if isinstance(role, Role) else int(role)

    assignment = RoleAssignment.objects.filter(
        user=user, role_id=role_id).first()

    if assignment is not None:
        return assignment

    delta = assign_roles(
        user,
        [
            *RoleAssignment.objects
            .filter(user=user)
            .values_list("role_id", flat=True),
            {
                "role": role_id,
                "authority_mode": mode,
                "authority_level": level,
                "authorities": [
                    {"resource_type": row[0], "resource_id": row[1]}
                    for row in authorities
                ],
            },
        ],
    )

    assert role_id in delta.added

    return RoleAssignment.objects.get(user=user, role_id=role_id)


# ----------------------------------------------------------------------
# Kewenangan per penugasan (Stage 4E — administrasi)
# ----------------------------------------------------------------------

# Jenis yang boleh disunting dari layar. Sengaja **bukan** seluruh
# `ResourceType`: `warehouse`, `project`, dan `iup` ada di enum tapi
# belum punya satu pun model yang dipetakan, jadi menyodorkannya cuma
# menawarkan kewenangan yang tidak menyaring apa pun.
EDITABLE_RESOURCE_TYPES = (
    "company",
    "branch",
    "location",
    "division",
    "department",
    "section",
    "cost_center",
)

# `own` ("baris yang user_id-nya saya") **tidak** disunting di sini —
# ia datang dari konfigurasi role, bukan dari pilihan organisasi — tapi
# juga **tidak boleh terhapus** karenanya. 22 penugasan EMPLOYEE di
# tenant peragaan bergantung padanya, dan penyimpanan yang mengirim
# daftar tanpa `own` akan mencabut hak orang atas datanya sendiri tanpa
# ada yang memintanya. Karena itu baris `own` dilewati sepenuhnya oleh
# penyuntingan: tidak dikirim klien, tidak dihapus server.
PRESERVED_RESOURCE_TYPES = ("own",)


class AuthorityValidationError(ValueError):
    """Kombinasi mode/level/baris yang tidak sah. Tidak ada yang disimpan."""


def read_authority(user) -> list[dict]:
    """Kewenangan tiap penugasan milik `user`, untuk layar administrasi."""
    from apps.accounts.models import RoleAssignment

    rows = []

    for assignment in (
        RoleAssignment.objects
        .filter(user=user, role__is_deleted=False)
        .select_related("role")
        .prefetch_related("authorities")
        .order_by("role__code")
    ):
        authorities = [
            {
                "resource_type": authority.resource_type,
                "resource_id": authority.resource_id,
            }
            for authority in assignment.authorities.all()
        ]

        rows.append({
            "assignment": assignment.pk,
            "role": assignment.role_id,
            "role_code": assignment.role.code,
            "role_name": assignment.role.name,
            "authority_mode": assignment.authority_mode,
            "authority_level": assignment.authority_level,
            "authorities": [
                row for row in authorities
                if row["resource_type"] in EDITABLE_RESOURCE_TYPES
            ],
            # Ditampilkan, tidak disunting — supaya yang menyimpan tahu
            # baris ini ada dan tidak mengira kewenangannya kosong.
            "preserved": [
                row for row in authorities
                if row["resource_type"] in PRESERVED_RESOURCE_TYPES
            ],
        })

    return rows


def validate_authority(mode, level, authorities, *, allow_preserved=False) -> None:
    """
    Aturan yang harus berlaku bersamaan.

    Ditegakkan di service, bukan di serializer: perintah manajemen dan
    seed menulis lewat jalur yang sama, dan aturan yang cuma hidup di
    serializer tidak berlaku bagi mereka.

    `allow_preserved` memperbolehkan jenis yang tidak bisa disunting
    dari layar — hari ini cuma `own`. Layar memang tidak boleh
    menyentuhnya (ia datang dari keputusan role, bukan dari pilihan
    organisasi), tapi pemanggil non-interaktif justru harus bisa
    menyatakannya: `EMPLOYEE` berarti "datanya sendiri", dan sesudah
    turunan dari `Role` dibuang, tidak ada lagi yang menuliskannya
    kalau seed-nya tidak menyebut.
    """
    from apps.accounts.models import AuthorityMode

    if mode not in AuthorityMode.values:
        raise AuthorityValidationError(
            f"Mode kewenangan tidak dikenal: {mode!r}.")

    if mode == AuthorityMode.PLACEMENT:
        if not level:
            raise AuthorityValidationError(
                "Mode 'Ikut Penempatan Pemegang' butuh tingkat organisasi."
            )

        if authorities:
            raise AuthorityValidationError(
                "Mode 'Ikut Penempatan Pemegang' tidak memakai daftar "
                "kewenangan — nilainya diambil dari penempatan orangnya."
            )

        return

    if level:
        raise AuthorityValidationError(
            "Tingkat organisasi hanya dipakai mode 'Ikut Penempatan "
            "Pemegang'."
        )

    if mode == AuthorityMode.UNRESTRICTED and authorities:
        raise AuthorityValidationError(
            "Mode 'Tanpa Batas' tidak memakai daftar kewenangan."
        )

    if mode == AuthorityMode.EXPLICIT:
        allowed = EDITABLE_RESOURCE_TYPES + (
            PRESERVED_RESOURCE_TYPES if allow_preserved else ()
        )

        for row in authorities:
            resource_type = row.get("resource_type")

            if resource_type not in allowed:
                raise AuthorityValidationError(
                    f"Jenis kewenangan tidak bisa disunting: "
                    f"{resource_type!r}."
                )

            # `own` tidak menyebut nilai apa pun — artinya "baris yang
            # user_id-nya saya", dan itu tidak butuh id.
            if (
                resource_type not in PRESERVED_RESOURCE_TYPES
                and row.get("resource_id") in (None, "")
            ):
                raise AuthorityValidationError(
                    f"Kewenangan {resource_type!r} harus menyebut nilainya."
                )

        # **Nol baris sah, dan artinya tanpa kewenangan.** Bukan
        # kelalaian yang perlu ditolak: kadang itu memang yang
        # dimaksud — penugasan yang WHERE-nya sengaja belum diberikan.
        # Layarnya yang wajib menyatakannya dengan jelas.


@transaction.atomic
def set_authority(user, role_id, *, mode, level="", authorities=()) -> dict:
    """
    Menetapkan kewenangan satu penugasan.

    **Tidak pernah membuat penugasan.** Kewenangan hanya bisa menempel
    pada keanggotaan yang sudah ada — kalau tidak, layar ini jadi
    pintu kedua untuk memberi role, dan pintu kedua itu tidak melewati
    satu pun aturan penugasan.

    PK penugasannya tidak berubah: yang ditulis kolomnya, dan baris
    kewenangannya direkonsiliasi sebagai selisih.
    """
    assignment = (
        RoleAssignment.objects
        .filter(user=user, role_id=role_id, role__is_deleted=False)
        .select_related("role")
        .first()
    )

    if assignment is None:
        raise AuthorityValidationError(
            "Pengguna ini tidak memegang role tersebut. Berikan rolenya "
            "lebih dulu, baru tentukan kewenangannya."
        )

    return _reconcile_authority(
        assignment, mode=mode, level=level, authorities=authorities)


def _reconcile_authority(
    assignment, *, mode, level="", authorities=(), allow_preserved=False,
) -> dict:
    """
    Menulis mode/level dan **merekonsiliasi** baris kewenangan.

    PK penugasannya tidak berubah: yang ditulis kolomnya, dan barisnya
    dihitung sebagai selisih. Baris `own` dilewati sepenuhnya kecuali
    pemanggilnya memang menyatakannya.
    """
    from apps.accounts.models import RoleAssignmentAuthority

    rows = [
        {
            "resource_type": row.get("resource_type"),
            "resource_id": (
                int(row["resource_id"])
                if row.get("resource_id") not in (None, "")
                else None
            ),
        }
        for row in (authorities or [])
    ]

    validate_authority(mode, level, rows, allow_preserved=allow_preserved)

    assignment.authority_mode = mode
    assignment.authority_level = level or ""

    assignment.save(update_fields=["authority_mode", "authority_level"])

    wanted = {
        (row["resource_type"], row["resource_id"]) for row in rows
    }

    held_query = assignment.authorities.all()

    if not allow_preserved:
        held_query = held_query.exclude(
            resource_type__in=PRESERVED_RESOURCE_TYPES)

    held = set(held_query.values_list("resource_type", "resource_id"))

    to_remove = held - wanted
    to_add = wanted - held

    for resource_type, resource_id in to_remove:
        RoleAssignmentAuthority.objects.filter(
            assignment=assignment,
            resource_type=resource_type,
            resource_id=resource_id,
        ).delete()

    if to_add:
        RoleAssignmentAuthority.objects.bulk_create(
            [
                RoleAssignmentAuthority(
                    assignment=assignment,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
                for resource_type, resource_id in sorted(
                    to_add, key=lambda item: (item[0], item[1] or 0))
            ],
            ignore_conflicts=True,
        )

    return {
        "assignment": assignment.pk,
        "role": assignment.role_id,
        "authority_mode": assignment.authority_mode,
        "authority_level": assignment.authority_level,
        "added": sorted(to_add),
        "removed": sorted(to_remove),
    }


def _write_authority(user, role_id, *, mode, level="", rows=()) -> dict:
    """WHERE awal sebuah penugasan yang **baru** dibuat."""
    assignment = RoleAssignment.objects.get(user=user, role_id=role_id)

    return _reconcile_authority(
        assignment,
        mode=mode,
        level=level,
        authorities=[
            {"resource_type": resource_type, "resource_id": resource_id}
            for resource_type, resource_id in rows
        ],
        # Pemanggil non-interaktif harus bisa menyatakan `own`; layar
        # tetap tidak bisa (serializernya tidak menerimanya).
        allow_preserved=True,
    )
