from rest_framework.permissions import IsAuthenticated
from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.numbering.serializers.numbering import (
    NumberingSequenceSerializer,
    DocumentSeriesSerializer,
)
from apps.administration.api.numbering.services.numbering_service import (
    NumberingSequenceService,
    DocumentSeriesService,
)


class NumberingSequenceViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NumberingSequenceSerializer
    service_class = NumberingSequenceService
    framework_module = "administration/numbering/numbering-sequence"
    schema_type = "crud"

    schema = {
        "title": "Numbering Sequence",
        "description": "Manage automatic numbering sequences.",
    }


class DocumentSeriesViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DocumentSeriesSerializer
    service_class = DocumentSeriesService
    framework_module = "administration/numbering/document-series"
    schema_type = "crud"

    schema = {
        "title": "Document Series",
        "description": "Manage document series and prefixes.",
    }