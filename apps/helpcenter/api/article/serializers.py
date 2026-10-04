from rest_framework import serializers

from apps.helpcenter.models import HelpArticle
from apps.helpcenter.sanitize import absolutize_media


class HelpArticleSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
        default=None,
    )

    role_name = serializers.CharField(
        source="role.name",
        read_only=True,
        default=None,
    )

    # Kolom Status tanpa ini menampilkan `published` mentah. Versi
    # siap-tampilnya harus ada di payload dan dirujuk `display_key` —
    # keduanya, kalau tidak kolomnya tetap membaca kunci yang salah.
    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = HelpArticle
        fields = "__all__"

        read_only_fields = [
            "category_name",
            "role_name",
            "status_label",
            "view_count",
            "helpful_count",
            "not_helpful_count",
            "published_at",
        ]

        extra_kwargs = {
            # Diturunkan `HelpArticleService` dari judul kalau
            # dikosongkan. Dibiarkan `required` bawaan model, jalur
            # pengisian otomatisnya tidak pernah kepakai — DRF menolak
            # requestnya lebih dulu. Jebakan yang sama dengan
            # `location` di Roster Setup.
            "slug": {"required": False, "allow_blank": True},
            "code": {"required": False, "allow_blank": True},
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Gambar tersimpan sebagai jalur relatif, dan editor artikel
        # berjalan di origin frontend — tanpa ini penulisnya membuka
        # artikelnya sendiri dan melihat seluruh gambar sebagai ikon
        # pecah, lalu menyangka unggahannya gagal.
        #
        # Bentuk absolut ini ikut terkirim balik saat disimpan;
        # `normalize_image_src` yang mengembalikannya jadi relatif.
        # Kalau salah satu dari dua sisi itu dilepas, gambarnya hilang
        # diam-diam pada penyimpanan berikutnya.
        request = self.context.get("request")

        if request is not None and data.get("content"):
            data["content"] = absolutize_media(
                data["content"],
                request.build_absolute_uri("/").rstrip("/"),
            )

        return data
