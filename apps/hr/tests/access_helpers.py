"""
Perkakas kecil untuk fixture test yang membuat role sendiri.

`hr.employee` termasuk resource yang **bacanya** dijaga izin model
(`BaseMasterViewSet.require_view_permission`), jadi role tanpa
`hr.view_employee` menabrak 403 di daftar pegawai dan di dropdown-nya —
sebelum satu pun aturan cakupan sempat dijalankan.

Di produksi keadaan itu tidak ada: `READ_GRANTS` memberikan
`hr.view_employee` kepada **setiap** role yang diseed, dari EMPLOYEE
sampai SECURITY-GATE. Yang membedakan mereka bukan boleh membaca
pegawai atau tidak, melainkan **pegawai siapa** — dan itu urusan
cakupan.

Berkas ini menjaga fixture tetap sejalan dengan keadaan itu. Tanpa ini,
test cakupan gagal karena alasan yang tidak sedang diujinya, dan
membacanya seperti temuan padahal cuma fixture yang belum lengkap.

**Ini tidak melebarkan apa pun.** Izin menjawab jenis datanya; baris
mana yang terlihat tetap ditentukan `RoleDataPermission` yang dipasang
masing-masing test.
"""

from __future__ import annotations

from django.contrib.auth.models import Permission


def grant_employee_read(role) -> None:
    """Memberi `hr.view_employee` ke satu role, aman diulang."""
    permission = Permission.objects.filter(
        content_type__app_label="hr",
        codename="view_employee",
    ).first()

    if permission is None:
        # Bukan diam-diam dilewati: izinnya selalu ada begitu migration
        # `hr` jalan, jadi tidak adanya berarti panggungnya belum siap
        # dan test berikutnya akan gagal dengan sebab yang menyesatkan.
        raise AssertionError(
            "Izin 'hr.view_employee' tidak ada — content type hr.Employee "
            "belum terbentuk saat fixture ini dijalankan."
        )

    role.permissions.add(permission)
