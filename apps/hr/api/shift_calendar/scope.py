"""
Siapa yang boleh **melihat** kalender, dan siapa yang boleh
**menyesuaikan** shift-nya. Dua pertanyaan berbeda, dan itu seluruh isi
berkas ini.

Sebelumnya jawabannya hidup sebagai potongan kode di dalam
`ShiftCalendarView.get()`, dan satu-satunya pemakainya endpoint
kalender. Akibatnya jalur tulis — `POST /api/hr/shift-assignments/` —
tidak memeriksa cakupan sama sekali: `filter_queryset()` menjaga baca,
ubah, dan hapus, tapi **create tidak melewatinya**. HR Admin Site yang
dicakup ke satu lokasi bisa menerbitkan adjustment untuk pegawai site
sebelah lewat satu request yang id-nya diketik tangan.

## Cakupan baca lebih luas daripada cakupan tulis, dan itu disengaja

    lihat  = DataScope  ∪  garis pelaporan  ∪  dirinya sendiri
    adjust = DataScope

* **`DataScope`** — kewenangan `RoleAssignment` / Organization Scope existing.
  Ini yang membedakan HR (seluruh tenant), Admin Department, dan Admin
  Section satu sama lain, dan tidak satu barisnya pun ditulis di sini.
* **Garis pelaporan** — `apps.hr.reporting_line`, yang sudah dipakai
  endpoint kalender dan dropdown pegawai. Atasan langsung lazimnya
  dicakup `own`; tanpa ini ia cuma menemukan dirinya sendiri, padahal
  justru jadwal timnya yang harus ia pantau. **Hanya menambah**, dan
  isinya diturunkan dari akun yang meminta — yang paling jauh bisa
  didapat seseorang adalah bawahannya sendiri.
* **Dirinya sendiri** — pegawai yang punya akun selalu boleh membuka
  kalendernya sendiri. Alasan yang sama dengan `employees/me/`: kartu
  sendiri tidak boleh bisa ditutup oleh cakupan data, karena admin yang
  penempatannya dipindah akan kehilangan halamannya sendiri tanpa satu
  pun pesan yang menyebut sebabnya.

Garis pelaporan **tidak** ikut ke jalur tulis. Memantau jadwal tim
adalah pekerjaan atasan; mengubahnya bukan — itu wewenang operasional
yang ditegakkan `ModelPermission` (`hr.add_employeeshiftassignment`),
dan cakupan barisnya tetap cakupan organisasi.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.hr import reporting_line
from apps.hr.api.employee.scope import EMPLOYEE_SCOPE


def _base(queryset=None):
    if queryset is not None:
        return queryset

    from apps.hr.models import Employee

    return Employee.objects.filter(is_deleted=False)


def _is_authenticated(user) -> bool:
    return user is not None and bool(getattr(user, "is_authenticated", False))


def viewable_employees(user, *, queryset=None):
    """
    Pegawai yang kalendernya boleh dibuka `user`.

    `queryset` boleh diisi queryset `Employee` yang **sudah** disaring
    dasar (aktif, belum dihapus). Wajib queryset yang sama yang dipakai
    memperluas — `reporting_line.widen` meng-OR, bukan menumpuk, jadi
    `Employee.objects` telanjang akan menghidupkan kembali baris yang
    sudah dibuang penyaring dasarnya.
    """
    base = _base(queryset)

    # Cakupannya ditanyakan **per izin**, sama dengan tabel Employee.
    # Tanpa `permission`, satu role tak berbatas yang tidak ada
    # hubungannya dengan kepegawaian menyalakan `unrestricted` dan
    # seluruh penyaringan di bawahnya dilewati.
    from apps.hr.models import Employee

    permission = view_permission_for(Employee)

    scope = DataScopeService.for_user(user, permission=permission)

    # HR tak bercakupan dan superuser: querysetnya dikembalikan apa
    # adanya, tanpa `distinct()` dan tanpa OR tambahan — SQL-nya harus
    # tetap sama persis dengan sebelum berkas ini ada.
    if scope.unrestricted:
        return base

    scoped = DataScopeService.filter(
        base,
        EMPLOYEE_SCOPE,
        user,
        required_permission=permission,
    )

    # "Dirinya sendiri" digabung **sebelum** `widen`, bukan sesudah.
    # `widen` menutup hasilnya dengan `.distinct()`, dan Django menolak
    # meng-OR queryset distinct dengan yang bukan — "Cannot combine a
    # unique query with a non-unique query", `TypeError` mentah yang
    # jatuh sebagai 500 untuk **setiap** kursi yang dibatasi: Admin
    # Section, Admin Department, atasan langsung, dan pegawai biasa.
    # Yang menentukan urutannya, bukan isinya.
    if _is_authenticated(user):
        scoped = scoped | base.filter(user_id=user.pk)

    scoped = reporting_line.widen(scoped, base=base, user=user)

    # `distinct()` di ujung, sekali. Penyaring cakupan menembus relasi
    # organisasi, dan OR di atas join bisa memulangkan baris yang sama
    # lebih dari sekali — duplikat di daftar pegawai tidak terbaca
    # seperti bug, terbaca seperti dua orang bernama sama.
    return scoped.distinct()


def adjustable_employees(user, *, queryset=None):
    """
    Pegawai yang shift-nya boleh **disesuaikan** `user`.

    Cakupan organisasi saja. Yang menentukan boleh-tidaknya menekan
    tombolnya tetap `ModelPermission`; yang di sini menentukan **baris
    siapa** — dan keduanya harus lewat, bukan salah satu.
    """
    from apps.hr.models import Employee

    base = _base(queryset)

    return DataScopeService.filter(
        base,
        EMPLOYEE_SCOPE,
        user,
        required_permission=view_permission_for(Employee),
    )


def assert_adjustable(*, employee, user) -> None:
    """
    Menolak penyesuaian shift untuk pegawai di luar cakupan penulisnya.

    Dipanggil dari service, bukan viewset: `perform_create()` tidak
    pernah melewati `filter_queryset()`, jadi penjagaan yang ditaruh di
    viewset hanya menjaga baca dan ubah. Seed dan perintah manajemen
    memanggil service dengan `user=None` dan memang tidak dijaga —
    keduanya berjalan sebagai sistem, bukan sebagai seseorang.
    """
    if employee is None:
        return

    if not _is_authenticated(user):
        return

    if getattr(user, "is_superuser", False):
        return

    # Service dipanggil dari dua bentuk: serializer DRF mengoper
    # instance, sementara pemanggil internal kadang mengoper pk. Yang
    # kedua akan lolos diam-diam kalau `employee.pk` diambil begitu
    # saja — `AttributeError`-nya jadi 500, bukan penolakan.
    employee_id = getattr(employee, "pk", employee)

    allowed = (
        adjustable_employees(user)
        .filter(pk=employee_id)
        .exists()
    )

    if allowed:
        return

    label = getattr(employee, "employee_number", None) or f"#{employee_id}"

    raise ValidationError(
        {
            "employee": (
                f"Pegawai {label} berada di luar cakupan data Anda, "
                "jadi shift-nya tidak bisa disesuaikan dari sini."
            ),
        },
    )


def can_adjust_shift(user) -> bool:
    """
    Boleh menekan tombol Adjust Shift atau tidak.

    Jawabannya **bukan** aturan baru: ini `ModelPermission` yang sama
    yang menolak `POST /api/hr/shift-assignments/`, dibaca lebih awal
    supaya layarnya tidak menyodorkan tombol yang pasti ditolak.
    `hr.add_employeeshiftassignment` dicentang di layar Roles seperti
    izin model lain — tidak ada satu kode role pun di berkas ini.

    Yang perlu disadari: ini menjawab "boleh **mengubah** shift", bukan
    "boleh **melihat** kalender". Keduanya sengaja dipisah — pegawai
    yang membuka kalendernya sendiri tidak punya izin ini, dan memang
    tidak seharusnya punya.
    """
    if not _is_authenticated(user):
        return False

    if getattr(user, "is_superuser", False):
        return True

    return user.has_perm("hr.add_employeeshiftassignment")
