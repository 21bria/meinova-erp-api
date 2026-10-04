"""
Satu-satunya jalan dari `request.user` ke pegawainya untuk `/api/me/*`.

Kontraknya:

    authenticated user → linked Employee → is_deleted=False → is_active=True

**Tidak pernah menerima identitas dari client.** Tidak lewat URL, query
param, maupun body. Itu yang membuat `/me` berarti "pegawai yang sedang
login" dan bukan "pegawai yang id-nya kebetulan diketik di URL" — dan
satu-satunya cara menjaminnya adalah tidak pernah menyediakan
parameternya sama sekali.

**Tidak bergantung pada `hr.view_employee`, `DataScopeService`, atau
role HR mana pun.** Ini sumbu yang berbeda: cakupan administratif
menjawab "boleh melihat baris siapa", identitas Self Service menjawab
"baris ini memang dirinya". Mencampurnya menghasilkan dua kesalahan yang
sama-sama nyata — HR Admin bercakupan luas membuka `/me` lalu melihat
orang lain, dan pegawai yang cakupannya dipersempit kehilangan halaman
profilnya sendiri.

Kenapa query eksplisit, bukan `user.employee_profile`
-----------------------------------------------------
Accessor reverse OneToOne itu dipakai di belasan tempat lain di sistem
ini, dan **tidak satu pun menyaring `is_deleted`**: `BaseModel` tidak
memasang manager kustom, jadi kartu pegawai yang sudah di-soft-delete
tetap dikembalikan accessor-nya seolah masih berlaku. Untuk Self Service
itu bukan ketidakrapian melainkan kebocoran — orang yang kartunya
dihapus HR tetap membuka profilnya, lengkap dengan penempatannya.

Yang di luar Self Service sengaja **tidak** ikut diubah; lihat
`docs/claude/self-service.md` → FOLLOW-UP: CURRENT EMPLOYEE RESOLVER
CONSOLIDATION.

Catatan tentang `user_id` yang tetap terpakai
--------------------------------------------
`Employee.user` sebuah `OneToOneField`, jadi constraint UNIQUE-nya
berlaku untuk **seluruh** baris termasuk yang sudah di-soft-delete.
Akibatnya satu akun tidak bisa ditautkan ke kartu pegawai baru selama
kartu lamanya belum di-restore atau di-hard-delete. Itu perilaku yang
sudah ada sebelum berkas ini dan tidak diubah di sini — dicatat karena
ia yang menjamin query di bawah mengembalikan paling banyak satu baris.
"""

from __future__ import annotations

from rest_framework.exceptions import NotAuthenticated

from apps.self_service.exceptions import (
    EmployeeInactive,
    EmployeeNotLinked,
)


# Relasi yang dipakai layar Self Service, diambil sekali di sini.
#
# Daftarnya panjang, dan itu pilihan sadar: `/api/me/profile/` menyentuh
# dua puluh master sekaligus, dan tanpa ini tiap satu jadi query
# tersendiri — dua puluh satu query untuk satu halaman yang membaca
# **satu** baris pegawai. Sebagai JOIN pada pencarian satu baris,
# ongkosnya tidak terasa; sebagai dua puluh perjalanan bolak-balik, ia
# terasa di setiap pembukaan halaman.
#
# Konsekuensinya `/api/me/` yang cuma butuh identitas ikut membayar
# JOIN-nya. Itu ditanggung dengan sengaja: satu resolver kanonik yang
# kadang mengambil lebih dari yang dipakai lebih mudah dijaga benar
# daripada dua resolver yang harus tetap sepakat tentang siapa pegawai
# yang sedang login.
_RELATED = (
    "user",
    "avatar_file",

    "gender",
    "religion",
    "nationality",
    "blood_type",
    "marital_status",

    "province",
    "city",
    "district",
    "village",

    "organization",
    "organization__company",
    "organization__branch",
    "organization__location",
    "organization__division",
    "organization__department",
    "organization__section",
    "organization__position",
    "organization__job_level",
    "organization__job_grade",
    "organization__cost_center",
    "organization__reports_to",

    "employment",
    "employment__employment_status",
    "employment__employment_type",
)

# Kunci cache pada objek request. Satu request bisa menyentuh resolver
# lebih dari sekali — permission class menanyakannya, lalu view-nya
# menanyakannya lagi — dan tanpa ini keduanya jadi dua query untuk
# jawaban yang mustahil berbeda.
_CACHE_ATTR = "_self_service_employee"


class CurrentEmployeeService:
    """Pegawai di balik akun yang sedang login."""

    @staticmethod
    def _authenticated(user) -> bool:
        return user is not None and bool(
            getattr(user, "is_authenticated", False)
        )

    @classmethod
    def resolve(cls, user):
        """
        Pegawai milik `user`, atau melempar sebab yang menjelaskan.

        Melempar:

        * `NotAuthenticated` (401) — tidak ada yang login
        * `EmployeeNotLinked` (404) — akun tanpa kartu pegawai, termasuk
          akun yang kartunya sudah di-soft-delete
        * `EmployeeInactive` (403) — kartunya ada, statusnya nonaktif

        Kartu yang di-soft-delete sengaja dibalas `EmployeeNotLinked`,
        bukan sebab tersendiri: dari kursi yang membacanya, kartu yang
        dihapus dan kartu yang tidak pernah ada adalah keadaan yang
        sama, dan membedakannya justru memberi tahu bahwa dulu pernah
        ada.
        """
        if not cls._authenticated(user):
            raise NotAuthenticated()

        # Import di dalam fungsi: `apps.hr` memuat `apps.self_service`
        # lebih dulu di sebagian jalur, dan import model di tingkat
        # modul membuat urutan pemuatan app menentukan apakah berkas ini
        # bisa di-import.
        from apps.hr.models import Employee

        employee = (
            Employee.objects
            .filter(
                user=user,
                is_deleted=False,
            )
            .select_related(*_RELATED)
            .first()
        )

        if employee is None:
            raise EmployeeNotLinked()

        if not employee.is_active:
            raise EmployeeInactive()

        return employee

    @classmethod
    def resolve_or_none(cls, user):
        """
        Bentuk yang tidak melempar, untuk pemanggil yang memang boleh
        tidak punya pegawai — badge sidebar, penghitung notifikasi.

        **Bukan** untuk endpoint `/me/*`: di sana ketiadaan pegawai
        adalah jawaban yang harus terbaca pemakainya, bukan keadaan yang
        dilewati diam-diam.
        """
        try:
            return cls.resolve(user)
        except (NotAuthenticated, EmployeeNotLinked, EmployeeInactive):
            return None

    @classmethod
    def for_request(cls, request):
        """
        Seperti `resolve()`, tapi hasilnya disimpan pada `request`.

        Dipakai permission class dan view dalam satu request yang sama.
        Kalau resolusinya melempar, yang dilempar **tidak** di-cache:
        sebab kegagalan tidak perlu diingat, dan menyimpannya membuat
        alurnya lebih sulit dibaca daripada satu query ulang.
        """
        cached = getattr(request, _CACHE_ATTR, None)

        if cached is not None:
            return cached

        employee = cls.resolve(getattr(request, "user", None))

        setattr(request, _CACHE_ATTR, employee)

        return employee
