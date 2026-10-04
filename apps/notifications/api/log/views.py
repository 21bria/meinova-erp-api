"""
Layar log pengiriman.

Read-only, dan itu disengaja: ini catatan kejadian, bukan master.
Menyuntingnya berarti bukti pengiriman bisa diubah, dan satu-satunya
pertanyaan yang dijawab layar ini ("apa yang benar-benar dikirim ke
siapa") jadi tidak bisa dipercaya lagi.

Yang **bisa** dilakukan dari sini cuma mengirim ulang yang gagal.
"""

from rest_framework import serializers
from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.core.services.base import BaseService
# Di-alias: `action` polos bertabrakan dengan dekorator `@action` milik
# DRF yang diimpor di atas, dan tabrakannya baru muncul saat modulnya
# dimuat — sebagai `TypeError: 'module' object is not callable` yang
# menunjuk baris dekoratornya, jauh dari baris impor yang jadi sebabnya.
from apps.framework.builders import action as action_builder
from apps.framework.builders import field, ui
from apps.framework.views.master import BaseMasterViewSet

from ...constants import Channel, DeliveryStatus
from ...models import NotificationLog
from ...registry import event_choices, find_event


class NotificationLogService(BaseService):
    model = NotificationLog

    # Membaca log tidak menghasilkan baris audit. Kalau ikut dicatat,
    # jejak audit terisi satu baris tiap kali seseorang membuka layar
    # ini — dan perubahan yang benar-benar dilakukan orang tenggelam.
    audit_enabled = False


class NotificationLogSerializer(serializers.ModelSerializer):
    event_label = serializers.SerializerMethodField()
    channel_label = serializers.CharField(
        source="get_channel_display", read_only=True,
    )
    status_label = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    class Meta:
        model = NotificationLog
        fields = "__all__"

    def get_event_label(self, obj) -> str:
        spec = find_event(obj.event)

        return spec.label if spec else obj.event


NOTIFICATION_LOG_SCHEMA = {
    "module": "administration/notification-logs",
    "name": "NotificationLog",
    "label": "Notification Log",
    "endpoint": "/api/notifications/logs/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Notification Log",
            description=(
                "Riwayat pengiriman. Dilewati bukan gagal: yang pertama "
                "keputusan yang benar (penerimanya mematikan email, "
                "alamatnya kosong), yang kedua perlu diperbaiki."
            ),
            size="xl",
            columns=1,
            create=False,
            edit=False,
            delete=False,
            bulk_delete=False,
            export=True,
        ),
    },

    # **Tidak ada tombol Resend per baris, dan itu keputusan sadar.**
    #
    # Layar ini `edit: False` — read-only, karena log adalah catatan
    # kejadian dan barisnya tidak boleh disunting. Konsekuensinya
    # barisnya tidak bisa dibuka sama sekali: generator memasang
    # `onEdit` hanya kalau `ui.edit` menyala, dan record action hanya
    # dirender di dalam dialog/workspace yang terbuka. Jadi tombol
    # Resend yang dideklarasikan di sini akan **ada di schema tapi
    # tidak pernah muncul di layar mana pun** — persis pola "endpoint
    # tanpa tombol" yang berulang kali jadi masalah di codebase ini,
    # cuma terbalik.
    #
    # Endpoint `POST .../logs/<id>/resend/` tetap ada dan tetap dipakai
    # (`retry_failed`, dan pemanggil API langsung). Yang belum ada
    # rumahnya di layar. Menutupnya butuh mode dialog read-only di
    # `framework/` — Save selalu dirender `MFormDialog` hari ini — dan
    # itu perubahan pada komponen bersama yang dipakai seluruh modul.
    #
    # Yang menggantikannya untuk sekarang: kolom `detail` ikut di tabel,
    # jadi **alasan** kegagalan terbaca tanpa membuka apa pun. Itu yang
    # sebenarnya dicari orang saat membuka layar ini; mengirim ulang
    # tanpa tahu sebabnya cuma menghasilkan kegagalan yang sama.
    "actions": [
        action_builder.export(),
    ],

    "fields": {
        "created_at": field.datetime(
            label="Time", table=True, filter=False, sortable=True,
            overview=True, order=10,
        ),
        "event": field.select(
            label="Event",
            options=[
                {"label": label, "value": code}
                for code, label in event_choices()
            ],
            table=True, filter=True, search=True, sortable=True,
            display_key="event_label", overview=True, order=20,
        ),
        "recipient_name": field.text(
            label="Recipient", table=True, search=True, sortable=True,
            overview=True, order=30,
        ),
        "recipient_email": field.text(
            label="Email", table=True, search=True, sortable=False,
            order=40,
        ),
        "channel": field.select(
            label="Channel",
            options=[
                {"label": label, "value": value}
                for value, label in Channel.choices
            ],
            table=True, filter=True, sortable=True,
            display_key="channel_label", order=50,
        ),
        "status": field.select(
            label="Status",
            options=[
                {"label": label, "value": value}
                for value, label in DeliveryStatus.choices
            ],
            table=True, filter=True, sortable=True,
            display_key="status_label", overview=True, order=60,
        ),
        "subject": field.text(
            label="Subject", table=True, search=True, sortable=False,
            order=70,
        ),
        # Di tabel, bukan cuma di dalam record. Ini satu-satunya kolom
        # yang menjawab pertanyaan yang membuat orang membuka layar ini
        # ("kenapa tidak sampai"), dan barisnya tidak bisa dibuka —
        # lihat catatan di "actions" di atas.
        "detail": field.textarea(
            label="Detail", rows=3, table=True, search=True,
            sortable=False, layout="full",
            help_text="Alasan dilewati, atau pesan kegagalannya.",
            order=80,
        ),
        "body": field.textarea(
            label="Body", rows=10, table=False, search=False,
            sortable=False, layout="full",
            help_text="Isi yang benar-benar terkirim ke orang ini.",
            order=90,
        ),
        "attempts": field.integer(
            label="Attempts", table=True, sortable=True, order=100,
        ),

        # Kolom cakupan dokumen: berguna sebagai penyaring, tapi
        # memenuhi tabel kalau ikut ditampilkan.
        **{
            name: {
                "table": False, "filter": False,
                "search": False, "sortable": False,
            }
            for name in (
                "module", "object_type", "object_id", "dedup_key",
                "action_url", "sent_at", "recipient",
                "event_label", "channel_label", "status_label",
            )
        },
    },
}


