"""
Jenis sumber daya untuk kewenangan data — milik arsitektur yang sekarang.

Nilainya **tidak baru**. Ia lahir di model cakupan per-role yang lama,
dan sampai Stage 4I `RoleAssignmentAuthority` — model yang
menggantikannya — masih meminjam pilihannya dari sana. Ketergantungan
itu terbalik arahnya: model pengganti tidak boleh runtuh saat model yang
digantikannya dihapus, dan sebelum berkas ini ada, penghapusan itu akan
ikut membawa definisi field penggantinya.

Jadi rumahnya dipindahkan lebih dulu, bukan isinya diubah. Nilai dan
labelnya sama persis — termasuk urutannya — supaya `makemigrations`
tidak melihat selisih apa pun dan tidak ada satu baris data pun yang
perlu ditulis ulang. Model lamanya kemudian dihapus di gelombang C, dan
pemindahan inilah yang membuat penghapusan itu tidak menyentuh apa pun
di sini.

`warehouse`, `project`, dan `iup` tetap dideklarasikan dan tetap **tidak
dipakai menyaring**: modulnya belum ada, dan `SCOPE_TYPES` di
`apps.accounts.scoping` yang memutuskan jenis mana yang benar-benar
menyaring. Membuangnya dari sini akan menjadikannya nilai tak dikenal
bagi baris lama yang mungkin sudah menyimpannya — penghapusan nilai,
bukan pemindahan rumah.
"""

from django.db import models


class AuthorityResourceType(models.TextChoices):
    """Jenis sumber daya yang bisa disebut sebuah baris kewenangan.

    `own` bukan organisasi: ia berarti "baris yang `user_id`-nya saya",
    data diri sendiri. Sengaja tidak dinamai ulang meski satu daftar
    dengan company/branch/location — mengubah nilainya berarti menulis
    ulang data, dan namanya sudah dipakai baris yang ada.
    """

    COMPANY = "company", "Company"
    BRANCH = "branch", "Branch"
    LOCATION = "location", "Location"
    DIVISION = "division", "Division"
    DEPARTMENT = "department", "Department"
    SECTION = "section", "Section"
    COST_CENTER = "cost_center", "Cost Center"
    WAREHOUSE = "warehouse", "Warehouse"
    PROJECT = "project", "Project"
    IUP = "iup", "IUP"
    OWN = "own", "Own Data"
