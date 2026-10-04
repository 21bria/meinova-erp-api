"""
Metadata UI framework tidak boleh menimpa `View.schema` milik DRF.

`drf_spectacular.E001` ("Incompatible AutoSchema used on View") membuat
`check --deploy` gagal di produksi: seluruh viewset framework menulis
dict `schema`, dan nama itu descriptor DRF. `UISchemaMixin` memindahkan
dict itu ke `ui_schema`; test di sini menjaga keduanya — OpenAPI bisa
dibangkitkan, dan metadata UI tetap sampai ke pembangun schema frontend.

`SimpleTestCase`: tidak ada yang menyentuh database.
"""

from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import get_resolver
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.openapi import AutoSchema
from rest_framework.views import APIView

from apps.accounts.api.api_keys.views import APIKeyViewSet
from apps.framework.introspection.schema import get_schema_override
from apps.framework.views.dashboard import BaseDashboardAPIView
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.setting import BaseSettingAPIView
from apps.framework.views.tree import BaseTreeAPIView
from apps.framework.views.ui_schema import UISchemaMixin


FRAMEWORK_BASES = (
    BaseMasterViewSet,
    BaseDashboardAPIView,
    BaseSettingAPIView,
    BaseTreeAPIView,
)


def _framework_view_classes() -> set[type]:
    # Memuat seluruh URLconf supaya setiap modul view ikut terimpor.
    get_resolver().url_patterns

    found: set[type] = set()
    pending = list(FRAMEWORK_BASES)

    while pending:
        cls = pending.pop()
        found.add(cls)
        pending.extend(cls.__subclasses__())

    return found


class UISchemaSeparationTests(SimpleTestCase):
    def test_every_framework_view_keeps_drf_autoschema(self):
        classes = _framework_view_classes()

        # Sanity: yang diperiksa memang ratusan viewset, bukan daftar kosong.
        self.assertGreater(len(classes), 100)

        offenders = sorted(
            f"{cls.__module__}.{cls.__qualname__}"
            for cls in classes
            if not isinstance(cls().schema, AutoSchema)
        )

        self.assertEqual(offenders, [])

    def test_declared_metadata_moves_to_ui_schema(self):
        self.assertIsInstance(APIKeyViewSet().schema, AutoSchema)
        self.assertEqual(APIKeyViewSet.ui_schema["title"], "API Keys")
        self.assertEqual(
            get_schema_override(APIKeyViewSet)["title"],
            "API Keys",
        )

    def test_subclass_declaration_is_moved_and_parent_untouched(self):
        class Parent(UISchemaMixin, APIView):
            schema = {"title": "Parent"}

        class Child(Parent):
            schema = {"title": "Child"}

        class Inheriting(Parent):
            pass

        self.assertEqual(Parent.ui_schema, {"title": "Parent"})
        self.assertEqual(Child.ui_schema, {"title": "Child"})
        self.assertEqual(Inheriting.ui_schema, {"title": "Parent"})

        for cls in (Parent, Child, Inheriting):
            self.assertNotIn("schema", cls.__dict__)
            self.assertIsInstance(cls().schema, AutoSchema)

    def test_drf_schema_values_are_left_alone(self):
        class Excluded(UISchemaMixin, APIView):
            schema = None

        class Custom(UISchemaMixin, APIView):
            schema = AutoSchema()

        self.assertIsNone(Excluded().schema)
        self.assertEqual(Excluded.ui_schema, {})
        self.assertIsInstance(Custom().schema, AutoSchema)
        self.assertEqual(Custom.ui_schema, {})

    def test_openapi_generation_does_not_raise(self):
        # Yang dijalankan `check --deploy` (drf_spectacular.E001).
        document = SchemaGenerator().get_schema(request=None, public=True)

        self.assertTrue(document["paths"])
