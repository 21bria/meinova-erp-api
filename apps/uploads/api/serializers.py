from __future__ import annotations

from rest_framework import serializers
from rest_framework.reverse import reverse

from apps.uploads.models import UploadedFile
from apps.uploads.validators import (
    get_max_multiple_files,
    validate_uploaded_file,
)


class UploadedFileSerializer(serializers.ModelSerializer):
    size_display = serializers.ReadOnlyField()
    is_image = serializers.ReadOnlyField()
    is_pdf = serializers.ReadOnlyField()
    can_preview = serializers.ReadOnlyField()

    file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = UploadedFile

        fields = [
            "id",
            "public_id",
            "original_name",
            "stored_name",
            "extension",
            "mime_type",
            "file_type",
            "category",
            "size",
            "size_display",
            "checksum_sha256",
            "width",
            "height",
            "page_count",
            "is_public",
            "description",
            "metadata",
            "download_count",
            "last_download_at",
            "status",
            "version",
            "expires_at",
            "file_url",
            "thumbnail_url",
            "download_url",
            "preview_url",
            "is_image",
            "is_pdf",
            "can_preview",
            "uploaded_by",
            "updated_by",
            "deleted_by",
            "replaced_at",
            "created_at",
            "updated_at",
            "deleted_at",
            "is_deleted",
        ]

        read_only_fields = tuple(fields)

    def _absolute(self, url):
        if not url:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(url)

        return url

    def get_file_url(self, obj):
        if not obj.file:
            return None

        try:
            return self._absolute(obj.file.url)
        except Exception:
            return None

    def get_thumbnail_url(self, obj):
        if not obj.thumbnail:
            return None

        try:
            return self._absolute(obj.thumbnail.url)
        except Exception:
            return None

    def get_download_url(self, obj):
        request = self.context.get("request")

        return reverse(
            "uploads:uploaded-file-download",
            kwargs={
                "public_id": obj.public_id,
            },
            request=request,
        )

    def get_preview_url(self, obj):
        if not obj.can_preview:
            return None

        request = self.context.get("request")

        return reverse(
            "uploads:uploaded-file-preview",
            kwargs={
                "public_id": obj.public_id,
            },
            request=request,
        )


class UploadedFileReferenceSerializer(UploadedFileSerializer):
    """
    Berkas yang ditunjuk sebuah record, tanpa jalur penyimpanannya.

    Untuk `<field>_detail` yang ikut terkirim di payload **daftar**
    sebuah resource (mis. foto pegawai). Isinya cukup untuk widget
    unggah: identitas, nama, ukuran, dan dua alamat berautentikasi
    (`preview/`, `download/`) — alamat yang otoritasnya diturunkan dari
    record induknya lewat `FileAccessService`.

    `file_url` dan `thumbnail_url` **sengaja tidak ikut**: keduanya
    jalur `MEDIA_URL` statis yang dilayani tanpa pemeriksaan. Menyebarnya
    di setiap baris daftar berarti membagikan alamat yang bisa dibuka
    tanpa login untuk seluruh foto yang terlihat di halaman itu.
    """

    class Meta(UploadedFileSerializer.Meta):
        fields = [
            "id",
            "public_id",
            "original_name",
            "extension",
            "mime_type",
            "file_type",
            "category",
            "size",
            "size_display",
            "width",
            "height",
            "is_image",
            "can_preview",
            "preview_url",
            "download_url",
            "updated_at",
        ]

        read_only_fields = tuple(fields)


class UploadedFileCreateSerializer(serializers.Serializer):
    file = serializers.FileField(
        required=True,
        allow_empty_file=False,
        validators=[
            validate_uploaded_file,
        ],
    )

    metadata = serializers.JSONField(
        required=False,
        default=dict,
    )


class UploadedFileReplaceSerializer(serializers.Serializer):
    file = serializers.FileField(
        required=True,
        allow_empty_file=False,
        validators=[
            validate_uploaded_file,
        ],
    )


class MultipleUploadSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(
            allow_empty_file=False,
            validators=[
                validate_uploaded_file,
            ],
        ),
        required=True,
        allow_empty=False,
    )

    metadata = serializers.JSONField(
        required=False,
        default=dict,
    )

    def validate_files(self, files):
        maximum = get_max_multiple_files()

        if len(files) > maximum:
            raise serializers.ValidationError(
                f"Maksimal {maximum} file."
            )

        return files