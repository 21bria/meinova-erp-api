from rest_framework.permissions import IsAuthenticated
from apps.framework.builders import action
from apps.framework.services.company_copy import CompanyCopyViewSetMixin
from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.numbering.serializers.numbering import (
    NumberingSequenceSerializer,
    DocumentSeriesSerializer,
)
from apps.administration.api.numbering.services.numbering_service import (
    NumberingSequenceService,
    DocumentSeriesService,
)


class NumberingSequenceViewSet(CompanyCopyViewSetMixin, BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NumberingSequenceSerializer
    service_class = NumberingSequenceService
    framework_module = "administration/numbering/numbering-sequence"
    schema_type = "crud"

    schema = {
        "title": "Numbering Sequence",
        "description": "Manage automatic numbering sequences.",
        "endpoint": "/api/administration/numbering/sequences/",
        "actions": [
            action.copy_to_companies(
                endpoint="/api/administration/numbering/sequences/",
                help_text=(
                    "Yang disalin polanya saja — prefix, padding, dan "
                    "aturan resetnya. Penghitungnya selalu mulai dari "
                    "nol di perusahaan tujuan."
                ),
            ),
        ],
    }


class DocumentSeriesViewSet(BaseMasterViewSet):
    search_fields = [
        "sequence__code",
        "sequence__name",
    ]

    permission_classes = [IsAuthenticated]
    serializer_class = DocumentSeriesSerializer
    service_class = DocumentSeriesService
    framework_module = "administration/numbering/document-series"
    schema_type = "crud"

    schema = {
        "title": "Document Series",
        "description": "Manage document series and prefixes.",
    }