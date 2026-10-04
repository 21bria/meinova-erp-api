"""
Penyaringan data per baris berdasarkan **kewenangan per penugasan**.

Bedanya dengan dua lapis penjagaan lain, dan ini yang paling sering
tertukar:

* `ModelPermission` menjawab "boleh **mengubah** tabel ini?"
* `MenuAccessService` menjawab "menu ini disodorkan atau tidak?"
* Yang di sini menjawab "**baris yang mana** yang boleh dilihat?"

Hanya yang terakhir yang mencegah data bocor. Dua yang pertama tidak
menyembunyikan satu baris pun.

Semantiknya:

* **Tiap penugasan adalah satu cakupan yang utuh.** Di dalam satu
  penugasan, antar-jenis di-AND (company Karya Wijaya **dan** location
  Gebe); sesama jenis di-OR (location Gebe **atau** Jakarta HO).
* **Antar penugasan di-OR.** Orang yang memegang dua role melihat
  gabungan keduanya — tapi hanya dari penugasan yang **role-nya
  memberi izin yang diminta**, jadi izin satu role tidak pernah
  berjalan sejauh kewenangan role lain.

Tiga cara satu penugasan menentukan kewenangannya
(`RoleAssignment.authority_mode`):

* `unrestricted` — tanpa batasan, dinyatakan sengaja.
* `placement` — dihitung dari penempatan pemegangnya sendiri, sedalam
  `authority_level`. **Ini yang menghapus kebutuhan role per site:**
  yang disimpan aturannya ("sebatas lokasinya"), bukan nilainya
  ("Gebe").
* `explicit` — baris `RoleAssignmentAuthority` milik penugasan itu.
  **Tanpa baris berarti tanpa kewenangan**, bukan tanpa batasan.

Kosong = **tidak ada kewenangan**. Bukan lagi "ikuti konfigurasi Role
yang lama": penugasan dibuat jalur mana pun sudah diturunkan
kewenangannya saat lahir (`apps.accounts.signals`), jadi kosong hanya
bisa berarti baris peninggalan tenant yang belum di-backfill — dan itu
ditutup, bukan ditebak. Jalur kompatibilitas itu dibuang di Stage 4G
karena artinya berbahaya: `explicit` tanpa baris dibaca `Role` sebagai
tanpa batasan, jadi satu role baru membuka seluruh tenant.

Kolom cakupan pada `Role` dan tabel cakupan per-role/per-orang
**sudah dihapus** di gelombang C. Sampai stage itu keempatnya masih
ada tapi tidak dibaca satu baris pun di sini; sekarang tidak ada lagi
yang bisa dibaca. WHERE punya satu sumber, dan cuma satu.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q

from apps.accounts.models import (
    AuthorityMode,
    RoleAssignment,
)


logger = logging.getLogger(__name__)


# Jenis sumber daya yang benar-benar dipakai menyaring. `warehouse`,
# `project`, dan `iup` ada di `ResourceType` tapi modulnya belum ada;
# dibiarkan di luar sampai ada model yang bisa dipetakan.
SCOPE_TYPES = [
    "company",
    "branch",
    "location",
    "division",
    "department",
    "section",
    "cost_center",
]

OWN = "own"


def include_null() -> bool:
    """
    Baris yang kolom cakupannya kosong: ikut terlihat atau tidak?

    Bawaannya **tidak**. Di struktur organisasi ini hanya Company yang
    wajib, jadi Location boleh kosong — dan membiarkannya lolos berarti
    siapa pun yang lupa mengisi lokasi membuat datanya terbuka untuk
    semua role. Risiko sebaliknya nyata juga: data yang lokasinya belum
    diisi jadi tidak terlihat siapa pun kecuali superuser, tanpa pesan.
    Karena itu bisa dibalik lewat settings.
    """
    return bool(getattr(settings, "DATA_SCOPE_INCLUDE_NULL", False))


@dataclass
class DataScope:
    unrestricted: bool = True

    # Satu dict per role yang dibatasi: {jenis: {id, ...}} plus kunci
    # `own` bernilai True kalau role itu dibatasi ke data sendiri.
    role_scopes: list[dict] = field(default_factory=list)

    # Cakupannya benar-benar nihil — bukan "belum dipetakan".
    #
    # Dua keadaan itu wajib dibedakan, dan membingungkannya berbahaya
    # ke arah yang salah: `filter()` mengembalikan queryset **utuh**
    # saat tidak ada jenis yang cocok dengan peta viewset (itu memang
    # disengaja), jadi tanpa penanda ini role bermode `own` yang
    # penempatannya kosong justru membuka seluruh tenant.
    denied: bool = False

    def summary(self) -> dict:
        return {
            "unrestricted": self.unrestricted,
            "denied": self.denied,
            "scopes": [
                {
                    key: (sorted(value) if isinstance(value, set) else value)
                    for key, value in scope.items()
                }
                for scope in self.role_scopes
            ],
        }


def role_aware_enabled() -> bool:
    """
    Cakupan dihitung per izin, bukan per orang.

    Bawaannya **mati**. Menyalakannya menyempitkan akses, dan
    menyempitkan akses tanpa lebih dulu membuktikan role-nya memang
    memegang izin yang diperlukan akan mengunci orang dari pekerjaannya
    — kegagalan yang sama persis dengan menyalakan
    `ENFORCE_MODEL_PERMISSIONS` di tenant yang role-nya masih kosong.

    Urutan yang benar: seed izinnya, buktikan cakupannya lewat
    `audit_role_aware_coverage`, baru dinyalakan.

    **Bukan bypass permanen.** Begitu seluruh tenant terbukti tertutup,
    saklarnya dicabut bersama jalur lamanya — lihat catatan deprecation
    di `_build()`.
    """
    return bool(getattr(settings, "ROLE_AWARE_DATA_SCOPE", False))


class DataScopeService:
    @classmethod
    def for_user(cls, user, *, permission: str | None = None) -> DataScope:
        """
        Cakupan seseorang; kalau `permission` diisi, cakupan **untuk izin
        itu**.

        `permission` berbentuk `app_label.codename`, sama persis dengan
        yang dipakai `user.has_perm()` — satu kosakata untuk kedua
        pertanyaan, supaya "boleh membaca apa" dan "baris yang mana"
        tidak bisa berbeda pendapat soal nama izinnya.

        Diabaikan kalau `ROLE_AWARE_DATA_SCOPE` mati, jadi pemanggil
        boleh selalu mengirimkannya tanpa menunggu saklarnya menyala.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return DataScope(unrestricted=True)

        if user.is_superuser:
            return DataScope(unrestricted=True)

        if permission is not None and not role_aware_enabled():
            permission = None

        # Cache per izin. Sebelumnya satu nilai per orang, dan itu tidak
        # cukup lagi: dua izin yang berbeda sekarang boleh menghasilkan
        # dua jawaban yang berbeda dalam satu request yang sama.
        cache = getattr(user, "_data_scope_cache", None)

        if not isinstance(cache, dict):
            cache = {}

            user._data_scope_cache = cache

        if permission in cache:
            return cache[permission]

        scope = cls._build(user, permission=permission)

        cache[permission] = scope

        return scope

    @classmethod
    def _assignments_granting(cls, user, permission: str):
        """
        Penugasan milik `user` yang **role-nya** memberi `permission`.

        Satu query, dan sengaja lewat `Role.permissions` — bukan lewat
        `user.has_perm()`. `has_perm` menjawab "punya atau tidak" untuk
        orangnya; yang dibutuhkan di sini justru **role mana** yang
        memberikannya, dan itu pertanyaan yang tidak bisa dijawab
        gabungan.
        """
        app_label, _, codename = str(permission).partition(".")

        if not app_label or not codename:
            return []

        return list(
            RoleAssignment.objects
            .filter(
                user=user,
                role__is_deleted=False,
                role__permissions__content_type__app_label=app_label,
                role__permissions__codename=codename,
            )
            .select_related("role")
            .distinct()
        )

    # ------------------------------------------------------------------
    # Penyusunan
    # ------------------------------------------------------------------

    @classmethod
    def placement_for(cls, user) -> dict:
        """
        Penempatan organisasi pemegang akun — versi publiknya.

        Dipakai `/auth/me` supaya form bisa mengisi Company/Site/Section
        sendiri. Sengaja **terpisah** dari cakupan: penempatan menjawab
        "orang ini duduk di mana", cakupan menjawab "boleh melihat baris
        yang mana", dan HR pusat menunjukkan keduanya memang berbeda —
        ditempatkan di Jakarta, cakupannya seluruh tenant.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return {}

        return cls._placement(user)

    @staticmethod
    def _placement(user) -> dict:
        """
        Penempatan organisasi pemegang akun, untuk mode `own`.

        Dibaca dari `OrganizationAssignment` pegawainya. Akun tanpa
        pegawai (akun sistem, superuser yang bukan karyawan) tidak
        punya penempatan sama sekali — dan itu keadaan yang sah.
        """
        from apps.hr.models import Employee

        try:
            employee = user.employee_profile
        except Employee.DoesNotExist:
            return {}
        except AttributeError:
            return {}

        organization = getattr(employee, "organization", None)

        if organization is None:
            return {}

        placement = {}

        for name in SCOPE_TYPES:
            value = getattr(organization, f"{name}_id", None)

            if value is not None:
                placement[name] = value

        return placement

    @classmethod
    def _build(cls, user, *, permission: str | None = None) -> DataScope:
        """
        Cakupan dihitung dari **kewenangan per penugasan**.

        Yang menentukan WHERE bukan lagi konfigurasi milik `Role`,
        melainkan baris `RoleAssignment` — pasangan (orang, role).
        Itu yang membuat satu `HR-ADMIN` bisa berarti JKT-HO bagi satu
        orang dan SAGEA-MINE bagi yang lain tanpa role varian, dan yang
        membuat kewenangan tambahan menempel pada **kemampuan bisnis
        tertentu** alih-alih melebar ke setiap izin yang dipegang
        orangnya.

        `ROLE_AWARE_DATA_SCOPE` tetap menentukan hal yang sama seperti
        sebelumnya, dan hanya itu: apakah cakupannya disaring ke
        penugasan yang **role-nya memberi izin yang diminta**
        (`permission` diisi) atau dihitung dari seluruh penugasan
        (`permission=None`). Peralihan sumber WHERE ini tidak mengubah
        arti saklar tersebut.

        Cakupan **per-orang** yang lama tidak ada lagi. Barisnya dulu
        di-OR di atas cakupan seluruh role dan karena itu melebarkan
        setiap izin sekaligus — satu baris yang dimaksudkan untuk
        pengawasan kepegawaian ikut membuka slip gaji. Yang
        menggantikannya kewenangan pada penugasan yang tepat, jadi ia
        berlaku hanya untuk izin yang diberikan role penugasan itu.
        """
        if permission is not None:
            assignments = cls._assignments_granting(user, permission)

            if not assignments:
                # Tidak ada penugasan yang memberi izin ini. Ditutup,
                # bukan dibuka: tanpa izinnya tidak ada kewenangan yang
                # bisa dipinjam dari penugasan lain untuk
                # menjalankannya.
                #
                # Ini juga yang membuat pembaca di luar viewset —
                # yang merakit querysetnya sendiri dan karena itu tidak
                # melewati `ModelPermission` — ikut tertutup.
                return DataScope(unrestricted=False, denied=True)
        else:
            assignments = list(
                RoleAssignment.objects
                .filter(user=user, role__is_deleted=False)
                .select_related("role")
            )

        if not assignments:
            return DataScope(unrestricted=True)

        placement = None
        role_scopes = []

        for assignment in assignments:
            mode = assignment.authority_mode
            level = assignment.authority_level

            if not mode:
                # **Tertutup.** Dulu kosong berarti "ikuti konfigurasi
                # Role", dan justru itu lubangnya: `Role` bawaannya
                # `explicit` tanpa satu pun baris, yang pada `Role`
                # berarti *tanpa batasan* — jadi role baru mana pun
                # membuka seluruh tenant sampai ada yang menjalankan
                # backfill.
                #
                # Penugasan baru tidak bisa lagi sampai ke sini:
                # kewenangannya diturunkan saat dibuat, di jalur mana
                # pun. Yang masih kosong cuma peninggalan tenant yang
                # belum di-backfill, dan jawaban yang benar untuk
                # "kewenangannya belum diketahui" adalah tidak
                # memberikan apa-apa.
                logger.warning(
                    "Penugasan %s/%s belum punya kewenangan "
                    "(authority_mode kosong) — tidak memberi akses apa "
                    "pun. Nyatakan kewenangannya lewat layar Kewenangan "
                    "User Role; `audit_authority_hygiene` mendaftar "
                    "seluruh penugasan yang masih begini.",
                    getattr(user, "username", user.pk),
                    assignment.role.code,
                )

                continue

            if mode == AuthorityMode.UNRESTRICTED:
                # Satu penugasan tanpa batasan sudah membuka semuanya —
                # aturan yang sama dengan menu, dan disengaja: menambah
                # kewenangan harus menambah akses.
                return DataScope(unrestricted=True)

            if mode == AuthorityMode.PLACEMENT:
                if placement is None:
                    placement = cls._placement(user)

                value = placement.get(level)

                if value is None:
                    # Sengaja **tidak** dilonggarkan jadi tanpa batasan:
                    # melonggarkan diam-diam persis kebocoran yang mau
                    # dicegah. Pemegangnya jadi tidak melihat apa-apa
                    # lewat penugasan ini, dan sebabnya dicatat — kolom
                    # yang kosong di penempatannya, bukan konfigurasinya.
                    logger.warning(
                        "Penugasan %s/%s bermode 'placement' pada "
                        "tingkat %s, tapi penempatannya tidak punya "
                        "nilai itu — penugasan ini tidak memberi akses "
                        "apa pun.",
                        getattr(user, "username", user.pk),
                        assignment.role.code,
                        level or "(belum dipilih)",
                    )

                    continue

                role_scopes.append({level: {value}})

                continue

            # EXPLICIT. **Tanpa baris berarti tanpa kewenangan** —
            # kebalikan dari arti lamanya pada `Role`, dan itu memang
            # yang diperbaiki: baris yang hilang tidak boleh berarti
            # akses se-tenant. Penugasan ini tidak menyumbang apa pun.
            bucket = cls._authority_bucket(assignment)

            if not bucket:
                continue

            role_scopes.append(bucket)

        if not role_scopes:
            # Semua penugasannya bermode `placement` tanpa penempatan,
            # `explicit` tanpa baris, atau belum diturunkan sama sekali.
            # Ditutup, bukan dibuka.
            return DataScope(unrestricted=False, denied=True)

        return DataScope(unrestricted=False, role_scopes=role_scopes)

    @classmethod
    def _authority_bucket(cls, assignment) -> dict:
        """Baris kewenangan satu penugasan, jadi satu bucket."""
        return cls._bucket_from(
            assignment.authorities.values_list(
                "resource_type", "resource_id")
        )

    @staticmethod
    def _bucket_from(rows) -> dict:
        """`[(jenis, id)]` jadi `{jenis: {id, ...}}`."""
        bucket: dict = {}

        for resource_type, resource_id in rows:
            if resource_type == OWN:
                bucket[OWN] = True

                continue

            if resource_type not in SCOPE_TYPES or resource_id is None:
                continue

            bucket.setdefault(resource_type, set()).add(resource_id)

        return bucket

    @classmethod
    def implied_values(cls, user) -> dict[str, int]:
        """
        Nilai organisasi yang **tersirat** dari cakupan seseorang.

        Dipakai saat membuat data baru: admin yang cuma boleh melihat
        Gebe, kalau membuat pegawai tanpa mengisi Location, menyimpan
        baris yang seketika hilang dari layarnya sendiri — tersimpan
        (201), lalu 404 saat dibuka lagi. Dari kursinya itu terbaca
        seperti penyimpanan yang gagal, dan tidak ada pesan apa pun
        yang menjelaskannya.

        Hanya jenis yang nilainya **tunggal** yang dikembalikan. Dua
        role yang menunjuk dua lokasi berbeda tidak bisa disimpulkan
        jadi satu, dan menebak salah satunya lebih buruk daripada
        membiarkan kolomnya kosong — pemakainya masih bisa memilih
        sendiri, sedangkan tebakan yang salah menaruh pegawai di site
        yang bukan tempatnya bekerja.

        Yang tanpa batasan mengembalikan dict kosong: mereka memang
        boleh membuat pegawai di lokasi mana pun, dan mengisikan
        lokasinya sendiri justru menaruh pegawai site di kantor pusat.
        """
        scope = cls.for_user(user)

        if scope.unrestricted or scope.denied:
            return {}

        collected: dict[str, set] = {}

        for role_scope in scope.role_scopes:
            for resource_type, value in role_scope.items():
                if resource_type == OWN:
                    continue

                values = value if isinstance(value, set) else {value}

                collected.setdefault(resource_type, set()).update(values)

        return {
            resource_type: next(iter(values))
            for resource_type, values in collected.items()
            if len(values) == 1
        }

    @classmethod
    def filter(
        cls,
        queryset,
        mapping: dict | None,
        user,
        *,
        allow_null=None,
        required_permission: str | None = None,
    ):
        """
        Menyaring queryset memakai peta `{jenis: jalur ORM}` milik viewset.

        Jenis yang **tidak ada di peta dilewati**, bukan menolak semua:
        model yang tidak menyimpan section tidak bisa dipersempit ke
        section, dan menolak seluruh barisnya akan mengosongkan layar
        tanpa sebab yang bisa dijelaskan. Konsekuensinya cakupan yang
        lebih dalam dari yang dikenal model hanya berlaku sejauh yang
        bisa dipetakan — itu batas yang harus disadari saat memetakan
        model baru.

        `allow_null` menimpa `DATA_SCOPE_INCLUDE_NULL` untuk satu
        pemanggilan. Dipakai model yang memang memakai kolom kosong
        sebagai "berlaku lintas organisasi" — program training tanpa
        company, misalnya. Jangan dipakai sebagai jalan pintas kalau
        kosongnya cuma karena datanya belum diisi.

        `required_permission` (`app_label.codename`) membuat cakupannya
        dihitung **hanya dari role yang memberi izin itu**. Pemanggil
        yang tidak mengirimkannya mendapat perilaku lama persis seperti
        sebelumnya, jadi peluncurannya bisa satu resource demi satu
        resource — bukan sekaligus di 25 pemanggil.
        """
        if not mapping:
            # Tanpa peta, izin pun tidak menyaring apa pun di sini. Yang
            # menjaga resource semacam itu `ModelPermission`; `filter()`
            # menyaring baris, bukan menolak request.
            return queryset

        scope = cls.for_user(user, permission=required_permission)

        if scope.unrestricted:
            return queryset

        # Cakupannya nihil, bukan "belum dipetakan". Ditutup di sini,
        # sebelum peta viewset ikut dipertimbangkan — kalau tidak,
        # model yang kebetulan tidak menyimpan jenis apa pun yang
        # dicakup akan lolos utuh.
        if scope.denied:
            return queryset.none()

        allow_null = include_null() if allow_null is None else bool(allow_null)

        combined = Q()
        matched = False

        for role_scope in scope.role_scopes:
            role_q = Q()
            applied = False

            for resource_type, value in role_scope.items():
                path = mapping.get(resource_type)

                if not path:
                    continue

                if resource_type == OWN:
                    role_q &= Q(**{path: getattr(user, "pk", None)})
                    applied = True

                    continue

                condition = Q(**{f"{path}__in": sorted(value)})

                if allow_null:
                    condition |= Q(**{f"{path}__isnull": True})

                role_q &= condition
                applied = True

            if applied:
                combined |= role_q
                matched = True

        if not matched:
            return queryset

        return queryset.filter(combined)
