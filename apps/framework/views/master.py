import csv

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.fields import is_simple_callable
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.accounts.permissions import (
    ModelPermission,
    required_scope_permission,
)
from apps.accounts.scoping import DataScopeService
from apps.core.pagination import StandardPagination
from apps.framework.filters import SafeSearchFilter
from apps.framework.introspection import build_ui_schema
from apps.framework.views.ui_schema import UISchemaMixin


class BaseMasterViewSet(UISchemaMixin, ModelViewSet):
    schema_type = "crud"
    permission_classes = [IsAuthenticated, ModelPermission]
    pagination_class = StandardPagination

    # Dimatikan per viewset untuk resource yang penjagaannya lebih
    # spesifik daripada "boleh mengubah tabel ini" — Security memakai
    # `CanManageSecurity`, konfigurasi alur memakai `CanConfigureWorkflow`.
    # Lihat `apps.accounts.permissions.ModelPermission`.
    enforce_model_permissions = True

    # Baca ikut dijaga izin model (`view_<model>`), bukan cuma tulis.
    #
    # Bawaannya `False`, dan itu bukan kemalasan: membaca memang dibuka
    # lebar di seluruh sistem karena dropdown dan lookup dipakai lintas
    # modul, dan menutupnya serentak akan mengunci hampir semua orang
    # dari hampir semua layar.
    #
    # Dinyalakan pada resource yang isinya sendiri sudah rahasia — slip
    # gaji, rekening bank, catatan medis, kepesertaan BPJS. Untuk
    # resource semacam itu "boleh login" bukan alasan yang cukup.
    #
    # **Wajib berpasangan dengan `data_scope`.** Izin menjawab jenis
    # datanya, cakupan menjawab baris siapa; salah satu saja tidak
    # cukup. Dijaga `test_view_permission_gate` supaya pasangan itu
    # tidak diam-diam terlepas saat viewset baru ditambahkan.
    require_view_permission = False

    # Peta `{jenis sumber daya: jalur ORM}` untuk penyaringan data per
    # baris (kewenangan `RoleAssignment`). `None` = tidak disaring sama sekali,
    # dan itu bawaan yang benar untuk master data: jenis cuti dan mata
    # uang bukan rahasia per lokasi.
    #
    # Contoh untuk Employee (organisasinya di relasi, bukan di kolom):
    #     data_scope = {
    #         "company": "organization__company",
    #         "location": "organization__location",
    #         "section": "organization__section",
    #         "own": "user_id",
    #     }
    #
    # Lihat `apps.accounts.scoping.DataScopeService`.
    data_scope = None

    # Aksi kustom yang punya izin/kemampuannya sendiri, ditulis
    # `{nama aksi: "app_label.codename"}`.
    #
    # CRUD baku sudah diturunkan sendiri (`change_*` untuk update,
    # `delete_*` untuk hapus); yang perlu dinyatakan cuma aksi yang
    # namanya tidak bisa ditebak dari kata kerja CRUD — pencatatan
    # administratif cuti (`hr.record_employeeleave`), misalnya.
    #
    # Kosong = aksi kustom memakai semantik baca, persis seperti
    # sebelumnya. Lihat `apps.accounts.permissions.required_scope_permission`.
    action_scope_permissions: dict[str, str] = {}

    # Dokumen yang dijalankan lewat engine persetujuan, ditulis
    # `(module, document_type)` — pasangan yang sama dengan yang
    # didaftarkan ke `apps.workflow.registry`. Contoh untuk cuti:
    #
    #     workflow_document = ("hr", "leave_request")
    #
    # Diisi = peserta alur (pemegang meja, penerima kuasanya, dan yang
    # pernah menekan tombolnya) boleh **membaca** dokumen yang
    # ditagihkan kepadanya sekalipun cakupan datanya tidak mencakup
    # baris itu. Kosong = perilaku lama, cakupan data satu-satunya
    # penentu.
    #
    # Kenapa perlu: kotak masuk approval dan dokumennya dijaga dua lapis
    # yang berbeda dan tidak saling mengenal. Atasan langsung lazimnya
    # bercakupan `own`, jadi ia ditagih menyetujui dokumen yang tidak
    # bisa ia buka — 404 yang berbunyi seperti dokumennya hilang.
    workflow_document = None

    # Aksi non-baca yang tetap boleh dijalankan peserta alur. **Hanya
    # keputusan alurnya**, bukan penyuntingan: memutuskan dokumen orang
    # lain memang wewenang approver, mengubah isinya tidak. Karena itu
    # `update`/`partial_update`/`destroy` sengaja **tidak** ada di sini —
    # approver yang mencoba menyunting kembali jatuh ke cakupan datanya
    # sendiri, dan itu memang jawaban yang benar.
    workflow_participant_actions = ("approve", "reject", "send_back")

    filter_backends = [
        DjangoFilterBackend,
        SafeSearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = ["code", "name"]
    ordering_fields = "__all__"
    ordering = ["name"]

    service_class = None

    framework_module = None
    ui_schema = {}

    def get_permissions(self):
        """
        `ModelPermission` dipasang di sini, bukan cuma di
        `permission_classes`.

        Puluhan viewset menulis ulang `permission_classes` — kebanyakan
        cuma mengulang `[IsAuthenticated]` yang sudah jadi bawaan — dan
        itu **mengganti** daftarnya, bukan menambah. Kalau penjagaannya
        hanya ada di atribut kelas, setiap viewset semacam itu kehilangan
        kuncinya tanpa satu pesan pun; `CurrencyViewSet` sudah terbukti
        begitu. Dengan dipasang di sini, viewset yang punya penjagaan
        sendiri mendapat keduanya, dan yang memang tidak boleh dijaga
        izin model menyatakannya lewat `enforce_model_permissions`.
        """
        permissions = super().get_permissions()

        if not getattr(self, "enforce_model_permissions", True):
            return permissions

        if any(isinstance(item, ModelPermission) for item in permissions):
            return permissions

        return [*permissions, ModelPermission()]

    def filter_queryset(self, queryset):
        """
        Penyaringan baris dipasang di sini, **bukan** di `get_queryset()`.

        Dua alasan, dan yang kedua yang menentukan:

        1. `get_object()` milik DRF memanggil
           `filter_queryset(get_queryset())`, begitu pula `list()`,
           `export/`, dan `bulk-delete/`. Satu tempat ini menutup daftar,
           detail by id, export, hapus, **dan** update sekaligus — tanpa
           itu data tetap terbaca lewat `/api/hr/employees/160/` (nomor
           urut tinggal ditebak) dan tetap bisa diubah lewat PATCH.
        2. **41 viewset menimpa `get_queryset()` sendiri.** Kalau
           penyaringannya dipasang di sana, semuanya lolos diam-diam —
           persis cara `CurrencyViewSet` lolos dari izin model.
        """
        queryset = super().filter_queryset(queryset)

        request = getattr(self, "request", None)

        if request is None:
            return queryset

        user = getattr(request, "user", None)

        # Izin yang sedang dijalankan ikut dikirim, jadi cakupannya
        # dihitung **hanya dari role yang memberi izin itu**.
        #
        # Satu konteks otorisasi: nama izin yang sama persis yang barusan
        # dipakai `ModelPermission` untuk meloloskan request ini —
        # `view_*` saat membaca, `change_*` saat menyunting, `delete_*`
        # saat menghapus. Lihat `required_scope_permission()`: sebelum
        # ini semua aksi memakai izin baca, dan pada resource yang
        # bacanya tidak dijaga itu berarti gabungan seluruh role, jadi
        # cakupan baca yang luas ikut melebarkan hak ubah dan hapus.
        scoped = DataScopeService.filter(
            queryset,
            getattr(self, "data_scope", None),
            user,
            required_permission=required_scope_permission(self),
        )

        return self._widen_for_workflow_participants(
            base=queryset,
            scoped=scoped,
            request=request,
        )

    def _widen_for_workflow_participants(self, *, base, scoped, request):
        """
        Menambahkan dokumen yang orangnya ikut sebagai peserta alur.

        **Penambah, bukan pengganti.** Cakupan data tetap dihitung lebih
        dulu dan tetap berlaku utuh; yang ditambahkan cuma baris yang
        memang ditagihkan kepada orang itu lewat `WorkflowApproval`.
        Yang bukan peserta alur tidak mendapat satu baris pun dari sini.

        Dibatasi ke **membaca** dan ke keputusan alurnya sendiri (lihat
        `workflow_participant_actions`). Tiga jenis akses yang sering
        tertukar dan sengaja dipisah di sini:

        * membaca dokumennya — approver butuh, dan itu yang diberikan;
        * menjalankan keputusan alur — approver butuh, dijaga sendiri
          oleh `WorkflowApprovalService.check_right`;
        * menyunting isinya — approver **tidak** butuh. Dokumen yang
          salah dikembalikan lewat Return, bukan dibetulkan diam-diam
          oleh orang yang seharusnya menilainya.

        Tanpa pemisahan itu, dokumen yang sudah dikembalikan (dan karena
        itu bisa disunting lagi) akan ikut bisa disunting oleh approver
        yang mengembalikannya — persis kebocoran yang mau dicegah.
        """
        document = getattr(self, "workflow_document", None)

        if not document:
            return scoped

        if scoped is base:
            # Tanpa batasan cakupan — tidak ada yang perlu dilebarkan.
            return scoped

        if request.method not in SAFE_METHODS:
            allowed = getattr(self, "workflow_participant_actions", ()) or ()

            if (getattr(self, "action", None) or "") not in allowed:
                return scoped

        from apps.workflow import selectors as workflow_selectors

        module, document_type = document

        object_ids = workflow_selectors.participant_object_ids(
            getattr(request, "user", None),
            module=module,
            document_type=document_type,
        )

        # `object_id` disimpan sebagai teks — satu kolom untuk dokumen
        # dari modul mana pun, termasuk yang kuncinya bukan angka.
        # Yang tidak bisa dibaca sebagai kunci di sini dilewati, bukan
        # membuat seluruh querysetnya gagal.
        keys = [value for value in object_ids if str(value).isdigit()]

        if not keys:
            return scoped

        return (scoped | base.filter(pk__in=keys)).distinct()

    def get_queryset(self):
        if (
            self.service_class is not None
            and hasattr(
                self.service_class,
                "list",
            )
        ):
            return self.service_class.list()

        queryset = getattr(
            self,
            "queryset",
            None,
        )

        if queryset is None:
            raise AssertionError(
                (
                    f"{self.__class__.__name__} must define "
                    "`queryset`, override `get_queryset()`, "
                    "or provide service_class.list()."
                )
            )

        return queryset.all()

    def perform_soft_delete(self, instance, user):
        """
        Satu-satunya jalur penghapusan, dipakai `destroy()` maupun
        `bulk_delete()` supaya perilakunya tidak berbeda.

        Urutan: service punya `soft_delete` -> pakai itu (ada hook-nya);
        model punya kolom `is_deleted` -> tandai terhapus; selain itu
        baru hard delete, karena tidak ada tempat menyimpan jejaknya.
        """
        service_class = self.service_class

        if service_class is not None and hasattr(
            service_class,
            "soft_delete",
        ):
            service_class.soft_delete(
                instance=instance,
                user=user,
            )

            return

        if not hasattr(instance, "is_deleted"):
            self.perform_destroy(instance)

            return

        instance.is_deleted = True

        update_fields = ["is_deleted"]

        if hasattr(instance, "deleted_at"):
            instance.deleted_at = timezone.now()
            update_fields.append("deleted_at")

        if hasattr(instance, "deleted_by"):
            instance.deleted_by = (
                user
                if user is not None and user.is_authenticated
                else None
            )
            update_fields.append("deleted_by")

        if hasattr(instance, "updated_at"):
            update_fields.append("updated_at")

        instance.save(update_fields=update_fields)

    def destroy(
        self,
        request,
        *args,
        **kwargs,
    ):
        self.perform_soft_delete(
            self.get_object(),
            request.user,
        )

        return Response(
            {
                "detail": "Data berhasil dihapus.",
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="ui-schema",
        permission_classes=[AllowAny],
    )
    def ui_schema_view(self, request):
        return Response(
            build_ui_schema(
                self,
                request,
            )
        )

    # ------------------------------------------------------------------
    # Bulk delete
    # ------------------------------------------------------------------

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-delete",
    )
    def bulk_delete(self, request):
        raw_ids = request.data.get("ids", [])

        if not isinstance(raw_ids, (list, tuple)):
            return Response(
                {
                    "detail": "Field 'ids' harus berupa list.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ids = [
            str(value).strip()
            for value in raw_ids
            if str(value).strip()
        ]

        if not ids:
            return Response(
                {
                    "detail": "Tidak ada data yang dipilih.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            queryset = list(
                self.filter_queryset(
                    self.get_queryset(),
                ).filter(pk__in=ids)
            )
        except (ValidationError, ValueError, TypeError):
            # Satu id yang bentuknya tidak cocok dengan tipe primary key
            # resource ini membuat Django melempar saat menyusun query —
            # dan tanpa penangkapan ini jawabannya 500, yang terbaca
            # seperti server rusak padahal masukannya yang salah.
            return Response(
                {
                    "detail": "Ada id yang formatnya tidak valid.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted = 0

        for instance in queryset:
            self.perform_soft_delete(
                instance,
                request.user,
            )

            deleted += 1

        return Response(
            {
                "detail": f"{deleted} data berhasil dihapus.",
                "deleted": deleted,
                "requested": len(ids),
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    # Field audit yang tidak pernah ikut diexport.
    EXPORT_EXCLUDED_FIELDS = {
        "id",
        "created_at",
        "updated_at",
        "is_deleted",
        "deleted_at",
        "created_by",
        "updated_by",
        "deleted_by",
    }

    def get_export_fields(self, request) -> list[tuple[str, str]]:
        """
        Kolom export mengikuti kolom tabel di frontend.

        Sengaja memakai schema hasil `build_ui_schema` (bukan override
        statis) dan mempertahankan urutan aslinya, supaya file export
        sama persis dengan apa yang dilihat user di tabel.

        `export=False` datang dari introspeksi model untuk field yang
        memang tidak bisa diekspor (file, image, many-to-many), jadi
        dipakai sebagai penyaring, bukan sebagai penanda kurasi.
        """
        schema = build_ui_schema(self, request)

        fields = schema.get("fields", {}) or {}

        def is_exported(field_name: str) -> bool:
            options = fields.get(field_name)

            if options is None:
                return False

            if field_name in self.EXPORT_EXCLUDED_FIELDS:
                return False

            return (
                options.get("table") is not False
                and options.get("export") is not False
            )

        columns: list[tuple[str, str]] = []

        for name, options in fields.items():
            if not is_exported(name):
                continue

            # Kolom kembar `<x>` + `<x>_name`.
            #
            # Field lookup dideklarasikan schema (`company`, `table=True`)
            # sementara pasangan tampilannya lahir dari introspeksi
            # serializer (`company_name`) yang **tidak** menyebut `table`
            # sama sekali. Penyaring di atas cuma membuang `table is
            # False`, jadi yang tidak menyebutnya ikut lolos — dan CSV-nya
            # memuat "Company" dan "Company name" yang isinya sama persis.
            #
            # Tabel di layar tidak kena karena generator FE memetakan
            # field lookup ke `<x>_name` dan merendernya sebagai **satu**
            # kolom. Selisih itu yang membuatnya lama tidak ketahuan:
            # yang membandingkan layar dengan file export menyimpulkan
            # export-nya yang menambah kolom entah dari mana.
            #
            # Yang dibuang pasangan `_name`-nya, bukan sebaliknya:
            # `<x>` membawa label yang ditulis orang di schema
            # ("Company"), sementara `<x>_name` cuma punya label turunan
            # ("Company name"). Keduanya menghasilkan nilai yang sama —
            # `resolve_export_value` sudah menurunkan `.name` dari
            # instance relasinya.
            #
            # Dibuang **hanya kalau pasangannya benar-benar ikut**, jadi
            # `reports_to_name` dan kawan-kawannya yang `<x>`-nya
            # `table=False` tetap utuh — di situ merekalah satu-satunya
            # yang mewakili datanya.
            if name.endswith("_name") and is_exported(name[: -len("_name")]):
                continue

            columns.append((
                name,
                str(
                    options.get("label")
                    or name.replace("_", " ").title()
                ),
            ))

        return columns

    def get_export_sources(self) -> dict[str, str]:
        """
        Peta `{nama field: jalur atribut}` dari serializer.

        Export membaca **instance**, bukan hasil serializer, jadi kolom
        turunan seperti `employee_number` — yang di serializer memang
        `CharField(source="employee.employee_number")` — tidak punya
        atribut senama di model dan keluar **kosong di semua baris**.
        Gagalnya diam dan ke arah yang paling menyesatkan: kolomnya ada
        di tabel, ada di header CSV, isinya saja yang tidak pernah ada,
        jadi terbaca seperti data yang memang belum diisi.

        Yang dipakai `source` milik serializer, bukan daftar tersendiri
        per viewset: dua daftar yang harus tetap sama cepat atau lambat
        berbeda, dan yang menentukan isi kolom sudah tertulis di sana.
        """
        serializer_class = getattr(self, "serializer_class", None)

        if serializer_class is None:
            return {}

        try:
            fields = serializer_class().fields
        except Exception:
            # Serializer yang perlu context tidak boleh menggagalkan
            # export — jalur `getattr` biasa tetap melayani.
            return {}

        return {
            name: field.source
            for name, field in fields.items()
            # `*` milik SerializerMethodField: nilainya dihitung, bukan
            # diambil dari atribut, jadi tidak ada jalur yang bisa
            # ditelusuri di sini.
            if field.source
            and field.source != "*"
            and field.source != name
        }

    @staticmethod
    def resolve_export_value(instance, field_name: str) -> str:
        value = instance

        # `source` boleh menembus relasi (`employee.employee_number`).
        for part in str(field_name).split("."):
            value = getattr(value, part, None)

            if value is None:
                return ""

            # Ruas yang berupa method dipanggil, bukan dicetak.
            #
            # Peta sumbernya dibaca dari `source` milik serializer, dan
            # `source` memang boleh menunjuk method — `roster_start_basis
            # _label` menunjuk `get_roster_start_basis_display`. DRF
            # memanggilnya (`is_simple_callable` di `get_attribute`);
            # export dulu tidak, jadi selnya berisi **repr Python**:
            #
            #   functools.partial(<bound method Model._get_FIELD_display
            #   of <RosterPolicy: ...>>, field=<...CharField: ...>)
            #
            # Dipakai helper milik DRF, bukan `callable()` polos: yang
            # kedua ikut memanggil manager dan kelas model, dan sebuah
            # `.objects` yang tereksekusi di tengah export jauh lebih
            # merusak daripada satu sel yang jelek.
            if is_simple_callable(value):
                value = value()

                if value is None:
                    return ""

        if hasattr(value, "name"):
            return str(value.name)

        if hasattr(value, "pk"):
            return str(value)

        if isinstance(value, bool):
            return "Yes" if value else "No"

        return str(value)

    @action(
        detail=False,
        methods=["get"],
        url_path="export",
    )
    def export(self, request):
        columns = self.get_export_fields(request)

        if not columns:
            return Response(
                {
                    "detail": (
                        "Resource ini belum menentukan kolom export "
                        "pada schema-nya."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.filter_queryset(
            self.get_queryset(),
        )

        slug = str(
            getattr(self, "framework_module", "")
            or self.__class__.__name__.lower()
        ).strip("/").replace("/", "-")

        response = HttpResponse(
            content_type="text/csv",
        )

        response["Content-Disposition"] = (
            f'attachment; filename="{slug}-export.csv"'
        )

        writer = csv.writer(response)

        writer.writerow([label for _name, label in columns])

        sources = self.get_export_sources()

        for instance in queryset.iterator(chunk_size=500):
            writer.writerow([
                self.resolve_export_value(
                    instance,
                    sources.get(name, name),
                )
                for name, _label in columns
            ])

        return response