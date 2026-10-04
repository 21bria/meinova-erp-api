from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.setting import BaseSettingAPIView

from apps.administration.api.notification.serializers.notification import (
    NotificationSerializer,
    NotificationSettingSerializer,
)
from apps.administration.api.notification.services.notification_service import (
    NotificationService,
    NotificationSettingService,
)


class NotificationViewSet(BaseMasterViewSet):
    """
    Isi bel di header.

    Bukan CRUD walau mewarisi base CRUD: notifikasi ditulis sistem, dan
    yang bisa dilakukan pemiliknya cuma membacanya lalu menandainya
    terbaca atau membuangnya. Metode tulisnya karena itu dimatikan lewat
    `http_method_names` — basenya tetap `BaseMasterViewSet` supaya
    `framework_schema_view` masih menemukannya, pola yang sama dengan
    `WorkflowInstanceViewSet`.
    """

    http_method_names = ["get", "post", "delete", "head", "options"]

    search_fields = [
        "title",
        "message",
        "type",
        "module",
    ]

    # Base memakai `["name"]`, dan Notification tidak punya kolom itu —
    # setiap permintaan daftar akan melempar FieldError.
    ordering = ["-created_at"]

    permission_classes = [IsAuthenticated]

    # Notifikasi milik pribadi. Tidak ada izin model yang masuk akal di
    # sini: orang berhak membaca notifikasinya sendiri tanpa dicentangkan
    # apa pun di layar Roles.
    enforce_model_permissions = False

    serializer_class = NotificationSerializer
    service_class = NotificationService

    framework_module = "administration/notification/notification"
    schema_type = "crud"

    schema = {
        "title": "Notification",
        "description": "Manage user notifications.",
        "endpoint": "/api/administration/notifications/notifications/",
    }

    def create(self, request, *args, **kwargs):
        """
        Notifikasi ditulis sistem, tidak pernah diketik orang.

        `http_method_names` harus tetap memuat `post` karena action
        `read/` dan `mark-all-read/` memakainya — dan itu ikut membuka
        `create` bawaan router. Dibiarkan terbuka, POST kosong menembus
        serializer yang seluruh isinya read-only lalu jatuh 500 di
        tingkat basis data, bukan ditolak dengan pesan.
        """
        raise MethodNotAllowed(request.method)

    def get_queryset(self):
        """
        Selalu milik sendiri.

        Base memanggil `service_class.list()` tanpa argumen sementara
        `NotificationService.list` menuntut `user` — jadi jalur bawaannya
        melempar TypeError, dan endpoint ini tidak pernah bisa dipakai.
        """
        return NotificationService.list(self.request.user)

    @action(detail=False, methods=["get"])
    def bell(self, request):
        """
        Satu permintaan untuk seluruh isi bel.

        Termasuk `waiting_for_me` dari engine approval, walau angkanya
        milik modul lain: belnya tampil di **setiap** halaman, jadi
        memisahnya jadi dua permintaan berarti dua kali tembakan tiap
        kali orang berpindah layar. Alasan yang sama dengan
        `dashboard/summary/`.
        """
        from apps.workflow.services import WorkflowApprovalService

        data = NotificationService.bell(request.user)

        return success_response(
            data={
                "unread_count": data["unread_count"],
                "waiting_for_me": (
                    WorkflowApprovalService
                    .pending_for(request.user)
                    .count()
                ),
                "items": self.get_serializer(
                    data["items"],
                    many=True,
                ).data,
            },
            message="Isi notifikasi.",
        )

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        count = NotificationService.mark_read(request.user, [pk])

        return success_response(
            data={"updated": count},
            message="Notifikasi ditandai terbaca.",
        )

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        count = NotificationService.mark_read(request.user)

        return success_response(
            data={"updated": count},
            message="Semua notifikasi ditandai terbaca.",
        )


class NotificationSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSettingSerializer
    service_class = NotificationSettingService
    framework_module = "administration/notification/notification-setting"
    schema_type = "setting"

    schema = {
        "title": "Notification Settings",
        "description": "Configure notification preferences.",
        "endpoint": "/api/administration/notifications/settings/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
        "sections": [
            {
                "title": "Channels",
                "fields": [
                    "in_app_enabled",
                    "email_enabled",
                    "push_enabled",
                    "sms_enabled",
                ],
            },
        ],
    }

    def get_object(self):
        return self.service_class.get_settings(self.request.user)
