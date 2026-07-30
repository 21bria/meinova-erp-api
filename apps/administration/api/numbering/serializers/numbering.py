from rest_framework import serializers

from apps.administration.models import NumberingSequence, DocumentSeries


class NumberingSequenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NumberingSequence
        fields = "__all__"


class DocumentSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentSeries
        fields = "__all__"