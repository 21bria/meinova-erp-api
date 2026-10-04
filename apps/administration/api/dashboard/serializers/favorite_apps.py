from rest_framework import serializers


class FavoriteAppSerializer(serializers.Serializer):
    """
    Kartu aplikasi di halaman depan.

    Sengaja `Serializer` biasa, bukan `ModelSerializer`: sumbernya bisa
    baris `FavoriteApp` milik pengguna **atau** susunan bawaan dari
    katalog yang memang belum punya baris di database.
    """

    app_code = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True, required=False)
    link = serializers.CharField()
    icon = serializers.CharField(allow_blank=True, required=False)
    color = serializers.CharField(allow_blank=True, required=False)
    badge = serializers.CharField(allow_blank=True, required=False)
    status = serializers.CharField(required=False)
    position = serializers.IntegerField(required=False)


class AppCatalogEntrySerializer(FavoriteAppSerializer):
    is_favorite = serializers.BooleanField()

    # Dua keadaan yang berbeda sebabnya, jadi dikirim terpisah:
    # `is_accessible` soal hak akses pengguna, `is_available` soal modul
    # yang memang belum jalan untuk siapa pun. Keduanya penanda
    # tampilan; penegakan aksesnya tetap di menu permission, DataScope,
    # dan permission tiap endpoint.
    is_accessible = serializers.BooleanField(required=False, default=True)
    is_available = serializers.BooleanField(required=False, default=True)


class FavoriteAppSelectionSerializer(serializers.Serializer):
    codes = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )
