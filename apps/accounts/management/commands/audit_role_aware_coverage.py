"""
Siapa yang kehilangan akses kalau `ROLE_AWARE_DATA_SCOPE` dinyalakan.

Menyalakan cakupan per-izin **menyempitkan** akses, dan menyempitkan
akses tanpa tahu siapa yang terkena adalah cara membuat orang kehilangan
pekerjaannya di hari rilis. Perintah ini menjawabnya sebelum saklarnya
disentuh: untuk tiap resource sensitif, siapa yang hari ini membaca
barisnya karena **meminjam** cakupan role lain.

Tidak menulis apa pun. Aman dijalankan di tenant mana pun, kapan pun.

    python manage.py tenant_command audit_role_aware_coverage --schema=demo

Membaca hasilnya:

* **PINJAM** — orang ini membaca baris lewat cakupan role yang tidak
  memberi izinnya. Begitu saklarnya menyala, barisnya menyempit. Itu
  memang maksudnya; yang perlu dipastikan penyempitannya tidak
  memotong pekerjaan yang sah.
* **HILANG** — orang ini kehilangan **seluruh** aksesnya, karena tidak
  satu pun role-nya memberi izin itu. Ini yang harus diperiksa satu per
  satu: kalau pekerjaannya memang membutuhkannya, yang kurang izinnya —
  bukan saklarnya yang salah.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.urls import get_resolver

from apps.accounts.scoping import DataScopeService
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.permissions import _model_of


def _subclasses(cls):
    found = []

    for subclass in cls.__subclasses__():
        found.append(subclass)
        found.extend(_subclasses(subclass))

    return found


class Command(BaseCommand):
    help = (
        "Melaporkan siapa yang menyempit aksesnya kalau "
        "ROLE_AWARE_DATA_SCOPE dinyalakan. Tidak mengubah apa pun."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--writes",
            action="store_true",
            help=(
                "Memeriksa sisi **tulis**: siapa yang menyempit "
                "cakupan ubah/hapus/terbitnya kalau saklarnya menyala. "
                "Sejak `required_scope_permission()` dipakai "
                "`filter_queryset()`, izin tulis ikut menentukan baris "
                "— dan berbeda dari sisi baca, resource tulis tidak "
                "perlu `require_view_permission` untuk terkena."
            ),
        )

        parser.add_argument(
            "--surfaces",
            action="store_true",
            help=(
                "Ikut menghitung **baris** pada permukaan baca yang "
                "sudah dipindahkan Stage 3B (dashboard, laporan, "
                "dropdown). Lebih lambat — satu query per akun per "
                "permukaan — tapi ini satu-satunya yang bisa menjawab "
                "berapa yang hilang, bukan sekadar siapa."
            ),
        )

    def handle(self, *args, **options):
        # `__subclasses__` hanya menemukan yang sudah diimpor. Dari
        # management command URLconf-nya belum tentu termuat, dan daftar
        # kosong di sini terbaca persis seperti "tidak ada yang terkena".
        get_resolver().url_patterns

        User = get_user_model()

        if options.get("writes"):
            self.report_writes(User)

        if options.get("surfaces"):
            self.report_surfaces(User)

        gated = []

        for view_class in _subclasses(BaseMasterViewSet):
            if not getattr(view_class, "require_view_permission", False):
                continue

            scope_map = getattr(view_class, "data_scope", None)

            if not scope_map:
                continue

            # `_model_of`, **bukan** `required_view_permission()`: yang
            # kedua menerima instance dan jatuh ke `get_queryset()`.
            # Dipanggil pada kelas, `get_queryset()` jalan tanpa `self`
            # → TypeError → tertangkap → `None` untuk semua viewset, dan
            # hasilnya laporan kosong yang terbaca seperti "aman".
            model = _model_of(view_class)

            if model is None:
                continue

            meta = model._meta

            gated.append((
                view_class,
                f"{meta.app_label}.view_{meta.model_name}",
                scope_map,
            ))

        if not gated:
            self.stdout.write(
                self.style.WARNING(
                    "Tidak ada resource ber-`require_view_permission` — "
                    "tidak ada yang bisa diperiksa."
                )
            )

            return

        self.stdout.write(
            f"Resource sensitif yang diperiksa: {len(gated)}\n"
        )

        users = list(
            User.objects
            .filter(is_active=True, is_superuser=False)
            .order_by("username")
        )

        borrowing = 0
        losing = 0

        for view_class, permission, scope_map in sorted(
            gated,
            key=lambda item: item[1],
        ):
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{permission}"))

            reported = False

            for user in users:
                # Cache-nya per instance, jadi dua panggilan di bawah
                # tidak saling mencemari selama user-nya objek yang sama.
                legacy = DataScopeService.for_user(user)

                aware = DataScopeService._build(user, permission=permission)

                if not user.has_perm(permission):
                    # Sudah ditolak `ModelPermission` sejak Stage 1;
                    # bukan perubahan yang dibawa saklar ini.
                    continue

                verdict = self._compare(legacy, aware)

                if verdict is None:
                    continue

                reported = True

                if verdict == "HILANG":
                    losing += 1

                    style = self.style.ERROR
                else:
                    borrowing += 1

                    style = self.style.WARNING

                roles = ", ".join(
                    role.code for role in user.roles.filter(is_deleted=False)
                )

                self.stdout.write(
                    style(f"  {verdict:7} {user.username:24} [{roles}]")
                )

            if not reported:
                self.stdout.write("  (tidak ada yang menyempit)")

        self.stdout.write("")

        if losing:
            self.stdout.write(
                self.style.ERROR(
                    f"{losing} akun kehilangan seluruh akses pada salah satu "
                    "resource. Periksa dulu apakah pekerjaannya memang "
                    "membutuhkannya — kalau ya, izinnya yang kurang."
                )
            )

        if borrowing:
            self.stdout.write(
                self.style.WARNING(
                    f"{borrowing} akun menyempit cakupannya (berhenti "
                    "meminjam cakupan role lain). Itu maksud perubahannya."
                )
            )

        if not losing and not borrowing:
            self.stdout.write(
                self.style.SUCCESS(
                    "Tidak ada yang terkena. ROLE_AWARE_DATA_SCOPE aman "
                    "dinyalakan untuk tenant ini."
                )
            )

    @staticmethod
    def _compare(legacy, aware) -> str | None:
        """
        Bedanya, sebagai satu kata — atau `None` kalau tidak berubah.

        Sengaja membandingkan **bentuk** cakupannya, bukan menghitung
        baris: menghitung baris berarti satu query per orang per
        resource, dan yang perlu diketahui sebelum menyalakan saklar
        adalah siapa yang berubah, bukan berapa barisnya.
        """
        if aware.denied and not legacy.denied:
            return "HILANG"

        if legacy.unrestricted and not aware.unrestricted:
            return "PINJAM"

        if aware.unrestricted or legacy.denied:
            return None

        def shape(scope):
            return sorted(
                tuple(sorted(
                    (key, tuple(sorted(value)) if isinstance(value, set)
                     else value)
                    for key, value in bucket.items()
                ))
                for bucket in scope.role_scopes
            )

        if shape(legacy) != shape(aware):
            return "PINJAM"

        return None

    # ------------------------------------------------------------------
    # Sisi tulis (Stage A)
    # ------------------------------------------------------------------

    @staticmethod
    def _write_targets():
        """
        `{izin tulis: (model, peta cakupan)}` untuk seluruh viewset
        ber-`data_scope`.

        Berbeda dari sisi baca, **tidak** disaring ke resource
        ber-`require_view_permission`: sejak `required_scope_permission()`
        dipakai `filter_queryset()`, PATCH dan DELETE memakai
        `change_*`/`delete_*` pada resource mana pun yang punya peta
        cakupan. Resource yang bacanya terbuka justru yang paling
        berubah — di sanalah izin yang dikirim dulunya `None`.

        `add_*` ikut karena penjagaan subjek
        (`EmployeeSubjectWriteGuardMixin`) memakai izin yang sama.
        """
        targets: dict[str, tuple] = {}

        for view_class in _subclasses(BaseMasterViewSet):
            scope_map = getattr(view_class, "data_scope", None)

            if not scope_map:
                continue

            model = _model_of(view_class)

            if model is None:
                continue

            meta = model._meta

            for verb in ("add", "change", "delete"):
                targets.setdefault(
                    f"{meta.app_label}.{verb}_{meta.model_name}",
                    (model, scope_map),
                )

            # Aksi kustom yang menyatakan izinnya sendiri — pencatatan
            # cuti, misalnya. Cakupannya dihitung dari izin itu juga.
            declared = getattr(view_class, "action_scope_permissions", None)

            for permission in (declared or {}).values():
                targets.setdefault(permission, (model, scope_map))

        return targets

    def report_writes(self, User):
        """
        Siapa yang menyempit **hak tulisnya**, berikut jumlah barisnya.

        Barisnya benar-benar dihitung (bukan cuma dibandingkan
        bentuknya) karena pertanyaan yang harus dijawab sebelum saklar
        produksi dinyalakan bukan "siapa berubah" melainkan "apa yang
        tidak bisa lagi dikerjakan orang ini besok pagi".

        Tiga vonis, dan ketiganya berarti hal yang berbeda:

        * **TIDAK BERWENANG** — barisnya menyempit dan orangnya memang
          tidak memegang izin itu. Justru maksud perubahannya.
        * **SEMPIT** — izinnya ada, tapi cakupan role pemberinya lebih
          sempit daripada gabungan seluruh role-nya. Perlu dibaca satu
          per satu.
        * **KOSONG** — cakupannya sah tapi barisnya nol. Pemegang
          role EMPLOYEE yang belum pernah mengajukan cuti terbaca
          begini, dan itu bukan kehilangan kewenangan.
        * **HILANG** — cakupannya benar-benar ditutup (`denied`):
          tidak satu pun penugasannya memberi izin itu. Ini yang
          menahan rilis — kalau pekerjaannya memang membutuhkannya,
          yang kurang kewenangan penugasannya, bukan saklarnya.
        """
        from django.test import override_settings

        targets = self._write_targets()

        users = list(
            User.objects
            .filter(is_active=True, is_superuser=False)
            .order_by("username")
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nSisi tulis — {len(targets)} izin pada "
                f"{len(users)} akun (baris sebelum → sesudah)"
            )
        )

        counters = {
            "HILANG": 0,
            "SEMPIT": 0,
            "KOSONG": 0,
            "TIDAK BERWENANG": 0,
        }

        gained = 0

        for permission in sorted(targets):
            model, scope_map = targets[permission]

            lines = []

            for user in users:
                counts = []

                for enabled in (False, True):
                    for attribute in (
                        "_role_perm_cache",
                        "_data_scope_cache",
                    ):
                        if hasattr(user, attribute):
                            delattr(user, attribute)

                    with override_settings(ROLE_AWARE_DATA_SCOPE=enabled):
                        counts.append(
                            DataScopeService.filter(
                                model._default_manager.all(),
                                scope_map,
                                user,
                                required_permission=permission,
                            ).count()
                        )

                legacy, aware = counts

                if legacy == aware:
                    continue

                if aware > legacy:
                    gained += 1

                    verdict, style = "NAIK", self.style.ERROR
                elif not user.has_perm(permission):
                    verdict, style = (
                        "TIDAK BERWENANG",
                        self.style.SUCCESS,
                    )
                elif aware == 0:
                    # Nol baris punya **dua** sebab yang sama sekali
                    # berbeda, dan menyamakannya membuat laporan ini
                    # menahan rilis tanpa alasan: cakupannya benar-benar
                    # ditutup (tidak ada penugasan yang memberi izin
                    # ini), atau cakupannya sah — `own`, misalnya —
                    # tapi orangnya memang belum punya satu baris pun.
                    for attribute in (
                        "_role_perm_cache",
                        "_data_scope_cache",
                    ):
                        if hasattr(user, attribute):
                            delattr(user, attribute)

                    with override_settings(ROLE_AWARE_DATA_SCOPE=True):
                        scope = DataScopeService.for_user(
                            user,
                            permission=permission,
                        )

                    if scope.denied:
                        verdict, style = "HILANG", self.style.ERROR
                    else:
                        verdict, style = "KOSONG", self.style.WARNING
                else:
                    verdict, style = "SEMPIT", self.style.WARNING

                counters[verdict] = counters.get(verdict, 0) + 1

                roles = ", ".join(
                    role.code
                    for role in user.roles.filter(is_deleted=False)
                )

                lines.append(
                    style(
                        f"  {verdict:16} {user.username:20} "
                        f"{legacy:6} → {aware:<6} [{roles}]"
                    )
                )

            if not lines:
                continue

            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{permission}"))

            for line in lines:
                self.stdout.write(line)

        self.stdout.write("")

        if gained:
            self.stdout.write(
                self.style.ERROR(
                    f"{gained} akun **bertambah** hak tulisnya. Cakupan "
                    "per-izin tidak boleh melebarkan apa pun."
                )
            )

        if counters["HILANG"]:
            self.stdout.write(
                self.style.ERROR(
                    f"{counters['HILANG']} akun kehilangan seluruh hak "
                    "tulis pada salah satu resource meski memegang "
                    "izinnya. Periksa kewenangan penugasannya sebelum "
                    "saklar dinyalakan."
                )
            )

        self.stdout.write(
            f"SEMPIT {counters['SEMPIT']} | "
            f"KOSONG {counters['KOSONG']} | "
            f"TIDAK BERWENANG {counters['TIDAK BERWENANG']} | "
            f"HILANG {counters['HILANG']} | NAIK {gained}"
        )

        self.stdout.write(
            "KOSONG = cakupannya sah (lazimnya `own`) tapi orangnya "
            "memang belum punya baris sendiri — bukan kehilangan "
            "kewenangan."
        )

    # ------------------------------------------------------------------
    # Permukaan baca (3B-18)
    # ------------------------------------------------------------------

    @staticmethod
    def _surfaces():
        """
        Permukaan baca yang sudah dihitung per izin, beserta **sumber**
        izin dan cakupannya.

        Ditulis sebagai daftar, bukan ditemukan otomatis: yang otomatis
        akan ikut menemukan permukaan yang belum dipindahkan, dan
        melaporkannya "tidak berubah" — jawaban yang benar untuk
        pertanyaan yang salah.
        """
        from apps.hr.api.employee.scope import EMPLOYEE_SCOPE
        from apps.hr.models import Employee
        from apps.payroll.api.dashboard.services import (
            PayrollDashboardService,
        )
        from apps.reports.api.hr.manpower_summary.services import (
            ManpowerSummaryService,
        )

        def payroll_lines(user):
            return PayrollDashboardService.lines({"user": user}).count()

        def payroll_runs(user):
            return PayrollDashboardService.runs({"user": user}).count()

        def payroll_periods(user):
            return PayrollDashboardService.periods({"user": user}).count()

        def manpower(user):
            return ManpowerSummaryService.employee_queryset(
                {"user": user},
            ).count()

        return [
            ("dashboard payroll — baris", payroll_lines,
             "payroll.view_payrollrunemployee", "PAYROLL_RUN_EMPLOYEE_SCOPE"),
            ("dashboard payroll — run", payroll_runs,
             "payroll.view_payrollrun", "RUN_SCOPE"),
            ("dashboard payroll — periode", payroll_periods,
             "payroll.view_payrollperiod", "PERIOD_SCOPE"),
            ("laporan manpower summary", manpower,
             "hr.view_employee", "EMPLOYEE_SCOPE"),
        ]

    def report_surfaces(self, User):
        """
        Berapa baris yang hilang, dan berapa yang **bertambah**.

        Yang bertambah harus selalu nol. Otoritas per-izin adalah
        himpunan bagian dari cakupan gabungan — kalau ada yang naik,
        yang salah bukan datanya melainkan salah satu peta cakupan, dan
        itu harus ketahuan sebelum saklarnya menyala di produksi, bukan
        sesudah.
        """
        from django.test import override_settings

        try:
            surfaces = self._surfaces()
        except Exception as error:  # noqa: BLE001
            self.stdout.write(
                self.style.ERROR(f"Permukaan tidak bisa dimuat: {error}")
            )

            return

        users = list(
            User.objects
            .filter(is_active=True, is_superuser=False)
            .order_by("username")
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "\nPermukaan baca — baris sebelum → sesudah"
            )
        )

        total_lost = 0
        total_gained = 0

        for label, measure, permission, scope_source in surfaces:
            self.stdout.write(f"\n{label}")
            self.stdout.write(
                f"  izin: {permission}   cakupan: {scope_source}"
            )

            reported = False

            for user in users:
                counts = []

                for enabled in (False, True):
                    for attribute in (
                        "_role_perm_cache",
                        "_data_scope_cache",
                    ):
                        if hasattr(user, attribute):
                            delattr(user, attribute)

                    with override_settings(
                        ROLE_AWARE_DATA_SCOPE=enabled,
                    ):
                        counts.append(measure(user))

                legacy, aware = counts

                if legacy == aware:
                    continue

                reported = True

                if aware > legacy:
                    total_gained += 1

                    style = self.style.ERROR

                    verdict = "NAIK"
                else:
                    total_lost += 1

                    style = (
                        self.style.WARNING
                        if user.has_perm(permission)
                        else self.style.SUCCESS
                    )

                    # Kehilangan yang **berwenang** dan yang **tidak
                    # sengaja** dibedakan di sini, dan bedanya satu
                    # pertanyaan: apakah orang ini memegang izinnya?
                    #
                    # Tidak memegang → memang tidak boleh membacanya,
                    # dan hilangnya justru maksud perubahannya.
                    # Memegang → izinnya ada tapi cakupan role
                    # pemberinya lebih sempit; itu perlu dilihat orang
                    # sebelum rilis.
                    verdict = (
                        "SEMPIT" if user.has_perm(permission)
                        else "TIDAK BERWENANG"
                    )

                roles = ", ".join(
                    role.code for role in user.roles.filter(is_deleted=False)
                )

                self.stdout.write(
                    style(
                        f"  {verdict:16} {user.username:24} "
                        f"{legacy:6} → {aware:<6} [{roles}]"
                    )
                )

            if not reported:
                self.stdout.write("  (tidak ada yang berubah)")

        self.stdout.write("")

        if total_gained:
            self.stdout.write(
                self.style.ERROR(
                    f"{total_gained} akun **bertambah** aksesnya. Otoritas "
                    "per-izin tidak boleh melebarkan apa pun — periksa "
                    "peta cakupan permukaan itu sebelum rilis."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Nol akun bertambah aksesnya. Syarat rilis terpenuhi."
                )
            )

        self.stdout.write(
            f"{total_lost} akun menyempit. 'TIDAK BERWENANG' memang "
            "maksudnya; 'SEMPIT' perlu dibaca satu per satu."
        )

