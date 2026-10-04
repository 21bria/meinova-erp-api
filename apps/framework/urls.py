# apps/core/framework/urls.py
from django.urls import path
from apps.framework.views.framework import framework_schema_view
from apps.framework.views.permissions import framework_permissions_view

urlpatterns = [
    # Rute `permissions/` harus **di atas** `schema/<path:module>/`?
    # Tidak — keduanya berbeda awalan, jadi tidak saling menelan. Yang
    # perlu diingat: `<path:module>` memang serakah, jadi rute baru yang
    # berawalan `schema/` wajib didaftarkan sebelum baris itu.
    path("permissions/", framework_permissions_view, name="framework-permissions"),
    path("schema/<path:module>/", framework_schema_view, name="framework-schema"),
]
