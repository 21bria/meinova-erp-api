from rest_framework import serializers


class FavoriteMenuSerializer(serializers.Serializer):
    """
    Pintasan di halaman depan.

    Sengaja `Serializer` biasa, bukan `ModelSerializer`: sumbernya bisa
    baris `FavoriteMenu` milik pengguna **atau** susunan bawaan dari
    katalog yang memang belum punya baris di database. Alasan yang sama
    dengan `FavoriteAppSerializer`.
    """

    menu_code = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True, required=False)
    link = serializers.CharField()
    icon = serializers.CharField(allow_blank=True, required=False)
    color = serializers.CharField(allow_blank=True, required=False)
    badge = serializers.CharField(allow_blank=True, required=False)
    module = serializers.CharField(allow_blank=True, required=False)
    position = serializers.IntegerField(required=False)
    is_visible = serializers.BooleanField(required=False)


class MenuCatalogEntrySerializer(FavoriteMenuSerializer):
    is_favorite = serializers.BooleanField()


class FavoriteMenuSelectionSerializer(serializers.Serializer):
    codes = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )
