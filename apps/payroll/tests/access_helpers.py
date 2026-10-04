"""
Perkakas kecil untuk fixture test payroll yang membuat role sendiri.

Sejak Stage 3B, permukaan baca payroll — daftar, rekap `summary/`, dan
seluruh widget dashboard — menghitung cakupannya **per izin**. Role
tanpa `payroll.view_payrollrun` dan kembarannya karena itu membaca nol
baris, dan test cakupan yang role-nya kosong gagal karena alasan yang
bukan sedang diujinya.

Di produksi keadaan itu tidak ada: `READ_GRANTS` memberikan ketiga izin
di bawah kepada HR-ADMIN, HR-MANAGER, kembaran site-nya, dan
FINANCE-MANAGER sekaligus. Yang membedakan meja-meja itu bukan boleh
tidaknya membuka payroll, melainkan **baris siapa** — dan itu urusan
cakupan, yang tetap dipasang masing-masing test.

**Ini tidak melebarkan apa pun.** Izin menjawab jenis datanya; baris
mana yang terlihat tetap ditentukan `RoleDataPermission`.
"""

from __future__ import annotations

from django.contrib.auth.models import Permission


# Tiga izin yang dipakai tiga permukaan payroll yang harus sepakat:
# daftar per pegawai, pemilih run, dan pemilih periode.
PAYROLL_READS = (
    "view_payrollrun",
    "view_payrollrunemployee",
    "view_payrollperiod",
)


def grant_payroll_read(role) -> None:
    """Memberi izin baca payroll ke satu role, aman diulang."""
    permissions = list(
        Permission.objects.filter(
            content_type__app_label="payroll",
            codename__in=PAYROLL_READS,
        )
    )

    if len(permissions) != len(PAYROLL_READS):
        # Bukan diam-diam dilewati: izinnya selalu ada begitu migration
        # `payroll` jalan, jadi tidak lengkapnya berarti panggungnya
        # belum siap — dan test berikutnya akan gagal dengan sebab yang
        # menyesatkan.
        found = sorted(item.codename for item in permissions)

        raise AssertionError(
            f"Izin baca payroll tidak lengkap: {found}. Content type "
            f"payroll belum terbentuk saat fixture ini dijalankan."
        )

    role.permissions.add(*permissions)
