from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    DocumentSeries,
    NumberingSequence,
)


@register_lookup
class NumberingSequenceLookup(BaseLookup):
    name = "numbering-sequences"

    model = NumberingSequence

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]


@register_lookup
class DocumentSeriesLookup(BaseLookup):
    name = "document-series"

    model = DocumentSeries

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]