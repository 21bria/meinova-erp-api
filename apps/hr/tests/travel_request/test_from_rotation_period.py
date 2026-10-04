"""
Regression B7: satu blok jadwal = satu Travel Request aktif, dan
`from-rotation-period` menyaring blok jadwalnya dengan cakupan data.

Dua cacat yang berbeda sifatnya tapi lewat pintu yang sama.

Yang pertama tidak berbunyi sama sekali: menekan tombolnya dua kali
menerbitkan dua dokumen untuk kepulangan yang sama, dan kalau
dua-duanya disetujui `issue_leave_records` memotong saldo cutinya dua
kali. Ketahuannya lewat saldo yang tidak cocok berbulan-bulan
kemudian, bukan lewat error.

Yang kedua kebocoran: view-nya mengambil `RotationPeriod.objects`
langsung, jadi cakupan data yang menjaga daftar Travel Request tidak
ikut menjaga jalan pintas ini. Nomor blok jadwal tinggal ditebak.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Location
from apps.hr.api.travel_request.services import TravelRequestService
from apps.hr.models import (
    RotationPeriod,
    RotationPeriodType,
    TravelRequest,
    TravelRequestStatus,
)

from .base import TravelRequestTestCase


User = get_user_model()

ENDPOINT = "/api/hr/travel-requests/from-rotation-period/"


class PeriodDuplicateGuardTests(TravelRequestTestCase):
    """B7 — blok jadwal yang sudah punya TR aktif menolak yang kedua."""

    def _period_with_request(self):
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        _, off = self.make_periods(rotation)

        request = TravelRequestService.build_from_period(period=off)

        return employee, off, request

    def _set_status(self, request, status):
        request.status = status
        request.save(update_fields=["status", "updated_at"])
        request.refresh_from_db()

        return request

    # ------------------------------------------------------------------
    # Status yang menghalangi
    # ------------------------------------------------------------------

    def test_second_request_from_the_same_block_is_rejected(self):
        _, off, _ = self._period_with_request()

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.build_from_period(period=off)

        self.assertIn(
            "rotation_period",
            caught.exception.message_dict,
        )

    def test_rejection_names_the_document_that_blocks_it(self):
        """
        "Sudah ada" tanpa menyebut yang mana memaksa pengisinya mencari
        sendiri di daftar yang panjangnya seribu baris.
        """
        _, off, existing = self._period_with_request()

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.build_from_period(period=off)

        message = " ".join(
            caught.exception.message_dict["rotation_period"],
        )

        self.assertIn(existing.document_number, message)
        self.assertIn(existing.get_status_display(), message)

    def test_draft_blocks(self):
        _, off, existing = self._period_with_request()

        self.assertEqual(existing.status, TravelRequestStatus.DRAFT)

        with self.assertRaises(ValidationError):
            TravelRequestService.build_from_period(period=off)

    def test_submitted_blocks(self):
        _, off, existing = self._period_with_request()

        self._set_status(existing, TravelRequestStatus.SUBMITTED)

        with self.assertRaises(ValidationError):
            TravelRequestService.build_from_period(period=off)

    def test_approved_blocks(self):
        """
        Yang paling merugikan dari ketiganya: dokumen kedua untuk blok
        yang cutinya sudah terbit akan menerbitkan cuti kedua begitu
        ikut disetujui.
        """
        _, off, existing = self._period_with_request()

        self._set_status(existing, TravelRequestStatus.APPROVED)

        with self.assertRaises(ValidationError):
            TravelRequestService.build_from_period(period=off)

    # ------------------------------------------------------------------
    # Status yang tidak menghalangi
    # ------------------------------------------------------------------

    def test_rejected_does_not_block(self):
        """Pengajuan yang ditolak harus bisa diajukan ulang."""
        _, off, existing = self._period_with_request()

        self._set_status(existing, TravelRequestStatus.REJECTED)

        replacement = TravelRequestService.build_from_period(period=off)

        self.assertNotEqual(replacement.pk, existing.pk)
        self.assertEqual(replacement.rotation_period_id, off.pk)

    def test_cancelled_does_not_block(self):
        _, off, existing = self._period_with_request()

        self._set_status(existing, TravelRequestStatus.CANCELLED)

        replacement = TravelRequestService.build_from_period(period=off)

        self.assertNotEqual(replacement.pk, existing.pk)

    def test_soft_deleted_does_not_block(self):
        """
        Dokumen terhapus tidak terlihat di layar mana pun, jadi
        menghalangi dari balik layar membuat penolakannya menunjuk
        dokumen yang tidak bisa dibuka.
        """
        _, off, existing = self._period_with_request()

        TravelRequestService.soft_delete(instance=existing)

        replacement = TravelRequestService.build_from_period(period=off)

        self.assertNotEqual(replacement.pk, existing.pk)

    def test_another_block_of_the_same_roster_is_unaffected(self):
        """
        Yang dikunci satu blok, bukan pegawainya: putaran berikutnya
        tetap harus bisa diajukan.
        """
        employee, off, _ = self._period_with_request()

        later = RotationPeriod.objects.create(
            rotation=off.rotation,
            employee=employee,
            sequence=4,
            period_type=RotationPeriodType.OFF,
            start_date=off.end_date + timedelta(days=60),
            end_date=off.end_date + timedelta(days=73),
            total_days=14,
            purpose=self.field_break,
            cycle_number=2,
        )

        request = TravelRequestService.build_from_period(period=later)

        self.assertEqual(request.rotation_period_id, later.pk)

    # ------------------------------------------------------------------
    # Jalur masuk selain tombolnya
    # ------------------------------------------------------------------

    def test_manual_create_pointing_at_a_taken_block_is_rejected(self):
        """
        Penjagaannya di service, jadi create biasa yang mengetik
        `rotation_period` sendiri kena aturan yang sama.
        """
        employee, off, _ = self._period_with_request()

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.create(
                data={
                    "employee": employee,
                    "company": self.company,
                    "location": self.site,
                    "rotation_period": off,
                    "start_date": off.start_date,
                    "end_date": off.end_date,
                },
            )

        self.assertIn(
            "rotation_period",
            caught.exception.message_dict,
        )

    def test_moving_a_request_onto_a_taken_block_is_rejected(self):
        """
        Jalur ketiga: dokumen yang tadinya tidak menunjuk blok mana pun
        dipindahkan ke blok yang sudah dipegang dokumen lain.

        Pegawainya sengaja sama supaya yang menolak benar-benar
        penjagaan ini — `TravelRequest.clean()` juga menolak blok milik
        pegawai lain, dan itu aturan yang berbeda.
        """
        employee, off, _ = self._period_with_request()

        loose = self.make_request(employee)

        self.assertIsNone(loose.rotation_period_id)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.update(
                instance=loose,
                data={"rotation_period": off},
            )

        self.assertIn(
            "rotation_period",
            caught.exception.message_dict,
        )

    def test_the_owner_of_the_block_is_not_blocked_by_itself(self):
        """
        Dokumen yang memang pemegang blok itu harus tetap bisa
        disunting — kalau tidak, penjagaannya mengunci dokumennya
        sendiri sejak baris pertama.
        """
        _, off, existing = self._period_with_request()

        updated = TravelRequestService.update(
            instance=existing,
            data={"notes": "Tiket menyusul."},
        )

        self.assertEqual(updated.rotation_period_id, off.pk)
        self.assertEqual(updated.notes, "Tiket menyusul.")

    def test_no_second_document_is_left_behind(self):
        """
        Penolakannya harus terjadi **sebelum** dokumennya tersimpan.
        Kalau tidak, yang tercegah cuma pesannya.
        """
        _, off, _ = self._period_with_request()

        with self.assertRaises(ValidationError):
            TravelRequestService.build_from_period(period=off)

        self.assertEqual(
            TravelRequest.objects.filter(
                rotation_period=off,
                is_deleted=False,
            ).count(),
            1,
        )


class FromRotationPeriodScopeTests(TravelRequestTestCase):
    """
    B7 — jalan pintasnya memakai cakupan data yang sama dengan daftar
    Travel Request-nya.

    Diuji lewat HTTP, bukan service: cakupan data hidup di lapisan view
    dan justru itu lapisan yang dilewati endpoint ini sebelum
    diperbaiki.
    """

    _user_counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Site kedua, dipakai sebagai cakupan yang **tidak** memuat
        # blok jadwal yang diuji.
        cls.other_site = Location.objects.create(
            company=cls.company,
            code="TROTHER",
            name="Sorong Site",
        )

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @classmethod
    def make_user(cls, *, superuser=False):
        cls._user_counter += 1

        return User.objects.create_user(
            username=f"trv.scope{cls._user_counter}",
            email=f"trv.scope{cls._user_counter}@example.test",
            password="Test-Only#Pw1",
            is_superuser=superuser,
            is_staff=superuser,
        )

    @classmethod
    def scoped_user(cls, location):
        """User biasa yang cakupannya dikunci ke satu Location."""
        cls._user_counter += 1

        role = Role.objects.create(
            code=f"TRV-SCOPE-{cls._user_counter}",
            name=f"Travel Scope {cls._user_counter}",
        )

        # Endpoint-nya menyaring blok jadwal **per izin**
        # (`required_permission=view_permission_for(RotationPeriod)`),
        # jadi role yang tidak memegang izin itu tidak menyumbang
        # cakupan apa pun — pemegangnya ditutup, dan test positif di
        # bawah gagal karena sebab yang bukan sedang diujinya. Di
        # produksi setiap role yang diseed memegang izin baca resource
        # yang dipakainya lewat `READ_GRANTS`; fixture tanpa izin
        # menguji keadaan yang tidak pernah ada.
        role.permissions.add(
            Permission.objects.get(
                content_type__app_label="hr",
                codename="view_rotationperiod",
            )
        )

        user = cls.make_user()

        # WHERE dinyatakan pada penugasan — satu-satunya tempatnya
        # sejak Wave C.
        grant_role(
            user,
            role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("location", location.pk)],
        )

        return user

    def post(self, period, *, user):
        return self.client.post(
            ENDPOINT,
            data=json.dumps({"rotation_period": period.pk}),
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        )

    def make_off_block(self):
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        _, off = self.make_periods(rotation)

        return off

    # ------------------------------------------------------------------
    # Cakupan
    # ------------------------------------------------------------------

    def test_block_outside_the_scope_is_refused(self):
        """
        Blok jadwalnya di Gebe, cakupan pemanggilnya Sorong. Sebelum
        diperbaiki, dokumennya terbit dan sejak itu terbaca di daftar
        TR-nya — karena dokumennya jadi miliknya.
        """
        off = self.make_off_block()

        response = self.post(off, user=self.scoped_user(self.other_site))

        self.assertEqual(response.status_code, 400)

        self.assertIn(
            "rotation_period",
            response.json()["errors"],
        )

        self.assertFalse(
            TravelRequest.objects.filter(
                rotation_period=off,
                is_deleted=False,
            ).exists(),
        )

    def test_refusal_does_not_say_whether_the_block_exists(self):
        """
        Pesannya sama dengan blok yang memang tidak ada. Membedakannya
        membuat endpoint ini jadi alat untuk memeriksa nomor mana yang
        terpakai.
        """
        off = self.make_off_block()

        outside = self.post(off, user=self.scoped_user(self.other_site))

        missing = self.client.post(
            ENDPOINT,
            data=json.dumps({"rotation_period": 9_999_999}),
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer "
                f"{RefreshToken.for_user(self.make_user()).access_token}"
            ),
        )

        self.assertEqual(outside.status_code, missing.status_code)

    def test_block_inside_the_scope_still_works(self):
        """
        Penyaringannya tidak boleh mengunci orang yang memang berhak —
        itu cara paling mudah membuat penjagaan dimatikan lagi.
        """
        off = self.make_off_block()

        response = self.post(off, user=self.scoped_user(self.site))

        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            TravelRequest.objects.filter(
                rotation_period=off,
                is_deleted=False,
            ).exists(),
        )

    def test_user_without_any_role_sees_nothing(self):
        """
        **Dibalik di Stage 4J.** Dulu berbunyi "tanpa role = tanpa
        batasan", aturan lama yang memang sengaja dipertahankan saat
        test ini ditulis.

        Aturan itu sudah tidak berlaku di jalur ini. Endpoint-nya
        menyaring dengan `required_permission`, dan dengan cakupan
        per-izin menyala, orang yang tidak memegang satu pun role yang
        memberi izin itu **ditutup** — bukan dibuka. Blok jadwalnya
        dijawab "tidak ditemukan", sama seperti blok yang memang tidak
        ada, supaya keberadaannya tidak bocor lewat selisih pesan.

        Yang belum berubah, dan sengaja tidak disentuh stage ini:
        `DataScopeService` masih memberi `unrestricted` kepada akun
        tanpa penugasan **saat tidak ada izin yang disebut**. Jalur itu
        tidak lewat sini.
        """
        off = self.make_off_block()

        response = self.post(off, user=self.make_user())

        self.assertEqual(response.status_code, 400, response.content[:200])

        self.assertIn("rotation_period", response.json().get("errors", {})
                      or response.json())

    def test_superuser_is_unrestricted(self):
        off = self.make_off_block()

        response = self.post(off, user=self.make_user(superuser=True))

        self.assertEqual(response.status_code, 200)

    # ------------------------------------------------------------------
    # Duplikat lewat HTTP
    # ------------------------------------------------------------------

    def test_pressing_the_button_twice_returns_a_validation_error(self):
        """
        Bentuk yang dilihat frontend: 400 berisi error per field, bukan
        500 dan bukan dokumen kedua.
        """
        off = self.make_off_block()
        user = self.make_user(superuser=True)

        first = self.post(off, user=user)

        self.assertEqual(first.status_code, 200)

        second = self.post(off, user=user)

        self.assertEqual(second.status_code, 400)

        self.assertIn(
            "rotation_period",
            second.json()["errors"],
        )

        self.assertEqual(
            TravelRequest.objects.filter(
                rotation_period=off,
                is_deleted=False,
            ).count(),
            1,
        )
