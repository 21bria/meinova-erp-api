"""
Layar setelan notifikasi tenant + katalog event.

Setelan memakai `schema_type="setting"` — satu baris per tenant, jadi
satu form, bukan tabel. Bandingkan dengan Tenant Setting dan Print
Setting yang justru `OneToOne(company)` dan karena itu **harus** jadi
CRUD: yang di sini memang cuma satu.
"""

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses.api import success_response
from apps.framework.builders import field, tabs, ui
from apps.framework.views.setting import BaseSettingAPIView

from ...models import NotificationConfig
from ...registry import all_events


class NotificationConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationConfig
        fields = [
            "id",
            "name",
            "email_enabled",
            "in_app_enabled",
            "sender_name",
            "reply_to",
            "app_name",
            "logo_url",
            "base_url",
            "footer_text",
        ]


NOTIFICATION_SETTING_SCHEMA = {
    "module": "administration/notification-settings",
    "name": "NotificationConfig",
    "label": "Notification Setting",
    "endpoint": "/api/notifications/settings/",
    "schema_type": "setting",

    "ui": {
        **ui.page(
            title="Notification Setting",
            description=(
                "Identitas pengirim dan saklar induk. Alamat pengirim "
                "sendiri ditentukan setelan server, bukan di sini — "
                "mengarang alamat per tenant membuat emailnya ditolak "
                "di sisi penerima."
            ),
            columns=2,
        ),
        "tabs": ["switch", "sender", "appearance"],
    },

    "tabs": [
        tabs.form(key="switch", label="Switch", fields=[
            "email_enabled", "in_app_enabled",
        ], order=10),
        tabs.form(key="sender", label="Sender", fields=[
            "sender_name", "reply_to", "base_url",
        ], order=20),
        tabs.form(key="appearance", label="Appearance", fields=[
            "app_name", "logo_url", "footer_text",
        ], order=30),
    ],

    "fields": {
        "email_enabled": field.switch(
            tab="switch", label="Email Enabled", order=10,
            help_text=(
                "Dimatikan = seluruh email dilewati dan dicatat di log "
                "sebagai dilewati, bukan hilang tanpa jejak."
            ),
        ),
        "in_app_enabled": field.switch(
            tab="switch", label="Bell Enabled", order=20,
        ),
        "sender_name": field.text(
            tab="sender", label="Sender Name", order=110,
        ),
        "reply_to": field.email(
            tab="sender", label="Reply-To", order=120,
            help_text=(
                "Alamat balasan, mis. hrd@perusahaan.co.id. Tanpa ini "
                "balasan mendarat di kotak no-reply yang tidak dibuka "
                "siapa pun."
            ),
        ),
        "base_url": field.url(
            tab="sender", label="App URL", order=130, layout="full",
            help_text=(
                "Alamat frontend tenant ini. Dipakai membangun tautan "
                "di dalam email — kalau salah, tautannya mendarat di "
                "tenant lain dan penerimanya menyangka haknya dicabut."
            ),
        ),
        "app_name": field.text(
            tab="appearance", label="App Name", order=210,
        ),
        "logo_url": field.url(
            tab="appearance", label="Logo URL", order=220,
            help_text=(
                "Wajib absolut dan bisa diakses tanpa login — klien "
                "email tidak membawa sesi penerimanya."
            ),
        ),
        "footer_text": field.textarea(
            tab="appearance", label="Footer", rows=3, order=230,
            layout="full",
        ),
    },
}


class NotificationSettingAPIView(BaseSettingAPIView):
    serializer_class = NotificationConfigSerializer
    framework_module = "administration/notification-settings"
    schema = NOTIFICATION_SETTING_SCHEMA

    def get_object(self):
        return NotificationConfig.resolve()


class NotificationEventCatalogView(APIView):
    """
    Katalog event beserta placeholder-nya.

    Ini yang dibaca panel di sebelah editor template. Tanpa endpoint
    ini, satu-satunya cara mengetahui kunci apa yang tersedia untuk
    sebuah event adalah membaca kode pengirimnya — dan orang yang
    menyunting kalimat surat tidak membuka repo.

    Diturunkan dari registry, **bukan** dari tabel: daftar event
    ditentukan kode yang memicunya, dan baris database tidak bisa
    mengarang pemicu. Alasan yang sama dengan `APP_CATALOG` dan
    `HOME_WIDGETS`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        module = str(request.query_params.get("module") or "").strip().lower()

        events = [
            item.as_dict()
            for item in all_events()
            if not module or item.module.lower() == module
        ]

        return success_response(
            data={"events": events, "count": len(events)},
            message="Katalog event notifikasi.",
        )
