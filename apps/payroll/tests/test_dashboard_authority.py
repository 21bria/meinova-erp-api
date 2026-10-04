"""
Dashboard payroll dan daftar payroll harus menjawab pertanyaan yang
sama dengan jawaban yang sama.

Stage 3A memasang otoritas per-izin di `BaseMasterViewSet`, dan hanya di
sana. Dashboard merakit querysetnya sendiri lewat
`PayrollDashboardService`, jadi ia tetap memakai cakupan gabungan
**seluruh** role pemegang akun — termasuk role yang tidak memberi satu
pun izin payroll. Akibatnya dua pintu ke angka yang sama dijaga dua
aturan yang berbeda: daftar per pegawai menyempit, kartu KPI tidak.

Yang diuji di sini bukan besar angkanya. `test_proration`,
`test_attendance_deduction`, dan `test_overtime` sudah menjawab itu.
Yang diuji: **apakah tiap permukaan menjumlahkan baris yang sama dengan
yang boleh dibaca pemanggilnya** — diperiksa dengan membandingkan
permukaan satu sama lain memakai akun yang sama, bukan dengan
menuliskan angka yang diharapkan.

Panggungnya diwarisi dari `RunSummaryScopeTestCase`: satu run, empat
pegawai di dua divisi, dan akun `full` / `partial` / `blind`. Yang
ditambahkan di sini satu akun lagi — `borrower` — yang memegang izin
payroll dari role bercakupan sempit **dan** role tak berbatas yang tidak
memberi izin apa pun. Dialah bentuk peminjaman lintas-role yang
dimaksud Stage 3B.
"""

from __future__ import annotations

from django.contrib.auth.models import Permission
from django.test import override_settings

from apps.accounts.models import Role
from apps.payroll.api.dashboard.services import PayrollDashboardService

from .test_payroll_run_summary import RunSummaryScopeTestCase


