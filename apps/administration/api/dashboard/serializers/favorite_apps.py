from rest_framework import serializers

from apps.administration.models import FavoriteApp


class FavoriteAppSerializer(serializers.ModelSerializer):
    class Meta:
        model = FavoriteApp
        fields = [
            "id",
            "app_code",
            "title",
            "description",
            "link",
            "icon",
            "color",
            "badge",
            "position",
            "is_visible",
        ]