from rest_framework import serializers

from apps.administration.models import FavoriteMenu


class FavoriteMenuSerializer(serializers.ModelSerializer):
    class Meta:
        model = FavoriteMenu
        fields = [
            "id",
            "menu_code",
            "title",
            "description",
            "link",
            "icon",
            "color",
            "badge",
            "position",
            "is_visible",
        ]