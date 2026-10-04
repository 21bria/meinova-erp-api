"""
Kelas dasar test tenant yang **memakai ulang schema**.

Kenapa ada
----------
`TenantTestCase` django-tenants membangun schema tenant di `setUpClass`
dan membuangnya di `tearDownClass`. Di repositori ini satu schema tenant
berisi ~230 tabel dari 25 `TENANT_APPS`, dan biayanya **terukur ~90
detik per kelas** — bukan per run. Tiga modul regresi HR punya 59 kelas
seperti itu; badan test-nya sendiri berjalan sekitar 0,11 detik per
test. Hampir seluruh waktu run dihabiskan membangun dan membuang schema
yang isinya sama persis.

`FastTenantTestCase` memakai ulang satu schema, tapi apa adanya ia
menyimpan tiga jebakan yang membuat penggantian langsung tidak aman:

1. **Nama schema tetap.** Bawaannya `fast_test` untuk semua orang, jadi
   dua modul yang jalan bersamaan bertabrakan di
   `tenants_client_schema_name_key`. Kelas ini menuntut tiap pemakai
   menyebut namanya sendiri lewat `reusable_schema_name`.

2. **Schema yang sudah ada tidak pernah dimigrasikan** oleh
   `FastTenantTestCase` sendiri. Dengan `--keepdb` schema-nya hidup
   lintas run, jadi migrasi baru tidak ikut terpasang lewat jalur itu.

   Dalam pemakaian normal lubang ini sudah tertutup dari arah lain:
   django-tenants mengganti perintah `migrate` dengan
   `migrate_schemas` (lihat
   `django_tenants/management/commands/migrate.py`), jadi
   `DiscoverRunner.setup_databases()` memigrasikan **seluruh** schema
   tenant — termasuk yang dipakai ulang — sebelum satu test pun jalan.
   Terukur: satu catatan migrasi yang dihapus dari schema yang dipakai
   ulang sudah dipasang kembali sebelum kelas pertama dimuat.

   Penjaga di `use_existing_tenant()` karena itu **lapis kedua**,
   bukan satu-satunya: ia menangkap schema yang tidak ikut lewat
   bootstrap itu — dibuat di luar runner, tenant-nya belum terdaftar
   saat bootstrap jalan, atau riwayatnya bergeser sesudahnya. Kalau
   tertinggal, schema-nya dibangun ulang, bukan dipakai apa adanya.

3. **Data tingkat kelas bocor.** `setUpClass` tidak ikut di-rollback,
   jadi baris yang dibuatnya menetap di schema dan kelas berikutnya
   menabrak unique constraint. Karena itu `build_baseline()` **wajib
   idempoten**.

Yang **tidak** berubah: tiap test tetap berjalan di dalam transaksi dan
tetap di-rollback sesudahnya. Itu mesin `django.test.TestCase`, bukan
milik django-tenants, dan penggantian kelas dasar tidak menyentuhnya.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django_tenants.test.cases import FastTenantTestCase
from django_tenants.utils import (
    app_labels,
    get_tenant_domain_model,
    schema_context,
    schema_exists,
)


def _tenant_app_labels() -> set[str]:
    """Label app yang migrasinya memang hidup di schema tenant."""
    return set(app_labels(settings.TENANT_APPS))


def expected_tenant_migrations() -> set[tuple[str, str]]:
    """
    `(app_label, migration_name)` yang **seharusnya** ada di schema
    tenant, dibaca dari disk.

    Dibaca dari `disk_migrations`, bukan dari `graph`: yang dicari
    adalah berkas yang ada, bukan urutan penerapannya.
    """
    loader = MigrationLoader(None, ignore_no_migrations=True)
    labels = _tenant_app_labels()

    return {key for key in loader.disk_migrations if key[0] in labels}


def applied_tenant_migrations(schema_name: str) -> set[tuple[str, str]]:
    """`(app_label, name)` yang tercatat terpasang di satu schema."""
    with schema_context(schema_name):
        recorder = MigrationRecorder(connection)

        if not recorder.has_table():
            return set()

        labels = _tenant_app_labels()

        return {
            key for key in recorder.applied_migrations() if key[0] in labels
        }


def missing_tenant_migrations(schema_name: str) -> set[tuple[str, str]]:
    """Migrasi yang ada di disk tapi belum terpasang di schema itu."""
    if not schema_exists(schema_name):
        return expected_tenant_migrations()

    return expected_tenant_migrations() - applied_tenant_migrations(
        schema_name,
    )


class ReusableTenantTestCase(FastTenantTestCase):
    """
    Schema tenant dibangun **sekali**, lalu dipakai ulang.

    Kontrak untuk yang menurunkannya:

    * `reusable_schema_name` wajib diisi, dan **unik per modul**;
    * `build_baseline()` wajib idempoten — ia dipanggil sekali per
      kelas, di atas schema yang isinya mungkin sudah ada;
    * data yang bisa berubah dibuat di dalam test, bukan di
      `build_baseline()`, supaya ikut di-rollback.
    """

    reusable_schema_name: str | None = None

    #: Diisi penjaga migrasi supaya laporan/test bisa membacanya.
    schema_was_rebuilt: bool = False

    # ------------------------------------------------------------------
    # Identitas schema
    # ------------------------------------------------------------------

    @classmethod
    def get_test_schema_name(cls) -> str:
        if not cls.reusable_schema_name:
            raise AssertionError(
                f"{cls.__name__} memakai ReusableTenantTestCase tapi "
                "belum menyebut `reusable_schema_name`. Tanpa itu ia "
                "memakai schema `fast_test` bersama modul lain dan "
                "bertabrakan di tenants_client_schema_name_key.",
            )

        return cls.reusable_schema_name

    @classmethod
    def get_test_tenant_domain(cls) -> str:
        """
        Nama host untuk `TenantClient`, diturunkan dari nama schema
        dengan **garis bawah diganti tanda hubung**.

        Garis bawah sah di nama schema PostgreSQL dan **tidak sah** di
        nama host. `request.get_host()` menolaknya lewat
        `host_validation_re`, `TenantMainMiddleware.process_request()`
        pulang lebih awal dengan 404 — dan karena baris pertamanya
        `connection.set_schema_to_public()`, koneksinya **ditinggalkan
        di public**. Test berikutnya lalu gagal dengan "relation ...
        does not exist", jauh dari sebabnya.

        Yang paling berbahaya bukan test yang gagal: test yang memang
        mengharapkan 404 akan **lulus karena alasan yang salah**.
        """
        return f"{cls.get_test_schema_name().replace('_', '-')}.fast-test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        """
        Identitas tenant bawaan, diturunkan dari nama schema.

        `tenants_client.code` unique dan baris tenant yang dipakai ulang
        hidup selamanya, jadi dua kelas yang lupa menyebut kodenya akan
        bertabrakan begitu keduanya ada bersamaan — keadaan yang tidak
        pernah terjadi waktu tiap kelas punya tenant sekali pakai.
        Menurunkannya dari nama schema membuat keunikannya mengikuti
        keunikan yang sudah wajib.
        """
        tenant.code = cls.get_test_schema_name().replace("_", "-")
        tenant.name = cls.get_test_schema_name().replace("_", " ").title()

    # ------------------------------------------------------------------
    # Penjaga kebasian migrasi
    # ------------------------------------------------------------------

    @classmethod
    def use_existing_tenant(cls) -> None:
        """
        Dipanggil django-tenants saat schema-nya sudah ada.

        Di sinilah satu-satunya tempat yang tahu bahwa schema lama
        sedang dipakai ulang — dan karena itu satu-satunya tempat yang
        bisa menolak memakainya kalau sudah basi.
        """
        schema = cls.get_test_schema_name()
        missing = missing_tenant_migrations(schema)

        if not missing:
            cls.schema_was_rebuilt = False

            return

        cls._rebuild_schema(missing=missing)

    @classmethod
    def _rebuild_schema(cls, *, missing) -> None:
        """
        Buang schema basinya lalu bangun ulang dari migrasi terkini.

        Dibangun ulang seluruhnya, bukan dimigrasikan di tempat:
        `migrate_schemas` pada schema yang riwayatnya tidak utuh bisa
        berhenti di tengah dan meninggalkan bentuk yang lebih sulit
        dijelaskan daripada schema yang hilang.
        """
        sample = sorted(missing)[:3]

        print(
            f"\n[ReusableTenantTestCase] schema "
            f"{cls.get_test_schema_name()!r} tertinggal "
            f"{len(missing)} migrasi (mis. {sample}); dibangun ulang.",
            flush=True,
        )

        domain_model = get_tenant_domain_model()
        domain_model.objects.filter(tenant=cls.tenant).delete()
        cls.tenant.delete(force_drop=True)

        cls.setup_test_tenant_and_domain()

        cls.schema_was_rebuilt = True

    # ------------------------------------------------------------------
    # Siklus hidup
    # ------------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        # `super()` yang memutuskan bangun-atau-pakai-ulang, dan baru di
        # baris terakhirnya koneksi dipindah ke schema tenant. Karena
        # itu baseline dibangun **sesudahnya** — hook `use_new_tenant()`
        # bawaan django-tenants berjalan saat koneksi masih di public,
        # dan apa pun yang ditulis di sana mendarat di schema yang
        # salah.
        super().setUpClass()

        # Identitas ditulis **di luar** atomik kelas: baris tenant dan
        # domain hidup di `public` dan memang harus bertahan.
        cls._ensure_identity()

        # Atomik tingkat kelas — yang dilewatkan django-tenants.
        #
        # `TestCase.setUpClass()` milik Django membuka transaksi kelas
        # lalu me-rollback-nya di `tearDownClass()`. `TenantTestCase`
        # maupun `FastTenantTestCase` tidak pernah memanggil
        # `super().setUpClass()`, jadi transaksi itu tidak pernah ada:
        # apa pun yang dibuat `setUpClass` **commit** dan menetap.
        #
        # Selama schema dibuang tiap kelas, hal itu tidak terlihat —
        # schema-nya ikut hilang. Begitu schema dipakai ulang, baris
        # tingkat kelas menumpuk antar kelas **dan antar run**, dan
        # kelas kedua menabrak unique constraint pada kode yang
        # diturunkan dari penghitung yang dimulai ulang dari nol.
        #
        # Membukanya kembali di sini memulihkan semantik `TestCase`
        # apa adanya: data tingkat kelas hidup selama kelasnya, lalu
        # hilang. Atomik per-test bersarang di dalamnya, persis seperti
        # rancangan Django.
        # Atomik yang menggantung dari kelas sebelumnya, kalau ada.
        #
        # unittest **tidak** memanggil `tearDownClass` ketika
        # `setUpClass` gagal, jadi kelas yang meledak sesudah baris ini
        # meninggalkan transaksinya terbuka dan rusak. Tanpa
        # dibereskan, setiap kelas berikutnya gagal dengan
        # `TransactionManagementError` — satu kegagalan berubah jadi
        # ratusan, dan yang pertama tenggelam.
        dangling = getattr(cls, "cls_atomics", None)

        if dangling:
            # Hanya kalau transaksinya memang masih terbuka.
            # `_rollback_atomics()` memanggil `set_rollback(True)`, dan
            # di luar blok atomic itu sendiri melempar — kegagalan
            # pembersihan yang menutupi kegagalan aslinya.
            if connection.in_atomic_block:
                try:
                    cls._rollback_atomics(dangling)
                except Exception:
                    pass

            cls.cls_atomics = None

        cls.cls_atomics = cls._enter_atomics()

        try:
            cls.build_baseline()
        except Exception:
            # Bereskan tanpa menutupi sebab aslinya: kalau
            # pembersihannya sendiri melempar, yang terbaca di laporan
            # adalah kegagalan pembersihan, bukan kegagalan yang
            # sebenarnya terjadi.
            if connection.in_atomic_block:
                try:
                    cls._rollback_atomics(cls.cls_atomics)
                except Exception:
                    pass

            cls.cls_atomics = None

            raise

    @classmethod
    def tearDownClass(cls):
        atomics = getattr(cls, "cls_atomics", None)

        if atomics:
            cls._rollback_atomics(atomics)
            cls.cls_atomics = None

        super().tearDownClass()

    @classmethod
    def _ensure_identity(cls) -> None:
        """
        Samakan identitas tenant yang dipakai ulang dengan yang
        dideklarasikan kelasnya.

        Baris tenant yang dipakai ulang **tidak pernah lewat
        `setup_tenant()` lagi** — django-tenants hanya memanggilnya saat
        baris itu pertama dibuat. Jadi kode, nama, dan domain yang
        tersimpan bisa tertinggal dari yang dinyatakan kelasnya, dan
        yang tertinggal itu diam: kode basi menabrak
        `tenants_client_code_key` milik kelas sekali pakai, domain basi
        membuat setiap request mendarat di public.

        Ditulis lewat `.update()`, bukan `.save()`: `save()` pada model
        tenant menjalankan logika pembuatan schema, dan di sini tidak
        ada satu pun yang perlu dibuat.
        """
        from django_tenants.utils import get_tenant_model

        probe = get_tenant_model()()
        cls.setup_tenant(probe)

        fields = {
            name: getattr(probe, name)
            for name in ("code", "name")
            if getattr(probe, name, None)
            and getattr(cls.tenant, name, None) != getattr(probe, name)
        }

        if fields:
            get_tenant_model().objects.filter(pk=cls.tenant.pk).update(**fields)

            for name, value in fields.items():
                setattr(cls.tenant, name, value)

        domain_model = get_tenant_domain_model()
        expected = cls.get_test_tenant_domain()

        domain = domain_model.objects.filter(tenant=cls.tenant).first()

        if domain is None:
            cls.domain = domain_model.objects.create(
                tenant=cls.tenant, domain=expected, is_primary=True,
            )
        elif domain.domain != expected or not domain.is_primary:
            domain_model.objects.filter(pk=domain.pk).update(
                domain=expected, is_primary=True,
            )

            cls.domain = domain_model.objects.get(pk=domain.pk)
        else:
            cls.domain = domain

    def _pre_setup(self):
        """
        Bersihkan cache proses sebelum tiap test.

        Rollback transaksi mengurus basis data, **tidak** mengurus apa
        pun yang disimpan di memori proses. Selama schema dibuang tiap
        kelas hal itu tidak pernah terlihat; begitu schema dipakai
        ulang, nilai yang ditulis satu kelas terbaca kelas berikutnya
        dan urutan eksekusi mulai menentukan hasil.

        Hari ini tidak ada resolver bisnis yang memoisasi (tidak ada
        `lru_cache` maupun `django.core.cache` di apps/hr, apps/workflow
        dan apps/administration), jadi ini penjaga untuk yang datang
        nanti — bukan tambalan untuk kebocoran yang sudah ada.
        """
        from django.core.cache import caches

        for cache in caches.all():
            cache.clear()

        super()._pre_setup()

    @classmethod
    def build_baseline(cls) -> None:
        """
        Data pondasi yang tidak berubah, **idempoten**.

        Dipanggil sekali per kelas di atas schema yang dipakai bersama,
        jadi `objects.create()` di sini akan menabrak unique constraint
        pada kelas kedua. Pakai `get_or_create(..., is_deleted=False)`.
        """
        return None
