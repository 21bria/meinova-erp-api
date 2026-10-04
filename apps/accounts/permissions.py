"""
Penjagaan endpoint Security.

Membuat user, memberi role, dan mengubah hak akses adalah wewenang
paling berbahaya di sistem — yang memegangnya bisa memberi dirinya role
apa pun, termasuk yang membuka seluruh data tenant. Selama ini
endpoint-nya cuma `IsAuthenticated`: setiap pegawai yang bisa login
bisa melakukannya.
"""

from __future__ import annotations

from django.conf import settings

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.capabilities import can_manage_security


class CanManageSecurity(BasePermission):
    """
    Baca terbuka untuk yang login, tulis hanya untuk yang berhak.

    Baca dibiarkan terbuka karena beberapa layar sah membutuhkannya —
    dropdown "pilih pengguna" di konfigurasi alur, misalnya, dan daftar
    role di layar delegasi. Yang dijaga perubahannya.
    """

    message = (
        "Hanya superuser atau pemegang role administrator keamanan yang "
        "boleh mengubah pengguna, role, dan hak akses."
    )

    def has_permission(self, request, view) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            return False

        if request.method in SAFE_METHODS:
            return True

        return can_manage_security(request.user)


class IsSecurityAdmin(BasePermission):
    """
    Baca **dan** tulis hanya untuk yang berhak.

    Untuk layar yang isinya sendiri sudah sensitif — pemetaan hak data
    per role menunjukkan siapa boleh melihat company mana, dan itu peta
    yang berguna bagi orang yang mau menyalahgunakannya.
    """

    message = CanManageSecurity.message

    def has_permission(self, request, view) -> bool:
        return can_manage_security(request.user)


# Aksi CRUD baku -> kata kerja izin Django. Hanya lima ini yang dijaga;
# lihat alasannya di `ModelPermission`.
ACTION_VERBS = {
    "create": "add",
    "update": "change",
    "partial_update": "change",
    "destroy": "delete",
    "bulk_delete": "delete",
}


# Aksi baca yang tetap terbuka pada resource sensitif sekalipun.
#
# `ui_schema_view` mengembalikan **definisi kolom**, bukan satu pun
# baris, dan ia sengaja ber-`AllowAny`: generator modul frontend
# membacanya tanpa login. Menjaganya dengan `view_*` akan mematikan
# generator untuk setiap resource yang baru saja dinyatakan sensitif —
# kegagalan yang bunyinya jauh dari sebabnya, karena yang hilang bukan
# datanya melainkan kemampuan membangun layarnya.
READ_EXEMPT_ACTIONS = frozenset({"ui_schema_view"})


def view_permission_for(model) -> str | None:
    """
    Nama izin baca sebuah model — `app_label.view_model`, atau `None`.

    **Satu-satunya tempat nama itu dibentuk di seluruh sistem.** Bukan
    kemewahan: `ModelPermission` memakainya untuk menolak request
    (WHAT) dan `DataScopeService` untuk memilih role mana yang
    menyumbang cakupan (WHERE). Kalau ada dua tempat yang menyusunnya,
    satu perubahan nama model menggeser salah satunya saja — dan
    hasilnya bukan error, melainkan gerbang yang menjaga izin yang
    berbeda dari yang disaring cakupannya. Diamnya sempurna.

    Dipisah dari `required_view_permission()` karena permukaan baca di
    luar viewset — dashboard, laporan, export, lookup, resolver
    importer — tidak punya `view` untuk ditanyai; yang mereka pegang
    modelnya. Itu Stage 3B: **satu sumber WHAT, satu
    `DataScopeService` untuk WHERE.**
    """
    if model is None:
        return None

    meta = model._meta

    return f"{meta.app_label}.view_{meta.model_name}"


def required_view_permission(view) -> str | None:
    """
    Nama izin baca sebuah viewset — `app_label.view_model`, atau `None`.

    **Satu tempat, dua pemakai.** `ModelPermission` memakainya untuk
    menolak request (WHAT), `DataScopeService` untuk memilih role mana
    yang menyumbang cakupan (WHERE). Kalau keduanya membentuk namanya
    sendiri-sendiri, satu perubahan nama model akan menggeser salah
    satunya saja — dan hasilnya bukan error melainkan gerbang yang
    menjaga izin yang berbeda dari yang disaring cakupannya.

    `None` untuk viewset yang bacanya memang tidak dijaga; pemanggilnya
    kemudian jatuh ke perilaku lama, dan itu yang membuat peluncurannya
    bisa satu resource demi satu resource.
    """
    if not getattr(view, "require_view_permission", False):
        return None

    return view_permission_for(ModelPermission._model(view))


