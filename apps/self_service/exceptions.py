"""
Kenapa seseorang tidak punya halaman `/me`.

Tiga sebab yang berbeda, dan ketiganya **harus** terbaca berbeda oleh
yang mengalaminya. Satu pesan "akses ditolak" untuk ketiganya memindahkan
pekerjaan diagnosis ke helpdesk: akun integrasi yang memang tidak
berpegawai, pegawai yang baru resign, dan pegawai yang kartunya dihapus
HR minggu lalu adalah tiga percakapan yang sama sekali berlainan.

Turunan `APIException`, bukan `Exception` biasa. `meinova_exception_handler`
membungkus seluruh `APIException` jadi `{success, message, errors,
status_code}` yang sama dengan sisa API — jadi frontend tidak perlu
mengenali bentuk balasan khusus untuk Self Service.
"""

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError


class SelfServiceUnavailable(APIException):
    """Induk seluruh sebab. Jangan dilempar langsung."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Halaman ini tidak tersedia untuk akun Anda."
    default_code = "self_service_unavailable"


class EmployeeNotLinked(SelfServiceUnavailable):
    """
    Akun sah, tapi tidak menunjuk kartu pegawai mana pun.

    **Keadaan yang lazim dan bukan kesalahan**: akun sistem, akun
    integrasi, superuser yang bukan karyawan, dan akun yang dibuat
    sebelum pegawainya didaftarkan. Karena itu 404 — tidak ada yang
    perlu dijaga, yang diminta memang tidak ada — dan pesannya menyebut
    jalan keluarnya.
    """

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = (
        "Akun ini belum ditautkan ke data pegawai mana pun. Hubungi HR "
        "untuk menghubungkan akun Anda ke kartu pegawai."
    )
    default_code = "employee_not_linked"


class EmployeeInactive(SelfServiceUnavailable):
    """
    Kartu pegawainya ada, tapi sudah tidak aktif.

    Dibedakan dari `EmployeeNotLinked` karena yang perlu dilakukan
    berbeda: yang ini tidak bisa diselesaikan dengan menautkan akun.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = (
        "Data pegawai Anda berstatus tidak aktif, jadi halaman Self "
        "Service tidak bisa dibuka. Hubungi HR kalau ini keliru."
    )
    default_code = "employee_inactive"


class FieldNotAccepted(ValidationError):
    """
    Kolom yang tidak diterima jalur pengajuan pribadi.

    **Ditolak, bukan diabaikan.** Pemanggil yang mengirim `employee` ke
    `/api/me/*` sedang mengira bisa memilih subjeknya; mengabaikannya
    diam-diam membuat kesalahpahaman itu tidak pernah terbaca. Kolom HR
    (status, override, organisasi) ditolak dengan alasan yang sama:
    jalur ini bukan versi kecil formulir HR.

    `code` = `field_not_accepted`, per kolom di `errors`.
    """

    default_code = "field_not_accepted"