class PayrollDashboardAuthorityTest(RunSummaryScopeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Cakupan seluas tenant, **tanpa satu pun izin payroll**.
        # Keluasannya dinyatakan pada penugasan (`role_authority` di
        # base class memberinya `UNRESTRICTED`), bukan disimpulkan dari
        # daftar cakupan yang kebetulan kosong.
        cls.wide_no_perm = Role.objects.create(
            code="WIDE-NO-PAYROLL",
            name="Wide Without Payroll",
        )

        # Ia tetap perlu satu izin supaya bukan role kosong yang tidak
        # menguji apa pun — izin yang tidak ada hubungannya dengan
        # payroll, persis seperti EXECUTIVE di tenant sungguhan yang
        # memegang `hr.view_employee` saja.
        cls.wide_no_perm.permissions.add(
            Permission.objects.get(
                content_type__app_label="hr",
                codename="view_employee",
            )
        )

        cls.borrower_user = cls.make_account(
            "borrower",
            roles=[cls.payroll_reader, cls.wide_no_perm],
        )

        # Hanya role luas tanpa izin payroll. Di tenant sungguhan ini
        # `demo.gmho`: cakupan seluruh company, nol izin payroll.
        cls.outsider_user = cls.make_account(
            "outsider",
            roles=[cls.wide_no_perm],
        )

    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()

        self.clear_caches()

    @staticmethod
    def clear_caches():
        from django.contrib.auth import get_user_model

        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def dashboard(self, user, run):
        """
        Tiga angka dashboard untuk satu akun: periode, run, baris.

        Cache dibuang tiap panggilan — kalau tidak, jawaban mode
        sebelumnya terbaca lagi di mode berikutnya dan test dua-mode
        lulus karena alasan yang salah.
        """
        for attribute in ("_role_perm_cache", "_data_scope_cache"):
            if hasattr(user, attribute):
                delattr(user, attribute)

        context = {"user": user}

        return {
            "periods": PayrollDashboardService.periods(context).count(),
            "runs": PayrollDashboardService.runs(context).count(),
            "lines": PayrollDashboardService.lines(context).filter(
                run=run,
            ).count(),
        }

    # ==================================================================
    # 1 — dashboard tidak boleh lebih luas dari daftarnya
    # ==================================================================

    def test_dashboard_lines_agree_with_the_list_endpoint(self):
        """
        **Kontrak 3B.** Untuk tiap akun, jumlah baris yang dijumlahkan
        dashboard harus **sama persis** dengan jumlah baris yang
        dikirim `/payroll-run-employees/?run=`.

        Dibandingkan per akun, bukan terhadap angka tetap: yang diuji
        kesepakatan dua permukaan, dan angka tetap justru akan tetap
        hijau kalau keduanya salah dengan cara yang sama.
        """
        run, inside, outside = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            for name, user, expected in (
                ("full", self.full_user, len(inside) + len(outside)),
                ("partial", self.partial_user, len(inside)),
                ("blind", self.blind_user, 0),
                ("borrower", self.borrower_user, len(inside)),
                ("outsider", self.outsider_user, 0),
            ):
                listed = self.listed_for(user, run).count()

                dashboard = self.dashboard(user, run)["lines"]

                self.assertEqual(
                    dashboard,
                    listed,
                    msg=(
                        f"[{name}] dashboard menjumlahkan {dashboard} "
                        f"baris, daftarnya mengirim {listed}. Dua pintu "
                        f"ke angka yang sama menjawab berbeda."
                    ),
                )

                self.assertEqual(
                    listed,
                    expected,
                    msg=f"[{name}] panggungnya tidak seperti yang disangka.",
                )

    def test_a_wide_role_without_payroll_permission_reads_no_lines(self):
        """
        **Persona EXECUTIVE/BOD (3B-6).** Cakupan seluas tenant, nol
        izin payroll — nol baris, dan nol total.

        Diuji di kedua mode: jalur lama memang membacanya, dan itu
        yang membuat saklarnya masih ada.
        """
        run, _, _ = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            aware = self.dashboard(self.outsider_user, run)

        self.assertEqual(
            aware["lines"],
            0,
            msg=(
                "Pemegang cakupan luas tanpa izin payroll masih "
                "menjumlahkan baris gaji orang lain."
            ),
        )

        self.assertEqual(
            aware["runs"],
            0,
            msg="Daftar run masih terbuka untuk akun tanpa izin payroll.",
        )

        # Kebocoran jalur lama diperiksa pada **daftar run**, bukan pada
        # `lines`.
        #
        # `lines` dijaga dua lapis, dan di panggung ini lapis kedua
        # (`EmployeeDataPolicy` yang menyebut `payroll_reader`) sudah
        # menutupnya sendiri untuk `outsider` — jadi angkanya nol di
        # kedua mode, dan nol yang sama itu tidak membuktikan apa pun
        # tentang lapis cakupan. Di tenant sungguhan lapis kedua tidak
        # selalu menolong: `demo.gmho` tetap membaca 2 baris karena ia
        # atasan langsung dua orang, dan `allow_manager` membolehkannya.
        #
        # Daftar run tidak punya lapis kedua sama sekali. Ia karena itu
        # ukuran yang jujur untuk apa yang ditutup perubahan ini.
        with override_settings(ROLE_AWARE_DATA_SCOPE=False):
            legacy = self.dashboard(self.outsider_user, run)

        self.assertGreater(
            legacy["runs"],
            0,
            msg=(
                "Jalur lama berhenti membocorkan daftar run. Kalau ini "
                "yang berubah, saklarnya sudah tidak diperlukan — "
                "cabut, jangan longgarkan testnya."
            ),
        )

    def test_payroll_permission_does_not_borrow_a_wider_roles_scope(self):
        """
        **Peminjaman lintas-role, di permukaan dashboard.**

        `borrower` memegang izin payroll dari role bercakupan Divisi A,
        dan cakupan tak berbatas dari role yang tidak memberi izin apa
        pun. Yang berlaku cakupan role **pemberi izinnya**.
        """
        run, inside, outside = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            aware = self.dashboard(self.borrower_user, run)["lines"]

        self.assertEqual(
            aware,
            len(inside),
            msg=(
                "Izin payroll memakai cakupan role yang tidak "
                "memberikannya — peminjaman lintas-role kembali di "
                "dashboard."
            ),
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=False):
            legacy = self.dashboard(self.borrower_user, run)["lines"]

        self.assertEqual(
            legacy,
            len(inside) + len(outside),
            msg="Jalur lama berhenti meminjam — perbarui catatannya.",
        )

    def test_two_roles_granting_the_same_permission_union_their_scopes(self):
        """
        **Penyempitan yang benar juga harus tidak menyempitkan yang
        salah.** `full` memegang izin payroll dari **dua** role: satu
        bercakupan Divisi A, satu tak berbatas. Gabungannya tetap
        seluruh run.
        """
        run, inside, outside = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            lines = self.dashboard(self.full_user, run)["lines"]

        self.assertEqual(
            lines,
            len(inside) + len(outside),
            msg=(
                "Dua role yang sama-sama memberi izin payroll tidak "
                "digabung cakupannya."
            ),
        )

    def test_summary_action_agrees_with_the_list(self):
        """
        Permukaan ketiga: `payroll-runs/<id>/summary/`. Ia memakai
        pintu yang sama (`scope_run_employees`), jadi ia harus
        menjumlahkan baris yang sama dengan daftarnya.
        """
        run, inside, outside = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            for name, user in (
                ("partial", self.partial_user),
                ("borrower", self.borrower_user),
            ):
                summary = self.summary_for(user, run)

                totals = self.totals_of(self.listed_for(user, run))

                self.assertEqual(
                    summary["run"]["total_net"],
                    str(totals["total_net"]),
                    msg=(
                        f"[{name}] rekap dan daftar menjumlahkan baris "
                        f"yang berbeda."
                    ),
                )

                self.assertEqual(
                    summary["run"]["employee_count"],
                    self.listed_for(user, run).count(),
                    msg=f"[{name}] jumlah pegawainya berbeda.",
                )

    def test_direct_id_cannot_reach_a_run_without_the_permission(self):
        """
        **Akses lewat id langsung (3B-16 no. 5 & 7).**

        `outsider` tahu id run-nya — cakupan organisasinya memang
        mencakup company-nya — tapi tidak memegang `view_payrollrun`.
        `get_object()` DRF memanggil `filter_queryset()`, jadi
        querysetnya kosong dan action-nya tidak pernah sampai ke
        agregat.
        """
        from django.http import Http404

        from rest_framework.exceptions import NotFound, PermissionDenied

        run, _, _ = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            with self.assertRaises((Http404, NotFound, PermissionDenied)):
                self.summary_for(self.outsider_user, run)

    def test_period_and_run_selectors_follow_their_own_permissions(self):
        """
        **Pemilih periode dan run adalah permukaan baca tersendiri.**

        Keduanya dijaga izin modelnya masing-masing, dan `blind` —
        yang memegang keduanya lewat `open_role` — tetap boleh
        membukanya. Yang ditutup baginya angka per orang, oleh
        `EmployeeDataPolicy`, bukan oleh izin ini.
        """
        run, _, _ = self.build_run()

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            blind = self.dashboard(self.blind_user, run)

            outsider = self.dashboard(self.outsider_user, run)

        self.assertGreater(
            blind["runs"],
            0,
            msg="Pemegang `view_payrollrun` kehilangan daftar run-nya.",
        )

        self.assertEqual(
            blind["lines"],
            0,
            msg="Kelompok data payroll berhenti menutup angka per orang.",
        )

        self.assertEqual(
            outsider["runs"],
            0,
            msg=(
                "Akun tanpa `view_payrollrun` masih melihat daftar run "
                "— pemilihnya belum dihitung per izin."
            ),
        )
