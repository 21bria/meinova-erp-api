from __future__ import annotations

from django.db.models import F
from django.http import FileResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    UnsupportedMediaType,
)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from apps.uploads.api.serializers import (
    MultipleUploadSerializer,
    UploadedFileCreateSerializer,
    UploadedFileReplaceSerializer,
    UploadedFileSerializer,
)
from apps.uploads.models import UploadedFile
from apps.uploads.services.access_service import FileAccessService
from apps.uploads.services import (
    ReplaceService,
    UploadDeleteService,
    UploadService,
)


class UploadedFileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_fields = [
        "file_type",
        "category",
        "extension",
        "mime_type",
        "status",
        "is_public",
        "uploaded_by",
    ]

    search_fields = [
        "original_name",
        "stored_name",
        "description",
        "checksum_sha256",
    ]

    ordering_fields = [
        "original_name",
        "size",
        "file_type",
        "category",
        "download_count",
        "created_at",
        "updated_at",
    ]

    ordering = ["-created_at"]

    http_method_names = [
        "get",
        "post",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        """
        Berkas yang boleh **ditemukan** akun ini.

        Penyaringannya di `get_queryset()`, bukan `filter_queryset()`,
        dan itu disengaja: `get_object()` DRF memanggil
        `filter_queryset(get_queryset())`, jadi keduanya sama-sama
        menutup daftar **dan** akses lewat id — tapi menaruhnya di
        `get_queryset()` membuat action yang merakit querysetnya
        sendiri ikut terjaga tanpa harus ingat memanggil apa pun.

        Sebelum ini fungsi ini memulangkan `UploadedFile.objects
        .active()` apa adanya: **seluruh berkas tenant, untuk setiap
        akun yang login**, lengkap dengan `public_id`-nya. Penemuan
        itu sendiri sudah kebocoran — endpoint unduh tinggal
        menyusul.
        """
        queryset = (
            UploadedFile.objects.active()
            .select_related(
                "uploaded_by",
                "updated_by",
                "deleted_by",
            )
        )

        return FileAccessService.readable(
            queryset,
            getattr(self.request, "user", None),
        )

    def get_serializer_class(self):
        if self.action == "create":
            return UploadedFileCreateSerializer

        if self.action == "multiple":
            return MultipleUploadSerializer

        if self.action == "replace":
            return UploadedFileReplaceSerializer

        return UploadedFileSerializer

    def assert_may_write(self, request, instance) -> None:
        """
        Mengganti dan menghapus berkas **bukan** hak yang datang
        bersama hak membacanya.

        `uploaded_file` adalah `OneToOneField` ber-`on_delete=PROTECT`
        di tujuh model, jadi mengganti isinya berarti mengubah isi
        dokumen orang lain tanpa pernah menyentuh dokumennya. Yang
        boleh dilakukan lewat endpoint ini karena itu dibatasi pada
        berkas yang **belum** menempel ke record bisnis mana pun.
        """
        if FileAccessService.can_write(request.user, instance):
            return

        raise PermissionDenied(
            "Berkas ini sudah menjadi bagian dari sebuah dokumen. "
            "Ganti atau hapus dari layar dokumennya, bukan dari sini."
        )

    def serialize_output(
        self,
        instance,
        *,
        many: bool = False,
    ):
        return UploadedFileSerializer(
            instance,
            many=many,
            context=self.get_serializer_context(),
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        instance = UploadService.create(
            uploaded_file=serializer.validated_data["file"],
            metadata=serializer.validated_data.get(
                "metadata",
                {},
            ),
            user=request.user,
        )

        output_serializer = self.serialize_output(instance)

        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        self.assert_may_write(request, instance)

        UploadDeleteService.soft_delete(
            instance=instance,
            user=request.user,
        )

        return Response(
            {
                "detail": "File berhasil dihapus.",
                "public_id": str(instance.public_id),
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="multiple",
    )
    def multiple(self, request):
        serializer = self.get_serializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        instances = UploadService.create_multiple(
            files=serializer.validated_data["files"],
            metadata=serializer.validated_data.get(
                "metadata",
                {},
            ),
            user=request.user,
        )

        output_serializer = self.serialize_output(
            instances,
            many=True,
        )

        return Response(
            {
                "count": len(instances),
                "results": output_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="replace",
    )
    def replace(self, request, public_id=None):
        instance = self.get_object()

        self.assert_may_write(request, instance)

        serializer = self.get_serializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        instance = ReplaceService.replace(
            instance=instance,
            uploaded_file=serializer.validated_data["file"],
            user=request.user,
        )

        output_serializer = self.serialize_output(instance)

        return Response(
            output_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="download",
    )
    def download(self, request, public_id=None):
        instance = self.get_object()

        if not instance.file:
            raise NotFound("File tidak ditemukan.")

        storage = instance.file.storage
        file_name = instance.file.name

        if not storage.exists(file_name):
            raise NotFound(
                "File fisik tidak ditemukan pada storage."
            )

        UploadedFile.all_objects.filter(
            pk=instance.pk,
        ).update(
            download_count=F("download_count") + 1,
            last_download_at=timezone.now(),
        )

        response = FileResponse(
            storage.open(file_name, "rb"),
            as_attachment=True,
            filename=instance.original_name,
            content_type=(
                instance.mime_type
                or "application/octet-stream"
            ),
        )

        if instance.size:
            response["Content-Length"] = str(instance.size)

        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"

        return response

    @action(
        detail=True,
        methods=["get"],
        url_path="preview",
    )
    def preview(self, request, public_id=None):
        instance = self.get_object()

        if not instance.can_preview:
            raise UnsupportedMediaType(
                instance.mime_type,
                detail="Tipe file ini tidak mendukung preview.",
            )

        if not instance.file:
            raise NotFound("File tidak ditemukan.")

        storage = instance.file.storage
        file_name = instance.file.name

        if not storage.exists(file_name):
            raise NotFound(
                "File fisik tidak ditemukan pada storage."
            )

        response = FileResponse(
            storage.open(file_name, "rb"),
            as_attachment=False,
            filename=instance.original_name,
            content_type=(
                instance.mime_type
                or "application/octet-stream"
            ),
        )

        if instance.size:
            response["Content-Length"] = str(instance.size)

        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"

        return response

    @action(
        detail=False,
        methods=["get"],
        url_path="deleted",
        permission_classes=[IsAdminUser],
    )
    def deleted(self, request):
        queryset = (
            UploadedFile.objects.deleted()
            .select_related(
                "uploaded_by",
                "updated_by",
                "deleted_by",
            )
            .order_by("-deleted_at")
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.serialize_output(
                page,
                many=True,
            )

            return self.get_paginated_response(
                serializer.data
            )

        serializer = self.serialize_output(
            queryset,
            many=True,
        )

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="restore",
        permission_classes=[IsAdminUser],
    )
    def restore(self, request, public_id=None):
        try:
            instance = (
                UploadedFile.objects.deleted()
                .select_related(
                    "uploaded_by",
                    "updated_by",
                    "deleted_by",
                )
                .get(public_id=public_id)
            )
        except UploadedFile.DoesNotExist as exc:
            raise NotFound(
                "File yang sudah dihapus tidak ditemukan."
            ) from exc

        UploadDeleteService.restore(
            instance=instance,
            user=request.user,
        )

        serializer = self.serialize_output(instance)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path="purge",
        permission_classes=[IsAdminUser],
    )
    def purge(self, request, public_id=None):
        try:
            instance = UploadedFile.all_objects.get(
                public_id=public_id,
            )
        except UploadedFile.DoesNotExist as exc:
            raise NotFound(
                "File tidak ditemukan."
            ) from exc

        UploadDeleteService.purge(
            instance=instance,
        )

        return Response(
            {
                "detail": (
                    "Data dan file fisik berhasil "
                    "dihapus permanen."
                )
            },
            status=status.HTTP_200_OK,
        )