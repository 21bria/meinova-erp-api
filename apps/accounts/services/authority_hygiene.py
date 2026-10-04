"""
Kebersihan kewenangan penugasan — **tanpa menyebut skema lama.**

Kenapa ini ada sesudah peralihannya selesai
-------------------------------------------
Perkakas peralihan menjawab pertanyaan yang punya tanggal kedaluwarsa:
"apakah tenant ini sudah dipindahkan dari cakupan lama?" Sesudah semua
tenant dipindahkan dan skemanya dihapus, pertanyaan itu tidak bisa
ditanyakan lagi — dan pemeriksaannya ikut terhapus bersamanya.

Tapi dua dari tiga keadaan yang dicarinya **tidak** ada hubungannya
dengan peralihan. Keduanya bisa lahir besok, dari kode yang ditulis
orang yang belum pernah mendengar soal skema lama itu:

* **kewenangan kosong** — penugasan yang dibuat lewat jalur yang tidak
  menyebut WHERE (`.roles.add()`, `.set()`, fixture, perintah baru).
  Runtime menutupnya, jadi tidak ada insiden keamanan; yang terjadi
  orang melihat layar kosong tanpa pesan yang menjelaskan kenapa.
* **`EXPLICIT` tanpa satu pun baris** — bentuknya sama persis dengan
  "sengaja tidak boleh melihat apa-apa", dan itu memang arti yang
  berlaku. Yang membuatnya perlu dilaporkan: ia juga bentuk yang
  dihasilkan layar yang disimpan sebelum barisnya dipilih. Perkakas ini
  **tidak menebak** mana yang mana — itu keputusan orang. Ia cuma
  menolak membiarkannya tidak terlihat.
* **baris kewenangan cacat** — `resource_type` di luar daftar yang
  dikenal, atau `resource_id` kosong pada tipe yang membutuhkannya.
  Baris begini tidak menyaring apa pun dan tidak pula membuka apa pun;
  ia sekadar tidak berarti, dan diam-diam mempersempit orang yang
  mengiranya sudah diatur.

Jadi yang dipertahankan bukan perkakas peralihannya melainkan
**kebersihannya**, dilepas dari skema yang sudah tiada. Tidak satu pun
nama di berkas ini merujuk model lama; ia tetap bisa dijalankan sepuluh
rilis lagi.

**Read-only.** Ia melaporkan, tidak memperbaiki. Memperbaiki berarti
menebak WHERE seseorang, dan itu justru kesalahan yang membuat seluruh
rangkaian ini ada.
"""

from __future__ import annotations

from apps.accounts.models import (
    AuthorityMode,
    AuthorityResourceType,
    RoleAssignment,
    RoleAssignmentAuthority,
)


# Tipe yang **tidak** memakai `resource_id`. `own` berarti "baris yang
# `user_id`-nya saya" — sasarannya pemegangnya sendiri, jadi tidak ada
# id yang perlu disebut.
IDLESS_TYPES = (AuthorityResourceType.OWN,)


def authority_hygiene() -> dict:
    """
    Keadaan kewenangan satu tenant. Read-only, aman dijalankan kapan pun.

    Yang dikembalikan hitungan **dan** contohnya: angka saja memberi
    tahu ada masalah tanpa memberi tahu di mana, dan laporan seperti itu
    berakhir diabaikan.
    """
    blank = list(
        RoleAssignment.objects
        .filter(authority_mode="")
        .select_related("user", "role")
        .order_by("pk")
    )

    explicit_zero = [
        assignment
        for assignment in RoleAssignment.objects
        .filter(authority_mode=AuthorityMode.EXPLICIT)
        .select_related("user", "role")
        .order_by("pk")
        if not assignment.authorities.exists()
    ]

    placement_without_level = list(
        RoleAssignment.objects
        .filter(authority_mode=AuthorityMode.PLACEMENT, authority_level="")
        .select_related("user", "role")
        .order_by("pk")
    )

    known = {value for value, _ in AuthorityResourceType.choices}

    malformed = [
        row
        for row in RoleAssignmentAuthority.objects
        .select_related("assignment__user", "assignment__role")
        .order_by("pk")
        if row.resource_type not in known
        or (row.resource_id is None
            and row.resource_type not in IDLESS_TYPES)
    ]

    # Kewenangan yang menempel pada mode yang tidak memakainya. Bukan
    # kebocoran — `DataScopeService` tidak membacanya — tapi ia
    # **terlihat** seperti pembatasan yang berlaku di layar, dan
    # pembatasan yang cuma terlihat lebih berbahaya daripada yang tidak
    # ada sama sekali.
    rows_on_non_explicit = list(
        RoleAssignmentAuthority.objects
        .exclude(assignment__authority_mode=AuthorityMode.EXPLICIT)
        .select_related("assignment__user", "assignment__role")
        .order_by("pk")
    )

    return {
        "assignments": RoleAssignment.objects.count(),
        "authority_rows": RoleAssignmentAuthority.objects.count(),
        "blank_authority": blank,
        "explicit_without_rows": explicit_zero,
        "placement_without_level": placement_without_level,
        "malformed_rows": malformed,
        "rows_on_non_explicit_mode": rows_on_non_explicit,
    }


def is_clean(report: dict) -> bool:
    """
    Bersih = tidak ada satu pun temuan.

    `explicit_without_rows` **ikut dihitung sebagai temuan**, dan itu
    disengaja meskipun ia bisa jadi keadaan yang benar-benar dimaksudkan.
    Alasannya: keadaan itu tidak bisa dibedakan dari layar yang disimpan
    setengah jalan, dan yang salah di antara keduanya menutup akses
    seseorang tanpa satu pun pesan. Melaporkannya memaksa keputusannya
    diambil orang; mendiamkannya membuat keduanya terlihat sama.
    """
    return not any(
        report[key] for key in (
            "blank_authority",
            "explicit_without_rows",
            "placement_without_level",
            "malformed_rows",
            "rows_on_non_explicit_mode",
        )
    )
