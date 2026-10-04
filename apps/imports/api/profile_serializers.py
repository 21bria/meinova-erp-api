from __future__ import annotations

from rest_framework import serializers

from apps.framework.imports import get_importer
from apps.imports.models import ImportProfile


class ImportProfileLookupSerializer(
    serializers.ModelSerializer,
):
    value = serializers.IntegerField(
        source="id",
        read_only=True,
    )

    label = serializers.CharField(
        source="name",
        read_only=True,
    )

    company_label = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_label = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_label = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    # Bentuk file yang **diharapkan** profile ini, dijelaskan oleh
    # importer-nya sendiri.
    #
    # Ada di sini, bukan sebagai teks bantuan di frontend: yang tahu
    # apa arti `delimiter="\t"` plus `mapping` plus `options` adalah
    # importer, dan teks bantuan yang ditulis ulang di layar akan basi
    # pada perubahan profile pertama tanpa ada yang menyadarinya.
    format = serializers.SerializerMethodField()

    def get_format(self, profile: ImportProfile) -> dict:
        importer = get_importer(profile.module)

        if importer is None:
            return {}

        try:
            return importer.describe_profile(profile)
        except Exception:  # pragma: no cover - penjelasan bukan gerbang
            # Penjelasan format tidak boleh menjatuhkan dropdown
            # profile. Layar tanpa penjelasan masih bisa dipakai; layar
            # yang 500 tidak.
            return {}

    class Meta:
        model = ImportProfile
        fields = [
            "id",
            "value",
            "name",
            "label",
            "code",
            "module",
            "description",
            "source_type",
            "company",
            "company_label",
            "branch",
            "branch_label",
            "location",
            "location_label",
            "delimiter",
            "encoding",
            "datetime_formats",
            "options",
            "is_default",
            "format",
        ]
