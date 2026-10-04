"""
Layar aturan penerima.

Satu baris = satu kelompok penerima. Dua role penerima berarti dua
baris, dan itu justru lebih terbaca daripada satu baris berisi daftar:
masing-masing punya kanalnya sendiri, jadi HR boleh dapat email
sementara atasan langsung cukup notifikasi bel.
"""

from rest_framework import serializers

from apps.core.services.master import BaseMasterService
from apps.framework.builders import field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from ...constants import RecipientType
from ...models import NotificationRule
from ...registry import event_choices, find_event


class NotificationRuleService(BaseMasterService):
    model = NotificationRule


class NotificationRuleSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    role_name = serializers.CharField(
        source="role.name", read_only=True, default=None,
    )
    user_name = serializers.CharField(
        source="user.username", read_only=True, default=None,
    )

    event_label = serializers.SerializerMethodField()
    recipient_type_label = serializers.CharField(
        source="get_recipient_type_display", read_only=True,
    )

    class Meta:
        model = NotificationRule
        fields = "__all__"

        read_only_fields = [
            "company_name",
            "role_name",
            "user_name",
            "event_label",
            "recipient_type_label",
        ]

    def get_event_label(self, obj) -> str:
        spec = find_event(obj.event)

        return spec.label if spec else obj.event

    def validate_event(self, value):
        if find_event(value) is None:
            raise serializers.ValidationError(
                f"Event '{value}' tidak terdaftar di registry notifikasi.",
            )

        return str(value).strip().lower()


NOTIFICATION_RULE_SCHEMA = {
    "module": "administration/notification-rules",
    "name": "NotificationRule",
    "label": "Notification Rule",
    "endpoint": "/api/notifications/rules/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Notification Rule",
            description=(
                "Siapa yang menerima pemberitahuan untuk sebuah event, "
                "dan lewat kanal apa. Event yang belum punya satu baris "
                "pun memakai penerima bawaan sistem."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },

    "tabs": [
        tabs.form(key="general", label="Scope", fields=[
            "event", "company", "is_active", "sort_order",
        ], order=10, show_on_create=True),
        tabs.form(key="recipient", label="Recipient", fields=[
            "recipient_type", "role", "user", "manager_level",
        ], order=20, show_on_create=True),
        tabs.form(key="channel", label="Channel", fields=[
            "send_in_app", "send_email",
        ], order=30, show_on_create=True),
    ],

    "fields": {
        "event": field.select(
            tab="general", label="Event",
            options=[
                {"label": label, "value": code}
                for code, label in event_choices()
            ],
            required=True, table=True, filter=True, search=True,
            sortable=True, overview=True, display_key="event_label",
            order=10,
        ),

        "company": field.lookup(
            tab="general", label="Company",
            lookup_endpoint=(
                "/api/administration/organization/lookup/companies/"
            ),
            display_key="company_name",
            required=False, table=True, filter=True, sortable=True,
            help_text=(
                "Dikosongkan = berlaku untuk semua company. Begitu ada "
                "satu baris bercompany untuk sebuah event, baris global "
                "tidak dipakai lagi untuk company itu."
            ),
            order=20,
        ),

        "is_active": field.switch(
            tab="general", label="Active",
            required=False, table=True, filter=True, sortable=True,
            order=30,
        ),

        "sort_order": field.integer(
            tab="general", label="Order",
            required=False, table=False, sortable=True,
            order=40,
        ),

        "recipient_type": field.select(
            tab="recipient", label="Recipient",
            options=[
                {"label": label, "value": value}
                for value, label in RecipientType.choices
            ],
            required=True, table=True, filter=True, sortable=True,
            overview=True, display_key="recipient_type_label",
            order=110,
        ),

        "role": field.lookup(
            tab="recipient", label="Role",
            lookup_endpoint="/api/accounts/lookup/roles/",
            display_key="role_name",
            required=False, table=True, filter=True, sortable=True,
            visible_when={"field": "recipient_type", "op": "eq", "value": "role"},
            help_text=(
                "Yang diterima tiap pemegang role tetap disaring cakupan "
                "datanya — admin site tidak menerima pemberitahuan "
                "pegawai kantor pusat."
            ),
            order=120,
        ),

        "user": field.lookup(
            tab="recipient", label="User",
            lookup_endpoint="/api/accounts/lookup/users/",
            display_key="user_name",
            required=False, table=True, sortable=True,
            visible_when={"field": "recipient_type", "op": "eq", "value": "user"},
            order=130,
        ),

        "manager_level": field.integer(
            tab="recipient", label="Manager Level",
            required=False, table=False, sortable=False,
            visible_when={"field": "recipient_type", "op": "eq", "value": "manager"},
            help_text="1 = atasan langsung, 2 = atasannya atasan.",
            order=140,
        ),

        "send_in_app": field.switch(
            tab="channel", label="Bell",
            required=False, table=True, filter=True, sortable=True,
            order=210,
        ),

        "send_email": field.switch(
            tab="channel", label="Email",
            required=False, table=True, filter=True, sortable=True,
            order=220,
        ),

        **{
            name: {
                "table": False, "filter": False,
                "search": False, "sortable": False,
            }
            for name in (
                "event_label", "company_name", "role_name",
                "user_name", "recipient_type_label",
            )
        },
    },
}


class NotificationRuleViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = NotificationRuleSerializer
    service_class = NotificationRuleService

    framework_module = "administration/notification-rules"
    schema = NOTIFICATION_RULE_SCHEMA

    # `code`/`name` bawaan base tidak ada di model ini — tanpa menimpanya,
    # setiap ketikan di kotak pencarian membalas 500. Dijaring
    # `SafeSearchFilter`, tapi jaring itu bukan izin untuk membiarkannya.
    search_fields = ["event", "role__code", "role__name", "user__username"]

    filterset_fields = [
        "event", "company", "recipient_type", "role",
        "is_active", "send_in_app", "send_email",
    ]

    ordering_fields = ["event", "sort_order", "created_at"]
    ordering = ["event", "sort_order"]

    def get_queryset(self):
        return (
            NotificationRule.objects
            .select_related("company", "role", "user")
            .filter(is_deleted=False)
        )
