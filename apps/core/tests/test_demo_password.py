"""
Password akun peragaan tidak pernah punya nilai bawaan di kode.

Repositori ini publik: password yang jatuh ke nilai yang sudah dikenal
membuat setiap tenant peragaan bisa dimasuki siapa pun. Yang dikunci di
sini adalah arah gagalnya — kosong berarti berhenti, bukan menebak.
"""

from __future__ import annotations

import os
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.core.services.demo_password import (
    DEMO_PASSWORD_ENV,
    DemoPasswordMissing,
    demo_password,
)


class DemoPasswordTests(SimpleTestCase):
    def test_missing_env_and_explicit_fails(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DEMO_PASSWORD_ENV, None)

            with self.assertRaises(DemoPasswordMissing) as caught:
                demo_password()

        self.assertIn(DEMO_PASSWORD_ENV, str(caught.exception))

    def test_empty_env_fails(self):
        with mock.patch.dict(os.environ, {DEMO_PASSWORD_ENV: ""}):
            with self.assertRaises(DemoPasswordMissing):
                demo_password()

    def test_env_is_used(self):
        with mock.patch.dict(os.environ, {DEMO_PASSWORD_ENV: "from-env-pw"}):
            self.assertEqual(demo_password(), "from-env-pw")

    def test_explicit_wins_over_env(self):
        with mock.patch.dict(os.environ, {DEMO_PASSWORD_ENV: "from-env-pw"}):
            self.assertEqual(demo_password("explicit-pw"), "explicit-pw")

    def test_missing_is_a_command_error(self):
        # Perintah manajemen mencetak satu baris pesan, bukan traceback.
        self.assertTrue(issubclass(DemoPasswordMissing, CommandError))


class CreateSuperadminPasswordTests(SimpleTestCase):
    def test_password_is_required(self):
        # Gagal saat parsing argumen — sebelum menyentuh database.
        with self.assertRaises(CommandError) as caught:
            call_command("create_superadmin")

        self.assertIn("--password", str(caught.exception))


class SeedDemoPasswordTests(SimpleTestCase):
    def test_seed_demo_stops_before_any_step(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DEMO_PASSWORD_ENV, None)

            with mock.patch(
                "apps.hr.management.commands.seed_demo.call_command",
            ) as step:
                with self.assertRaises(DemoPasswordMissing):
                    call_command("seed_demo")

        step.assert_not_called()
