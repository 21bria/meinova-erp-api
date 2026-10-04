from django.conf import settings
from django.conf.urls.static import static

from django.contrib import admin
from django.urls import path,include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/accounts/", include("apps.accounts.api.urls")),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    path("api/framework/", include("apps.framework.urls")),

    # Upload Apps & Imports
    path("api/imports/", include("apps.imports.api.urls")),
    path("api/uploads/",include("apps.uploads.api.urls")),

    # Administration
    path("api/administration/", include("apps.administration.api.urls")),

    # Workflow / approval engine — generik, dipakai lintas modul
    path("api/workflow/", include("apps.workflow.api.urls")),

    # Notifikasi — generik juga: template, aturan penerima, dan log
    # pengiriman untuk seluruh modul
    path("api/notifications/", include("apps.notifications.api.urls")),

    # Self Service — ruang pribadi pegawai yang sedang login.
    #
    # Terdaftar di root, bukan di bawah `api/hr/`: `/me` menyangkut
    # seluruh domain (HR, payroll, workflow), dan menaruhnya di dalam
    # salah satunya akan menyatakan kepemilikan yang justru sedang
    # dilepas.
    path("api/me/", include("apps.self_service.api.urls")),

    # Apps Hr
    path("api/hr/", include("apps.hr.api.urls")),
    # Apps Payroll
    path("api/payroll/", include("apps.payroll.api.urls")),

    # Finance — buku besar, tahun buku, dan lapisan integrasi
    # akuntansi. Tahun buku & periode pindah ke sini dari
    # `api/administration/calendar/` pada 16 Sep 2026.
    path("api/finance/", include("apps.finance.api.urls")),

    # Asset Management — register, custody, dan dokumen pergerakan aset.
    # Kontrak: docs/claude/assets.md
    path("api/assets/", include("apps.assets.api.urls")),

    # Help Center — panduan pemakaian untuk pengguna akhir
    path("api/helpcenter/", include("apps.helpcenter.api.urls")),

    # Reports — laporan manajemen lintas modul, seluruhnya read-only
    path("api/reports/", include("apps.reports.api.urls")),

]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,

    )