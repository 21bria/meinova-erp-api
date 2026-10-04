"""
Kemudahan layar untuk direksi — **bukan** lapisan wewenang.

Tidak ada satu baris di berkas ini yang menambah baris yang boleh
dilihat seseorang. Yang diputuskan di sini cuma dua hal yang keduanya
soal tampilan:

* isi tombol pintas "Lokasi Saya" (seluruh baris ber-kode sama dengan
  lokasi penempatannya, bukan satu baris dan bukan seluruh cakupannya);
* apakah dropdown Location dikelompokkan per **kode lokasi**, sehingga
  satu gedung yang ditempati dua belas badan usaha tampil sekali, bukan
  dua belas kali.

Keduanya tetap melewati `DataScopeService`. Kalau berkas ini dihapus
seluruhnya, yang hilang cuma kenyamanan; tidak ada satu baris pun yang
jadi terlihat atau tersembunyi karenanya.

Kenapa **kode**, bukan nama
---------------------------
Location unik per company (`uniq_core_location_company_code`), jadi satu
lokasi fisik yang ditempati beberapa perusahaan berdiri sebagai beberapa
baris dengan **kode yang sama** — `JKT-HO` di MNI dan `JKT-HO` di MMR.
Nama bisa kebetulan sama tanpa maksud apa-apa ("Kantor Pusat" di dua
grup yang tidak berhubungan); kode adalah yang memang dipakai orang
untuk menyebut tempat yang sama. Karena itu pengelompokannya memakai
kode, dan nama cuma yang ditampilkan.
"""

from __future__ import annotations

from django.conf import settings


def _board_group_codes() -> list[str]:
    return [
        str(code).upper()
        for code in getattr(settings, "BOARD_EMPLOYEE_GROUPS", [])
    ]


def is_board_member(user) -> bool:
    """
    Pemegang akun ini duduk di Employee Group direksi?

    Dibaca dari `EmploymentAssignment.employee_group.code` dan
    dicocokkan ke `settings.BOARD_EMPLOYEE_GROUPS` — **bukan** dari
    username, role, jabatan, atau daftar nama di kode. Setiap pegawai
    yang group-nya memang direksi mendapat perilaku ini sendirinya, di
    tenant mana pun.

    Employee Group tetap tidak menentukan hak akses; lihat docstring
    modul.
    """
    from apps.hr.models import Employee

    codes = _board_group_codes()

    if not codes:
        return False

    if user is None or not getattr(user, "is_authenticated", False):
        return False

    try:
        employee = user.employee_profile
    except (Employee.DoesNotExist, AttributeError):
        return False

    employment = getattr(employee, "employment", None)
    group = getattr(employment, "employee_group", None)
    code = getattr(group, "code", "")

    return bool(code) and str(code).upper() in codes


def authorized_locations(user):
    """
    Seluruh Location yang boleh dilihat pemegang akun ini — **tanpa**
    pengelompokan.

    Memakai `LocationLookup` yang sama dengan dropdown-nya, lewat
    `scoped()` yang sengaja dipisah dari `apply_scope()`: yang terakhir
    sudah mengelompokkan per kode untuk direksi, dan pengelompokan itu
    justru yang tidak boleh ikut di sini — daftar ini yang dipakai
    memperluas pilihan, jadi ia harus memuat **semua** barisnya.
    """
    from apps.administration.api.organization.lookup.registry import (
        LocationLookup,
    )

    return LocationLookup.scoped(LocationLookup.get_queryset(), user)


def _same_code_ids(authorized, selected: set[int]) -> list[int]:
    """
    Id lokasi yang ber-kode sama dengan `selected`, **dari daftar yang
    dioper**.

    Kode dibaca dari baris yang memang ada di `authorized`, dan hasilnya
    juga diambil dari sana; kode yang sama di perusahaan di luar cakupan
    tidak punya jalan masuk. Kosong berarti tidak satu pun `selected`
    ada di cakupannya — pemanggil yang memutuskan artinya.
    """
    codes = set(
        authorized
        .filter(id__in=selected)
        .values_list("code", flat=True)
    )

    if not codes:
        return []

    return sorted(
        authorized
        .filter(code__in=codes)
        .values_list("id", flat=True)
    )


def self_filter_location_ids(user, location_id) -> list[int]:
    """
    Isi tombol "Lokasi Saya" untuk direksi: **tempat ia duduk**, di
    seluruh badan usaha yang boleh ia lihat.

    Direksi duduk di satu tempat fisik seperti orang lain — yang
    berbeda cuma tempat itu ditempati beberapa perusahaan sekaligus,
    jadi satu penempatan berdiri sebagai beberapa baris ber-kode sama.
    Tombolnya mengembalikan semuanya, dan berhenti di situ: lokasi lain
    dalam cakupannya **tidak** ikut. "Lokasi Saya" yang berarti seluruh
    cakupan sama saja dengan tanpa filter, dan tombol yang tidak
    mengubah angka tidak memberi tahu apa-apa.

    Kosong berarti penempatannya sendiri di luar cakupannya; pemanggil
    membiarkan nilai penempatannya berdiri apa adanya.
    """
    if location_id is None or not is_board_member(user):
        return []

    return _same_code_ids(authorized_locations(user), {int(location_id)})


def expand_location_selection(user, values) -> list:
    """
    Satu lokasi yang dipilih direksi berarti **seluruh lokasi ber-kode
    sama yang boleh ia lihat**.

    Dropdown-nya sudah menampilkan satu baris per kode, jadi tanpa ini
    memilih "Jakarta Head Office" cuma menjaring perusahaan yang
    kebetulan barisnya terpilih jadi wakil — dan angkanya keluar
    sebagian tanpa ada yang memberi tahu.

    **Tidak pernah memperluas cakupan.** Kode diambil dari baris yang
    memang ada di `authorized_locations`, dan hasilnya juga diambil dari
    daftar yang sama; kode yang sama di perusahaan di luar cakupan tidak
    punya jalan masuk. Id yang tidak dikenal dibiarkan apa adanya —
    `DataScopeService` pada queryset pegawainya yang menutupnya, dan itu
    memang penjaga yang sebenarnya.

    Untuk siapa pun selain direksi: dikembalikan apa adanya.
    """
    if not values or not is_board_member(user):
        return values

    selected = {
        int(value)
        for value in values
        if str(value).isdigit()
    }

    if not selected:
        return values

    expanded = _same_code_ids(authorized_locations(user), selected)

    if not expanded:
        # Tidak satu pun pilihannya ada di cakupannya. Dibiarkan apa
        # adanya supaya hasilnya tetap kosong, bukan diam-diam berubah
        # jadi "tanpa filter".
        return values

    return [str(value) for value in expanded]
