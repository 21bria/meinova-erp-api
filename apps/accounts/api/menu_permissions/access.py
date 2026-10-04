"""
Menghitung menu apa yang boleh dilihat seorang pengguna.

`RoleMenuPermission` sudah lama ada dan bisa dicentang di layar Security,
tapi **tidak ada satu baris kode pun yang membacanya** — persis nasib
`Role.permissions` sebelum `RolePermissionBackend`. Ini yang membacanya.

Aturannya sengaja dibalik dari yang paling kaku:

    Role **tanpa** satu pun baris menu = tanpa batasan.

Jadi tenant yang belum mengatur apa pun tidak mendadak kehilangan seluruh
sidebar-nya, dan role administratif tidak perlu dicentang satu per satu
setiap kali ada menu baru. Batasan baru berlaku begitu ada yang sengaja
mencentang — dan hanya untuk pemegang role itu.

Konsekuensi yang harus diingat: pengguna yang memegang **dua** role, satu
dibatasi dan satu tidak, melihat **semuanya**. Itu bukan kelalaian —
menambahkan role justru harus menambah akses, tidak pernah menguranginya.
Kalau seseorang tidak boleh melihat sesuatu, cabut role yang membolehkan.
"""

from __future__ import annotations

from apps.accounts.models import Menu, RoleMenuPermission


# Syarat yang dibaca dari **Feature Applicability** (`apps/hr/
# applicability.py`), bukan dari pola kerja (POLICY-1A). Kuncinya nilai
# `MenuVisibilityRule`, nilainya anggota `HRFeature` — sama persis, jadi
# penanda yang membuka menu adalah penanda yang sama dengan yang
# ditegakkan API dokumennya (`field_break` untuk Travel Request,
# `business_trip` untuk Business Trip).
#
# Arti tiap nilai **tidak bergantung pada rute**: `roster_only` di rute
# mana pun tetap keanggotaan roster, `field_break` di rute mana pun tetap
# penanda Employee Group.
FEATURE_RULES: dict[str, str] = {
    "field_break": "field_break",
    "business_trip": "business_trip",
}


