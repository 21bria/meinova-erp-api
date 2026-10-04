"""
Migration 0011/0012 dibekukan — penjaganya, bukan janjinya.

Yang dijaga berkas ini satu kalimat: **membuat tenant baru tidak boleh
bergantung pada kode aplikasi yang akan dihapus gelombang C.**

`django-tenants` memutar ulang seluruh rantai migration untuk setiap
schema tenant yang dibuat. Sampai Stage 4I, 0011 dan 0012 memanggil
`apps.accounts.services.authority_backfill`, yang mengimpor model nyata
— jadi begitu `RoleDataPermission` dihapus, yang gagal bukan pemutaran
riwayat melainkan **pembuatan tenant**, dan gagalnya jauh dari sebabnya:
pesannya menyebut sebuah import di migration nomor sebelas, bukan
"tenant baru tidak bisa dibuat".

Tiga hal diperiksa, dan ketiganya perlu:

1. **Statis** — kedua migration tidak menyebut `apps.` sama sekali.
   Ini yang menangkap kemunduran paling mungkin: seseorang menambahkan
   satu import "sementara" saat memperbaiki sesuatu.
2. **Perilaku** — salinan bekunya menurunkan kewenangan persis seperti
   service yang digantikannya, termasuk kasus yang paling mudah salah
   (`explicit` tanpa baris = tertutup) dan idempotensinya.
3. **Fungsional** — sebuah schema tenant benar-benar dibuat dari nol
   lewat rantai penuh.
"""

from __future__ import annotations

import io
import re
import tokenize
import uuid
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase

from django_tenants.utils import get_tenant_model, schema_context

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

FROZEN = (
    "0011_backfill_assignment_authority.py",
    "0012_close_blank_assignment_authority.py",
)

# `from apps.x import y`, `import apps.x` — tapi **bukan** parameter
# `apps` milik RunPython, yang justru jalur yang benar.
APP_IMPORT = re.compile(r"^\s*(from|import)\s+apps[.\s]", re.MULTILINE)


def code_only(source: str) -> str:
    """
    Sumber tanpa komentar dan tanpa string literal.

    Dipakai karena versi pertama test ini memeriksa substring mentah dan
    langsung salah menuduh: kedua migration **menjelaskan** di komentar
    bahwa nilainya ditulis literal "bukan lewat `AuthorityMode` /
    `DataScopeMode`" — kalimat yang menyebut nama yang justru dilarang.
    Penjaga yang tidak bisa membedakan penyebutan dari pemakaian akan
    menghukum dokumentasi yang baik.
    """
    kept = []

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue

        kept.append(token.string)

    return " ".join(kept)


class FrozenMigrationsImportNothingLiveTests(TransactionTestCase):
    """Pemeriksaan statis — tidak menyentuh database sama sekali."""

    def test_neither_migration_imports_application_code(self):
        for name in FROZEN:
            source = (MIGRATIONS / name).read_text()

            offenders = APP_IMPORT.findall(source)

            self.assertEqual(
                offenders, [],
                f"{name} mengimpor kode aplikasi: {offenders}. "
                "Migration yang dibekukan harus memakai "
                "apps.get_model() saja.",
            )

    def test_neither_migration_reaches_the_service_layer(self):
        for name in FROZEN:
            source = (MIGRATIONS / name).read_text()

            executable = code_only(source)

            for forbidden in (
                "authority_backfill",
                "backfill_authority",
                "AuthorityMode",
                "DataScopeMode",
                # `RoleDataPermission` **tidak** dilarang: itu nama
                # variabel lokal yang memegang model historis hasil
                # `apps.get_model()`, dan memang begitu seharusnya.
                # Yang dilarang mengimpor modelnya, dan itu dijaga
                # `test_neither_migration_imports_application_code`.
            ):
                self.assertNotIn(
                    forbidden, executable,
                    f"{name} memakai {forbidden!r} di kode yang "
                    "dijalankan. Menyebutnya di komentar boleh; "
                    "memakainya tidak.",
                )

    def test_both_migrations_resolve_models_historically(self):
        for name in FROZEN:
            source = (MIGRATIONS / name).read_text()

            self.assertIn(
                'apps.get_model("accounts", "RoleAssignment")', source,
                f"{name} tidak memakai model historis.",
            )


