"""
Menyelaraskan email akun peragaan yang **sudah ada** dengan daftarnya.

Dua seed pembentuk akun (`demo_workforce`, `demo_employees`) sudah
menulis ulang `User.email` tiap kali dijalankan, jadi secara berkas
mereka tidak salah. Yang tidak tertutup adalah dua keadaan yang
dua-duanya sudah terjadi di tenant peragaan yang sedang dipakai:

1. **Daftarnya bertambah setelah tenantnya diseed.** Akun yang dulu
   tidak ada di `DEMO_EMAILS` sudah terlanjur menyimpan alamat
   `@example.test`, dan alamat itu baru berubah kalau seed pembentuknya
   dijalankan ulang — yaitu perintah yang juga menyentuh pegawai,
   dokumen, dan roster. Memperbaiki alamat email seharusnya tidak
   menuntut pembangunan ulang seluruh tenant.

2. **Akunnya dibentuk seed yang berbeda dari yang dijalankan.**
   `demo_employees` membentuk dua puluh enam akun, `demo_workforce`
   sebelas. Menjalankan yang sebelas tidak menyentuh lima belas
   sisanya, dan lima belas akun itu tetap memegang alamat lamanya tanpa
   satu pun baris keluaran yang menyebutkannya.

Karena itu berkas ini berdiri sendiri: ia **tidak membentuk apa pun**.
Tidak ada user baru, tidak ada employee, tidak ada role. Yang disentuh
hanya kolom `email` milik akun berawalan `demo.` yang sudah ada — dan
hanya kalau alamatnya memang berbeda dari daftarnya, supaya menjalankan
ini dua kali tidak menghasilkan baris "diperbarui" yang kedua.

Akun sistem tidak ikut. Penyaringnya awalan username `demo.`, bukan
daftar tetap: `admin` (superadmin tenant, dibentuk
`create_superadmin`) tidak berawalan itu dan karena itu alamatnya tidak
pernah bisa tersentuh perintah ini walau dijalankan di tenant mana pun.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.hr.seeds.demo_accounts import USERNAME_PREFIX, demo_email


@transaction.atomic
def run(*, log=print, dry_run: bool = False) -> dict:
    """
    Selaraskan email seluruh akun `demo.` yang ada di schema aktif.

    Mengembalikan ringkasan plus pemetaan `username → email` sesudah
    penyelarasan, supaya pemanggilnya bisa mencetak keadaan akhir tanpa
    membaca ulang tabelnya.
    """
    User = get_user_model()

    accounts = (
        User.objects
        .filter(username__startswith=USERNAME_PREFIX)
        .order_by("username")
    )

    # Alamat email unik di tabel user, jadi dua akun peragaan yang
    # dipetakan ke alamat yang sama tidak akan gagal di sini melainkan
    # di baris `save()` yang kedua — dengan pesan basis data yang tidak
    # menyebut satu pun username. Diperiksa lebih dulu supaya yang
    # muncul adalah nama akun yang bentrok, bukan nama constraint.
    targets: dict[str, str] = {}

    for username in accounts.values_list("username", flat=True):
        address = demo_email(username)

        if address in targets:
            raise ValueError(
                f"Alamat {address} dipetakan ke dua akun: "
                f"{targets[address]} dan {username}. Perbaiki "
                f"DEMO_EMAIL_ALIASES di apps/hr/seeds/demo_accounts.py."
            )

        targets[address] = username

    changed: list[tuple[str, str, str]] = []
    unchanged: list[str] = []
    mapping: dict[str, str] = {}

    for user in accounts:
        target = demo_email(user.username)
        current = user.email or ""

        mapping[user.username] = target

        if current == target:
            unchanged.append(user.username)
            continue

        changed.append((user.username, current, target))

        if not dry_run:
            user.email = target

            # Hanya kolom `email`. Baris akun peragaan juga menyimpan
            # password yang sudah di-hash dan penanda aktif yang
            # disusun seed lain; `save()` polos menulis ulang semuanya
            # dari salinan yang dibaca perintah ini, dan perubahan yang
            # datang di antaranya hilang tanpa jejak.
            user.save(update_fields=["email"])

    for username, before, after in changed:
        log(f"  {username:<20} {before or '(kosong)'} → {after}")

    return {
        "total": len(mapping),
        "changed": len(changed),
        "unchanged": len(unchanged),
        "dry_run": dry_run,
        "mapping": mapping,
    }
