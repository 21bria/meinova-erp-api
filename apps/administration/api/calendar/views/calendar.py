from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.administration.models import HolidaySyncStatus
from apps.administration.services.holiday_sync import (
    HolidaySyncService,
    available_sources,
    get_provider,
)
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.administration.api.calendar.schema import (
    HOLIDAY_IMPORT_SCHEMA,
    ROSTER_CREW_SCHEMA,
    WORK_CALENDAR_IMPORT_SCHEMA,
)

from apps.administration.api.calendar.serializers.calendar import (
    HolidaySerializer,
    WorkCalendarSerializer,
    RosterCrewSerializer,
)
from apps.administration.api.calendar.services.calendar_service import (
    HolidayService,
    WorkCalendarService,
    RosterCrewService,
)


# Scope, Company, dan Location sebagai penyaring — dipakai Work
# Calendar dan Holiday.
#
# Keduanya dulu **wajib per company**, dan konsekuensinya terlihat di
# layar: satu hari libur nasional menghasilkan dua belas baris yang
# isinya identik kecuali kolom Company. Sekarang barisnya satu dan
# kolom yang menjelaskannya `applies_to` ("All Companies"), jadi
# penyaring Company menjawab pertanyaan yang berbeda: "apa yang khusus
# perusahaan ini", bukan "mana barisnya di antara dua belas".
#
# Hasil introspeksi memberi lookup filter **tanpa endpoint**, jadi
# dropdown-nya selalu kosong (dan sejak generator diperbaiki, dilewati
# sama sekali). Endpoint-nya harus disebut di sini.
# Kolom cakupan sebagai **satu kalimat**, bukan tiga kolom yang harus
# dibaca bersamaan.
#
# Introspeksi menemukan `applies_to` lewat serializer, tapi tanpa
# `type` — ia bukan field model — dan generator frontend melewati field
# tak bertipe. Akibatnya kolom yang paling menjelaskan baris GLOBAL
# ("All Companies") tidak pernah ikut digenerate, dan tabelnya kembali
# menampilkan Company kosong seperti sebelum task ini.
APPLIES_TO_FIELD = {
    "applies_to": {
        "type": "text",
        "widget": "text",
        "label": "Applies To",
        "table": True,
        "form": False,
        "filter": False,
        "sortable": False,
        "export": True,
        "read_only": True,
        "order": 6,
        # Tepat di sebelah kanan Scope. Urutan kolom mengikuti urutan
        # dict schema, dan field turunan serializer selalu ditempelkan
        # paling belakang — jadi tanpa ini "Applies To" mendarat di
        # kanan kolom audit, di luar layar, dan yang mencarinya
        # menyimpulkan kolomnya tidak pernah dibuat.
        "column_after": "scope",
    },
}


ORGANIZATION_FILTER_FIELDS = {
    "scope": {
        "filter": {"group": "quick", "order": 5},
        "order": 5,
    },

    "company": {
        "lookup_endpoint": (
            "/api/administration/organization/lookup/companies/"
        ),
        "display_key": "company_name",
        "filter": {"group": "quick", "order": 10},
        "order": 10,
    },

    "location": {
        "lookup_endpoint": (
            "/api/administration/organization/lookup/locations/"
        ),
        "display_key": "location_name",
        "depends_on": "company",
        "lookup_params": {"company_id": "$company"},
        "filter": {"group": "quick", "order": 20},
        "order": 20,
    },
}


# `FiscalYearViewSet` dan `PostingPeriodViewSet` pindah ke Finance:
# `apps/finance/api/fiscal_years/` dan `apps/finance/api/periods/`.
# `framework_module`-nya ikut pindah, jadi module frontend lamanya
# (`administration/calendar/{fiscal-year,posting-period}`) tidak bisa
# diregenerate lagi dan sudah dibuang bersama tabnya.


# Cakupan data untuk kedua master kalender.
#
# `allow_null=True` adalah bagian yang menentukan, dan menghilangkannya
# adalah bug yang paling mudah dibuat di sini. Bawaan
# `DATA_SCOPE_INCLUDE_NULL` adalah **False**: baris yang kolom
# company-nya kosong tidak terlihat oleh siapa pun yang bercakupan.
# Untuk model ini kolom kosong justru berarti "berlaku untuk semua",
# jadi tanpa `allow_null` justru libur nasional-lah yang menghilang
# dari layar setiap admin site — sementara libur perusahaan lain tetap
# tertutup rapat sebagaimana mestinya.
CALENDAR_SCOPE_MAP = {"company": "company", "location": "location"}


