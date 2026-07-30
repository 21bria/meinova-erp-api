from apps.administration.models import NumberingSequence, DocumentSeries


class NumberingSequenceService:
    @staticmethod
    def list():
        return NumberingSequence.objects.select_related("company").order_by(
            "module",
            "document_type",
        )


class DocumentSeriesService:
    @staticmethod
    def list():
        return DocumentSeries.objects.select_related("sequence").order_by(
            "-year",
            "-month",
        )