class NotificationLogViewSet(BaseMasterViewSet):
    serializer_class = NotificationLogSerializer
    service_class = NotificationLogService

    framework_module = "administration/notification-logs"
    schema = NOTIFICATION_LOG_SCHEMA

    # Read-only. Metodenya dimatikan di sini, bukan lewat ReadOnlyModelViewSet:
    # `framework_schema_view` hanya menemukan turunan `BaseMasterViewSet`,
    # dan viewset yang tidak ketemu berarti module-nya 404 di generator FE.
    http_method_names = ["get", "post", "head", "options"]

    search_fields = ["event", "recipient_name", "recipient_email", "subject", "detail"]

    filterset_fields = ["event", "channel", "status", "module", "recipient"]

    ordering_fields = ["created_at", "event", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return NotificationLog.objects.select_related("recipient")

    @action(detail=True, methods=["post"], url_path="resend")
    def resend(self, request, pk=None):
        """
        Kirim ulang satu baris yang gagal.

        Lewat `deliver_email` yang sama dengan worker — kalau jalurnya
        berbeda, yang diuji dari layar ini bukan yang berjalan di
        produksi.
        """
        from ...sender import deliver_email

        log = self.get_object()

        if log.channel != Channel.EMAIL:
            return success_response(
                data={"sent": False},
                message="Hanya baris email yang bisa dikirim ulang.",
            )

        if log.status == DeliveryStatus.SKIPPED:
            return success_response(
                data={"sent": False},
                message=(
                    "Baris ini dilewati, bukan gagal — mengulanginya "
                    "akan menghasilkan hasil yang sama. Yang perlu "
                    f"diperbaiki datanya: {log.detail}"
                ),
            )

        # Dipaksa ulang: `deliver_email` menolak baris yang sudah SENT
        # supaya task Celery yang diantre ulang tidak mengirim dua kali.
        # Tombol ini justru sengaja ditekan orang, jadi statusnya
        # dikembalikan dulu.
        log.status = DeliveryStatus.PENDING
        log.save(update_fields=["status"])

        ok = deliver_email(log.id)

        log.refresh_from_db()

        return success_response(
            data={"sent": ok, "status": log.status, "detail": log.detail},
            message="Terkirim." if ok else f"Masih gagal: {log.detail}",
        )