class MenuAccessService:
    @staticmethod
    def visible_for(user) -> dict:
        """
        `{"unrestricted": bool, "routes": [...], "codes": [...]}`.

        `unrestricted` dikirim apa adanya supaya frontend tidak perlu
        menebak arti daftar kosong — "tidak boleh melihat apa pun" dan
        "belum diatur" adalah dua keadaan yang sangat berbeda dan
        keduanya menghasilkan daftar kosong.
        """
        everything = {"unrestricted": True, "routes": [], "codes": []}

        if user is None or not getattr(user, "is_authenticated", False):
            return {"unrestricted": False, "routes": [], "codes": []}

        if user.is_superuser:
            return everything

        roles = list(user.roles.filter(is_deleted=False).values_list("id", flat=True))

        if not roles:
            # Tanpa role sama sekali tidak berarti tanpa akses menu.
            # Penjagaan sebenarnya ada di API; sidebar hanya memilih apa
            # yang layak disodorkan.
            return everything

        permissions = (
            RoleMenuPermission.objects
            .filter(role_id__in=roles, is_deleted=False)
            .values_list("role_id", "menu_id", "can_view", "visibility_rule")
        )

        by_role: dict[int, set[int]] = {}

        # Syarat pola kerja dievaluasi **belakangan**, dan sengaja
        # dikumpulkan per baris: satu menu yang sama bisa datang dari dua
        # role dengan syarat berbeda, dan yang tanpa syarat harus menang.
        # Menambah role selalu menambah akses — aturan yang sama dengan
        # "satu role tanpa batasan membuka semuanya".
        rules: dict[int, set[str]] = {}

        for role_id, menu_id, can_view, rule in permissions:
            if not can_view:
                continue

            by_role.setdefault(role_id, set()).add(menu_id)

            rules.setdefault(menu_id, set()).add(rule or "always")

        # Satu saja role yang tidak dibatasi sudah membuka semuanya.
        if any(role_id not in by_role for role_id in roles):
            return everything

        allowed = set().union(*by_role.values()) if by_role else set()

        menus = list(
            Menu.objects
            .filter(pk__in=allowed, is_deleted=False)
            .values_list("id", "code", "route", "is_group")
        )

        blocked = MenuAccessService._blocked_by_rule(
            user=user,
            rules=rules,
        )

        codes = []
        routes = []

        for menu_id, code, route, is_group in menus:
            if menu_id in blocked:
                continue

            codes.append(code)

            if route and not is_group:
                routes.append(route)

        return {
            "unrestricted": False,
            "routes": sorted(set(routes)),
            "codes": sorted(set(codes)),
        }

    # ------------------------------------------------------------------
    # Syarat pola kerja
    # ------------------------------------------------------------------

    @staticmethod
    def _blocked_by_rule(*, user, rules) -> set[int]:
        """
        Menu yang dicabut karena pola kerja penggunanya tidak memenuhi
        syarat pada baris `RoleMenuPermission`.

        Travel Request adalah dokumen **kepulangan dari site**; pegawai
        kantor pusat tidak punya kepulangan untuk diajukan, jadi menunya
        cuma menyodorkan form yang tidak pernah sah untuknya. Site Visit
        nanti kebalikannya.

        Syaratnya tersimpan **per baris (role, menu)** dan bisa disunting
        dari layar Menu Permissions — bukan di settings, yang berarti
        tetap perlu rilis untuk mengubahnya.

        Satu menu bisa membawa beberapa syarat (dari beberapa role);
        **satu saja yang terpenuhi** sudah membukanya. Tiap syarat dinilai
        menurut nilainya sendiri, tidak menurut rutenya:

        * `roster_only` / `non_roster_only` — keanggotaan roster;
        * `field_break` / `business_trip` — `FEATURE_RULES`, penanda
          Employee Group pegawai pemilik akun.

        Nilai yang tidak dikenal tidak terpenuhi (tertutup), sama dengan
        perilaku sebelumnya.

        Ini **bukan penjagaan**: rutenya tetap bisa diketik dan API-nya
        tetap melayani. Yang menolak sungguhan adalah validasi dokumen.
        """
        from apps.accounts.models import MenuVisibilityRule

        conditional = {
            menu_id: menu_rules
            for menu_id, menu_rules in rules.items()
            # Satu baris tanpa syarat sudah cukup membuka menunya. Peran
            # yang membolehkan tanpa syarat tidak boleh dibatalkan oleh
            # peran lain yang mensyaratkan.
            if str(MenuVisibilityRule.ALWAYS) not in menu_rules
        }

        if not conditional:
            return set()

        has_roster = MenuAccessService._has_roster(user)

        def satisfies(rule: str) -> bool:
            if rule == str(MenuVisibilityRule.ROSTER_ONLY):
                return has_roster

            if rule == str(MenuVisibilityRule.NON_ROSTER_ONLY):
                return not has_roster

            feature = FEATURE_RULES.get(rule)

            if feature is not None:
                return MenuAccessService._feature_applies(user, feature)

            return False

        blocked: set[int] = set()

        for menu_id, menu_rules in conditional.items():
            if not any(satisfies(rule) for rule in menu_rules):
                blocked.add(menu_id)

        return blocked

    @staticmethod
    def _feature_applies(user, feature) -> bool:
        """
        Fitur ini berlaku untuk pegawai pemilik akun?

        Lewat `is_applicable()`, jadi pegawai tanpa employment atau tanpa
        Employee Group = berlaku (keadaan `BOTH`).

        Akun yang **bukan pegawai** = tidak terpenuhi, tanpa jalan pintas
        khusus. Itu pola yang sudah ada: `_has_roster` menganggapnya
        bukan beroster, dan `DataScopeService._placement` memberinya
        penempatan kosong. Akun administratif tidak bergantung pada ini —
        superuser dan role tanpa baris menu sudah `unrestricted`, dan
        role meja (HR/Admin Section) diseed `always`.
        """
        from apps.hr.applicability import is_applicable

        employee = getattr(user, "employee_profile", None)

        if employee is None:
            return False

        return is_applicable(employee, feature)

    @staticmethod
    def _has_roster(user) -> bool:
        """
        Pegawai ini menjalani roster.

        Dua penanda, karena ada dua jalur yang sama-sama sah:
        `roster_crew` (jalur lama, jangkar per gelombang) dan
        `roster_policy` (jalur dokumen Roster Setup). Memeriksa salah
        satunya saja membuat separuh pegawai site kehilangan menunya.

        Akun yang bukan pegawai (admin sistem) dianggap **tidak**
        beroster — tapi ia juga hampir tidak pernah memegang role
        `EMPLOYEE` saja, jadi tidak kehilangan apa pun.
        """
        employment = getattr(
            getattr(user, "employee_profile", None),
            "employment",
            None,
        )

        if employment is None:
            return False

        return bool(
            employment.roster_crew_id
            or employment.roster_policy_id
        )