class CalendarScopedViewSetMixin:
    """
    Cakupan data yang memperlakukan kolom kosong sebagai "berlaku
    untuk semua", bukan sebagai "belum diisi".
    """

    data_scope = CALENDAR_SCOPE_MAP

    def filter_queryset(self, queryset):
        """
        Menimpa hanya untuk mengoper `allow_null=True`.

        `BaseMasterViewSet.filter_queryset()` memanggil
        `DataScopeService.filter()` tanpa argumen itu, dan menambahkan
        parameter ke base class akan mengubah perilaku 40-an viewset
        lain yang kolom kosongnya memang berarti "belum diisi".

        `super()` di sini melewati `BaseMasterViewSet.filter_queryset()`
        dan mendarat di DRF — pelebaran untuk peserta workflow tidak
        berlaku bagi master kalender (`workflow_document` kosong), jadi
        tidak ada yang hilang.
        """
        from apps.accounts.scoping import DataScopeService

        from rest_framework.viewsets import ModelViewSet

        queryset = ModelViewSet.filter_queryset(self, queryset)

        return DataScopeService.filter(
            queryset,
            self.data_scope,
            getattr(getattr(self, "request", None), "user", None),
            allow_null=True,
        )


class HolidayViewSet(CalendarScopedViewSetMixin, BaseMasterViewSet):
    """
    Selain cakupan bersama di atas, Holiday punya satu lubang yang harus
    ditutup sendiri: `SELECTED_COMPANIES`.

    Baris bercakupan itu menyimpan `company = NULL` — daftarnya ada di
    tabel relasi — jadi `allow_null=True` meloloskannya untuk **semua
    orang**, termasuk yang tidak satu pun perusahaannya ada di daftar
    itu. Untuk GLOBAL itu memang yang diinginkan; untuk yang "sebagian
    perusahaan", tidak: cuti bersama milik MMR tidak ada urusannya
    dengan admin yang bercakupan MLS.
    """

    serializer_class = HolidaySerializer
    service_class = HolidayService
    framework_module = "administration/calendar/holiday"
    schema_type = "crud"
    schema = {
        "title": "Holiday",
        "description": (
            "Manage public holidays and non-working days. "
            "A GLOBAL holiday is stored once and applies to every "
            "company, including companies created later."
        ),
        # Tanpa `endpoint` eksplisit, generator frontend menebaknya
        # dari slug module dan menghasilkan bentuk tunggal —
        # `/holiday/` — yang tidak terdaftar di router.
        "endpoint": "/api/administration/calendar/holidays/",
        "ui": {
            "import": True,
            "export": True,
            "bulk_delete": True,
        },
        "fields": {
            **ORGANIZATION_FILTER_FIELDS,
            **APPLIES_TO_FIELD,
            # Jejak sync: kolom, bukan isian. Yang mengubahnya tombol
            # Confirm/Reject di layar review, bukan form.
            "source": {"filter": {"group": "advanced", "order": 60}},
            "sync_status": {
                "form": False,
                "filter": {"group": "advanced", "order": 61},
            },
            **{
                field_name: {"form": False, "table": False, "filter": False}
                for field_name in ("external_id", "source_url", "synced_at")
            },
            # Daftar perusahaan untuk cakupan SELECTED_COMPANIES.
            #
            # Introspeksi membaca `PrimaryKeyRelatedField(many=True)`
            # sebagai field tanpa tipe, dan generator menurunkannya jadi
            # kolom teks biasa — kotak isian tempat orang mengetik id
            # perusahaan dengan tangan. Harus dinyatakan lookup
            # ber-`multiple` di sini.
            "company_ids": {
                "type": "lookup",
                "widget": "lookup",
                "label": "Companies",
                "lookup_endpoint": (
                    "/api/administration/organization/lookup/companies/"
                ),
                "multiple": True,
                "form": True,
                "table": False,
                "filter": False,
                "export": False,
                "required": False,
                "depends_on": "scope",
                "help_text": (
                    "Hanya untuk scope Selected Companies. Untuk "
                    "seluruh perusahaan, pilih scope All Companies — "
                    "jangan mendaftarkan semuanya satu per satu."
                ),
                "order": 15,
            },
            # Bacaan balik dari daftar di atas; tidak ada yang
            # menyuntingnya lewat kolom ini.
            "selected_companies": {
                "form": False,
                "table": False,
                "filter": False,
                "export": False,
            },
        },
        "import": HOLIDAY_IMPORT_SCHEMA,
    }
    ordering = ["date"]
    search_fields = ["code", "name"]
    # Sempat menyebut field `calendar` yang tidak ada di model Holiday,
    # sehingga django-filter melempar TypeError dan daftar hari libur
    # selalu membalas 500.
    filterset_fields = [
        "scope",
        "company",
        "location",
        "date",
        "country_code",
        "is_national",
        "is_recurring",
        "is_active",
        "source",
        "sync_status",
    ]

    def filter_queryset(self, queryset):
        # Cakupannya dari `scope_holidays_for_user()`, bukan dari mixin:
        # aturan yang sama dipakai sorotan dashboard HR dan widget
        # Upcoming Holidays, dan menuliskannya tiga kali berarti tiga
        # kesempatan salah satunya ketinggalan.
        from rest_framework.viewsets import ModelViewSet

        from apps.administration.services.calendar_resolver import (
            scope_holidays_for_user,
        )

        queryset = ModelViewSet.filter_queryset(self, queryset)

        return scope_holidays_for_user(
            queryset,
            getattr(getattr(self, "request", None), "user", None),
        )

    # ------------------------------------------------------------------
    # Sinkronisasi sumber luar
    # ------------------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="sync-sources")
    def sync_sources(self, request):
        """
        Penyedia yang benar-benar terpasang.

        Kosong hari ini, dan itu jawaban yang jujur: `HolidaySource`
        menyebut GOOGLE/GOVERNMENT/ICS sebagai **asal-usul** yang bisa
        dicatat, bukan sebagai integrasi yang sudah jalan. Layar yang
        membaca daftar ini menyembunyikan tombolnya alih-alih
        menawarkan sync yang akan gagal.
        """
        return Response({
            "sources": available_sources(),
            "pending_review": HolidaySyncService.pending().count(),
        })

    @action(detail=False, methods=["post"], url_path="sync")
    def sync(self, request):
        """
        POST /sync/  {"source": "...", "year": 2026, "country_code": "ID"}

        Hasilnya mendarat sebagai baris **PENDING** — tersimpan, tapi
        belum dibaca resolver mana pun. Yang membuatnya berlaku adalah
        `confirm/`, dan itu memang harus ditekan orang.
        """
        source = str(request.data.get("source") or "").strip().upper()

        provider = get_provider(source)

        if provider is None:
            return Response(
                {
                    "detail": (
                        f"Provider '{source}' belum terpasang. "
                        f"Yang tersedia: "
                        f"{', '.join(available_sources()) or '(belum ada)'}."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            year = int(request.data.get("year"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Field 'year' wajib berupa angka tahun."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        country_code = str(
            request.data.get("country_code") or "ID",
        ).strip().upper()

        holidays = provider.fetch(year=year, country_code=country_code)

        result = HolidaySyncService.stage(
            holidays,
            source=source,
            user=request.user,
        )

        return Response(
            {
                "detail": (
                    f"{result['created'] + result['updated']} hari libur "
                    f"menunggu review."
                ),
                **result,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        holiday = self.get_object()

        if holiday.sync_status != HolidaySyncStatus.PENDING:
            return Response(
                {
                    "detail": (
                        f"Hari libur ini berstatus "
                        f"{holiday.get_sync_status_display()}, bukan "
                        f"Pending Review."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        HolidaySyncService.confirm(holiday, user=request.user)

        return Response(self.get_serializer(holiday).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        holiday = self.get_object()

        HolidaySyncService.reject(holiday, user=request.user)

        return Response(self.get_serializer(holiday).data)


class WorkCalendarViewSet(CalendarScopedViewSetMixin, BaseMasterViewSet):
    serializer_class = WorkCalendarSerializer
    service_class = WorkCalendarService
    framework_module = "administration/calendar/work-calendar"
    schema_type = "crud"
    schema = {
        "title": "Work Calendar",
        "description": (
            "Manage working-day patterns. A GLOBAL calendar is "
            "stored once and applies to every company; company or "
            "location calendars override it."
        ),
        # Tanpa `endpoint` eksplisit, generator frontend menebaknya
        # dari slug module dan menghasilkan bentuk tunggal —
        # `/work-calendar/` — yang tidak terdaftar di router.
        "endpoint": "/api/administration/calendar/work-calendars/",
        "ui": {
            "import": True,
            "export": True,
            "bulk_delete": True,
        },
        "fields": {
            **ORGANIZATION_FILTER_FIELDS,
            **APPLIES_TO_FIELD,
            "working_days": {
                "type": "text",
                "widget": "text",
                "label": "Working Days",
                "table": True,
                "form": False,
                "filter": False,
                "sortable": False,
                "export": True,
                "read_only": True,
                "order": 7,
                "column_after": "name",
            },
            # Tujuh hari sebagai filter itu bising dan tidak menjawab
            # pertanyaan siapa pun — nyaris tidak ada yang mencari
            # "kalender yang Seninnya hari kerja".
            #
            # Sebagai **kolom** pun tidak lagi: `working_days` sudah
            # menjawabnya dalam satu sel (`Mon-Fri`), dan tujuh kolom
            # centang membuat satu baris tidak muat di layar. Tetap ada
            # di form — di sanalah polanya memang disunting.
            **{
                day: {"filter": False, "table": False}
                for day in (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )
            },
        },
        "import": WORK_CALENDAR_IMPORT_SCHEMA,
    }
    # GLOBAL lebih dulu, lalu COMPANY, lalu LOCATION — urutan yang sama
    # dengan presedennya, jadi baris yang berlaku paling luas duduk di
    # atas dan yang menimpanya tepat di bawahnya.
    ordering = ["scope", "company__name", "name"]
    search_fields = ["code", "name", "company__name", "location__name"]
    filterset_fields = [
        "scope",
        "company",
        "location",
        "is_default",
        "is_active",
    ]

class RosterCrewViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = RosterCrewSerializer
    service_class = RosterCrewService

    framework_module = "administration/calendar/roster-crew"
    schema = ROSTER_CREW_SCHEMA

    ordering = ["company__name", "code"]
    search_fields = ["code", "name", "description", "work_schedule__name"]
    filterset_fields = [
        "company",
        "location",
        "work_schedule",
        "cycle_start_date",
        "is_active",
    ]