def required_scope_permission(view) -> str | None:
    """
    Izin yang **mengotorisasi aksi yang sedang berjalan** — untuk cakupan.

    Membaca dan menulis dijaga izin yang berbeda, jadi cakupannya juga
    harus dihitung dari izin yang berbeda. Sebelum ini semua aksi
    memakai `required_view_permission()`, dan untuk 37 viewset yang
    bacanya tidak dijaga nilainya `None` — yang di
    `DataScopeService` berarti **gabungan seluruh penugasan**. Akibatnya
    hak baca yang luas ikut melebarkan hak ubah dan hapus: pemegang
    EMPLOYEE (`own`) + FINANCE-MANAGER (se-company) terbukti bisa
    menyetujui dan menghapus cuti 45 orang lain di tenant demo.

    Aturannya sekarang:

    * `update`/`partial_update` -> `change_<model>`
    * `destroy`/`bulk_delete`   -> `delete_<model>`
    * aksi kustom yang dinyatakan viewset -> izin/kemampuan aksi itu
      (`action_scope_permissions`)
    * selebihnya (baca, `@action` biasa) -> `required_view_permission()`,
      persis seperti sebelumnya.

    `create` sengaja tidak ada: ia tidak pernah melewati
    `filter_queryset()` sama sekali. Subjek create dijaga di batas API
    oleh `EmployeeSubjectWriteGuardMixin`, dengan izin `add_<model>` dan
    aturan yang sama.

    **Aksi kustom tidak diserempet.** `submit/`, `approve/`, `export/`,
    dan kawan-kawannya tidak ada di `ACTION_VERBS`, jadi mereka tetap
    memakai semantik baca yang lama. Menyeretnya ke izin tulis akan
    mengunci approver dari dokumen yang justru ditagihkan kepadanya.

    Catatan penting soal saklar: seperti seluruh jalur cakupan, nama
    izin ini **diabaikan** `DataScopeService` selama
    `ROLE_AWARE_DATA_SCOPE` mati — lihat `for_user()`. Pemilihan izin
    di sini benar untuk kedua keadaan saklar; yang menegakkannya baru
    menyala bersama saklarnya.
    """
    action = getattr(view, "action", None) or ""

    declared = getattr(view, "action_scope_permissions", None) or {}

    if action in declared:
        return declared[action]

    verb = ACTION_VERBS.get(action)

    if verb in ("change", "delete"):
        model = ModelPermission._model(view)

        if model is None:
            return None

        meta = model._meta

        return f"{meta.app_label}.{verb}_{meta.model_name}"

    return required_view_permission(view)


