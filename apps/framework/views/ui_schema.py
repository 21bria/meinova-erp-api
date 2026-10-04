"""
Metadata UI framework (`schema = {...}` di viewset) dipisahkan dari
`View.schema` milik DRF.

Seluruh viewset framework menulis metadata form/tabel untuk generator
frontend sebagai atribut kelas `schema`. Nama itu **dipakai DRF**:
`APIView.schema` adalah descriptor `ViewInspector` yang dibaca
drf-spectacular untuk membangkitkan OpenAPI. Dict yang menimpanya membuat
pembangkitan schema berhenti dengan `drf_spectacular.E001` ("Incompatible
AutoSchema used on View") — dan karena `check --deploy` menjalankan
pembangkitan itu, deploy produksi gagal.

Menulis ulang 200-an viewset tidak perlu: saat kelas dibentuk, dict
`schema` yang dideklarasikan dipindah ke `ui_schema`, lalu atribut
`schema` dibuang dari kelas itu sehingga `View.schema` kembali ke
descriptor DRF (`AutoSchema` dari `DEFAULT_SCHEMA_CLASS`). Pembaca
metadata UI framework membaca `ui_schema`, bukan `schema`.

Akibatnya bagi yang membaca: `SomeViewSet.schema` adalah `AutoSchema`,
**bukan** dict UI — pakai `SomeViewSet.ui_schema`.
"""

from rest_framework.schemas.inspectors import ViewInspector


class UISchemaMixin:
    ui_schema: dict = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        declared = cls.__dict__.get("schema")

        # `schema = None` atau sebuah inspector adalah urusan DRF —
        # dibiarkan apa adanya.
        if declared is None or isinstance(declared, ViewInspector):
            return

        cls.ui_schema = declared
        delattr(cls, "schema")