# ----------------------------------------------------------------------
# `FrozenDerivationBehaviourTests` — dihapus di gelombang C
# ----------------------------------------------------------------------
#
# Kelas itu memanggil `_backfill()` beku langsung terhadap registry
# Django yang **hidup**: ia membuat `Role` dengan `data_scope_mode=` lalu
# memeriksa kewenangan yang dihasilkannya. Sesudah kolom itu tidak ada
# lagi di model hidup, kelas itu tidak bisa dijalankan sama sekali —
# bukan merah, melainkan gagal saat menyiapkan fixture.
#
# Menuliskannya ulang terhadap `apps.get_model()` historis juga tidak
# menyelamatkannya: yang dibutuhkan bukan sekadar model historis
# melainkan **tabel** historis, dan kolomnya sudah hilang dari database
# tenant test.
#
# Yang hilang bersamanya bukti **perilaku** salinan beku itu. Yang
# tersisa dua bukti yang justru menjawab pertanyaan yang membuat
# pembekuannya mendesak:
#
# * `FrozenMigrationsImportNothingLiveTests` di atas — kedua migration
#   tidak mengimpor satu pun kode aplikasi dan menyelesaikan modelnya
#   lewat `apps.get_model()`. Ini yang menjaga migration tetap berarti
#   sama sesudah model nyatanya dihapus.
# * `FreshTenantSchemaTests` di bawah — rantai migration penuh benar-benar
#   diputar ulang untuk schema tenant **baru**. Itu jalur yang paling
#   sering ditempuh dan yang paling mahal kalau rusak:
#   `auto_create_schema` memutar seluruh rantai tiap tenant dibuat, jadi
#   migration yang mengimpor kode aplikasi menggagalkan **pembuatan
#   tenant**, bukan sekadar pemutaran ulang riwayat.
#
# Keduanya tidak menyentuh kolom lama, jadi keduanya selamat — dan
# keduanya masih bisa merah.


class FreshTenantSchemaTests(TransactionTestCase):
    """
    Schema tenant baru dibuat dari nol lewat rantai migration penuh.

    `TransactionTestCase`, bukan `TestCase`: `auto_create_schema`
    menjalankan `migrate_schemas` pada koneksinya sendiri, dan itu tidak
    terlihat dari dalam transaksi yang di-rollback.
    """

    serialized_rollback = False

    def setUp(self):
        super().setUp()

        self.schema = f"fresh{uuid.uuid4().hex[:10]}"

    def tearDown(self):
        # `auto_drop_schema = False` pada model tenant, jadi schema-nya
        # dibuang di sini — kalau tidak, tiap kali test ini jalan ia
        # meninggalkan satu schema yatim di database.
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')

        super().tearDown()

    def test_a_new_tenant_replays_the_whole_chain(self):
        tenant = get_tenant_model()(
            schema_name=self.schema,
            code=self.schema,
            name="Fresh Tenant",
        )

        # Di sinilah rantai migration penuh dijalankan. Sebelum
        # pembekuan, baris ini yang akan gagal begitu gelombang C
        # menghapus model lama.
        tenant.save()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = %s",
                [self.schema],
            )

            self.assertIsNotNone(
                cursor.fetchone(), "schema tenant tidak terbentuk")

        with schema_context(self.schema):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s",
                    [self.schema],
                )

                tables = {row[0] for row in cursor.fetchall()}

        for table in (
            "auth_users_roles",
            "accounts_role_assignment_authority",
            "accounts_role",
        ):
            self.assertIn(table, tables, f"{table} tidak dibuat")

        with schema_context(self.schema):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT name FROM django_migrations "
                    "WHERE app = 'accounts'"
                )

                applied = {row[0] for row in cursor.fetchall()}

        for name in (
            "0011_backfill_assignment_authority",
            "0012_close_blank_assignment_authority",
        ):
            self.assertIn(
                name, applied,
                f"{name} tidak tercatat diterapkan pada schema baru",
            )

    def test_the_new_schema_starts_with_no_assignments_at_all(self):
        """
        Sisi yang membuat pembekuan itu aman: pada schema baru kedua
        migration memang tidak mengerjakan apa-apa. Yang dipulihkan
        pembekuan bukan hasilnya, melainkan kemampuannya berjalan.
        """
        tenant = get_tenant_model()(
            schema_name=self.schema,
            code=self.schema,
            name="Fresh Tenant",
        )

        tenant.save()

        with schema_context(self.schema):
            from apps.accounts.models import RoleAssignment

            self.assertEqual(RoleAssignment.objects.count(), 0)