class ModelPermission(BasePermission):
    """
    Baca terbuka, tulis mengikuti izin per model milik role pengguna.

    Ini penjagaan yang **fleksibel**: aturannya tidak ditanam di kode
    melainkan dicentang di layar Roles, jadi tenant yang mau memberi
    admin site hak mengubah master HR tapi bukan master keuangan tidak
    perlu menunggu rilis.

    Tiga keputusan yang sengaja diambil:

    1. **Hanya aksi CRUD baku yang dijaga.** Endpoint `@action` seperti
       `submit/`, `approve/`, atau `sync/` punya aturannya sendiri yang
       jauh lebih spesifik daripada "boleh mengubah tabel ini" —
       pegawai berhak mengajukan cutinya sendiri tanpa perlu izin
       mengubah tabel cuti seisi perusahaan. Menyeret aksi itu ke sini
       akan mengunci orang dari dokumennya sendiri.
    2. **Membaca dibiarkan terbuka — kecuali yang menyatakan diri
       sensitif.** Dropdown, lookup, dan schema dipakai lintas modul
       oleh orang yang tidak berkepentingan mengubahnya, dan menutupnya
       semua akan mengunci hampir setiap layar: hari ini `EMPLOYEE`
       hanya punya `view_*` untuk 7 dari 152 model yang ada di balik
       endpoint.

       Yang **tidak** benar adalah membiarkan aturan itu berlaku juga
       untuk slip gaji dan rekening bank. Resource semacam itu
       menyatakan dirinya lewat `require_view_permission = True`, dan
       hanya resource itu yang bacanya ikut dijaga izin model.

       Perlu dua-duanya, dan urutannya penting: izin menjawab **jenis
       data apa** yang boleh dibaca, cakupan (kewenangan
       `RoleAssignment`) menjawab **baris milik siapa**. Punya izin tanpa cakupan berarti
       membaca slip gaji seluruh tenant; punya cakupan tanpa izin
       berarti "kebetulan satu lokasi" cukup untuk membuka gaji orang.
       Karena itu setiap viewset ber-`require_view_permission` wajib
       juga punya `data_scope` — dijaga sebuah test, bukan kesepakatan
       lisan.
    3. **Bisa dimatikan lewat settings.** `ENFORCE_MODEL_PERMISSIONS`
       ada supaya tenant yang role-nya belum diisi tidak mendadak
       read-only seluruhnya; matikan, isi role-nya, lalu nyalakan.
       `ENFORCE_VIEW_PERMISSIONS` melakukan hal yang sama khusus untuk
       penjagaan baca — saklarnya terpisah karena izin baca baru
       diseed belakangan, jadi tenant yang seed-nya belum diperbarui
       harus bisa mematikannya sendiri tanpa ikut membuka izin tulis.
    """

    message = (
        "Anda tidak punya hak untuk mengubah data ini. Hubungi "
        "administrator untuk menambahkannya ke role Anda."
    )

    def has_permission(self, request, view) -> bool:
        if not getattr(settings, "ENFORCE_MODEL_PERMISSIONS", True):
            return True

        if not getattr(view, "enforce_model_permissions", True):
            return True

        if request.method in SAFE_METHODS:
            return self._may_read(request, view)

        verb = ACTION_VERBS.get(getattr(view, "action", None) or "")

        if verb is None:
            return True

        user = request.user

        if not getattr(user, "is_authenticated", False):
            return False

        model = self._model(view)

        if model is None:
            # Tanpa model tidak ada nama izin yang bisa dibentuk.
            # Membiarkannya lewat lebih benar daripada menolak semua —
            # view seperti ini punya penjagaannya sendiri.
            return True

        meta = model._meta

        return user.has_perm(f"{meta.app_label}.{verb}_{meta.model_name}")

    def _may_read(self, request, view) -> bool:
        """
        Penjagaan baca, dan **hanya** untuk yang memintanya.

        Bawaannya tetap terbuka. Yang berubah cuma satu hal: resource
        yang menyatakan `require_view_permission = True` sekarang
        menuntut `view_<model>` seperti halnya menulis menuntut
        `change_<model>`.

        Aksi `@action` sengaja tidak dibedakan di sini — berbeda dari
        sisi tulis, di mana `submit/` dan `approve/` punya aturannya
        sendiri. Aksi baca pada resource sensitif (`export/`,
        `summary/`, `print/`) mengeluarkan isi baris yang sama dengan
        `list/`, jadi meloloskannya akan menyisakan pintu yang persis
        sebesar pintu yang baru saja ditutup.
        """
        if not getattr(settings, "ENFORCE_VIEW_PERMISSIONS", True):
            return True

        if not getattr(view, "require_view_permission", False):
            return True

        if getattr(view, "action", None) in READ_EXEMPT_ACTIONS:
            return True

        user = request.user

        if not getattr(user, "is_authenticated", False):
            return False

        self.message = (
            "Anda tidak punya hak untuk membaca data ini. Hubungi "
            "administrator untuk menambahkannya ke role Anda."
        )

        # Nama izinnya dibentuk `required_view_permission()`, satu-satunya
        # tempat yang membentuknya — jalur cakupan memakai fungsi yang
        # sama, jadi keduanya mustahil menjaga izin yang berlainan.
        permission = required_view_permission(view)

        if permission is None:
            # Sama seperti sisi tulis: tanpa model tidak ada nama izin
            # yang bisa dibentuk. Bedanya di sini menolak lebih aman
            # daripada meloloskan — viewset yang sengaja meminta
            # dijaga tapi tidak punya model adalah salah konfigurasi,
            # dan salah konfigurasi pada resource sensitif tidak boleh
            # berakhir "terbuka untuk semua".
            return False

        return user.has_perm(permission)

    @staticmethod
    def _model(view):
        queryset = getattr(view, "queryset", None)

        if queryset is None:
            get_queryset = getattr(view, "get_queryset", None)

            if get_queryset is None:
                return None

            try:
                queryset = get_queryset()
            except Exception:
                return None

        return getattr(queryset, "model", None)
