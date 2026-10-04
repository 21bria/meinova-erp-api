from rest_framework import serializers

from apps.helpcenter.models import HelpCategory


class HelpCategorySerializer(serializers.ModelSerializer):
    # Kolom tabel hasil generate mencari `article_count`; tanpa
    # disebut di sini kolomnya tampil "-" di semua baris tanpa error
    # apa pun — pola yang sudah beberapa kali kena di repo ini.
    article_count = serializers.SerializerMethodField()

    class Meta:
        model = HelpCategory
        fields = "__all__"

        read_only_fields = ["article_count"]

    def get_article_count(self, obj) -> int:
        # Dihitung dari `prefetch_related` di viewset, bukan `.count()`
        # per baris — kalau tidak, daftar 20 kategori berarti 20 query
        # tambahan.
        return len(
            [a for a in obj.articles.all() if not a.is_deleted]
        )
