"""
Layar template email.

Editor workspace, bukan dialog: isi surat ditulis di kotak beberapa
baris, dan dialog yang cukup untuk sebuah policy tidak cukup untuk
mengetik enam paragraf sambil melihat daftar placeholder di sebelahnya.
"""

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.responses.api import success_response
from apps.core.services.master import BaseMasterService
from apps.framework.builders import field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from ...models import EmailTemplate
from ...registry import event_choices, find_event, unknown_placeholders
from ...render import safe_render, variables_used


class EmailTemplateService(BaseMasterService):
    model = EmailTemplate


class EmailTemplateSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    event_label = serializers.SerializerMethodField()

    # Kunci yang dipakai template tapi tidak dikenal event-nya.
    #
    # **Peringatan, bukan penolakan.** Placeholder tak dikenal dirender
    # jadi string kosong; menolak simpan gara-gara satu salah ketik akan
    # membuang seluruh kalimat yang sudah ditulis orang. Ditampilkan di
    # layar supaya salah ketiknya tetap terlihat.
    unknown_placeholders = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = "__all__"

        read_only_fields = [
            "company_name",
            "event_label",
            "unknown_placeholders",
        ]

    def get_event_label(self, obj) -> str:
        spec = find_event(obj.event)

        return spec.label if spec else obj.event

    def get_unknown_placeholders(self, obj) -> list[str]:
        used = variables_used(obj.subject) | variables_used(obj.body)

        return unknown_placeholders(obj.event, used)

    def validate_event(self, value):
        if find_event(value) is None:
            raise serializers.ValidationError(
                f"Event '{value}' tidak terdaftar di registry notifikasi. "
                "Pilih dari daftar yang tersedia.",
            )

        return str(value).strip().lower()


EMAIL_TEMPLATE_SCHEMA = {
    "module": "administration/email-templates",
    "name": "EmailTemplate",
    "label": "Email Template",
    "endpoint": "/api/notifications/templates/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Email Template",
            description=(
                "Judul dan isi surat untuk tiap event. Placeholder "
                "ditulis {{ nama_kunci }} dan daftarnya berbeda per "
                "event."
            ),
            size="full",
            columns=1,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
        "tabs": ["general", "email", "in_app"],
    },

    "tabs": [
        tabs.form(key="general", label="Scope", fields=[
            "event", "company", "name", "is_active",
        ], order=10, show_on_create=True),
        tabs.form(key="email", label="Email", fields=[
            "subject", "body",
        ], order=20, show_on_create=True),
        tabs.form(key="in_app", label="Bel", fields=[
            "in_app_title", "in_app_body",
        ], order=30, show_on_create=True),
    ],

    "fields": {
        "event": field.select(
            tab="general",
            label="Event",
            options=[
                {"label": label, "value": code}
                for code, label in event_choices()
            ],
            required=True,
            table=True,
            filter=True,
            search=True,
            sortable=True,
            overview=True,
            display_key="event_label",
            help_text=(
                "Kejadian yang memicu surat ini. Daftarnya dari registry "
                "notifikasi — event yang tidak ada di sini belum punya "
                "pemicu di sistem."
            ),
            order=10,
        ),

        "company": field.lookup(
            tab="general",
            label="Company",
            lookup_endpoint=(
                "/api/administration/organization/lookup/companies/"
            ),
            display_key="company_name",
            required=False,
            table=True,
            filter=True,
            sortable=True,
            help_text=(
                "Dikosongkan = berlaku untuk semua company. Baris yang "
                "menyebut company mengalahkan yang global."
            ),
            order=20,
        ),

        "name": field.text(
            tab="general",
            label="Note",
            required=False,
            table=True,
            search=True,
            sortable=True,
            help_text="Keterangan untuk pengelola, tidak ikut terkirim.",
            order=30,
        ),

        "is_active": field.switch(
            tab="general",
            label="Active",
            required=False,
            table=True,
            filter=True,
            sortable=True,
            help_text=(
                "Dimatikan = event ini jatuh ke kalimat bawaan sistem, "
                "bukan berhenti terkirim."
            ),
            order=40,
        ),

        "subject": field.text(
            tab="email",
            label="Subject",
            required=True,
            table=True,
            search=True,
            sortable=False,
            layout="full",
            help_text="Judul email. Boleh memuat placeholder.",
            order=110,
        ),

        "body": field.textarea(
            tab="email",
            label="Body",
            rows=14,
            required=True,
            table=False,
            search=True,
            sortable=False,
            layout="full",
            help_text=(
                "Isi surat sebagai teks biasa. Baris kosong jadi "
                "paragraf baru. Kop, tombol, dan kaki surat ditambahkan "
                "sistem — jangan menulis HTML di sini."
            ),
            order=120,
        ),

        "in_app_title": field.text(
            tab="in_app",
            label="Bell Title",
            required=False,
            table=False,
            layout="full",
            help_text=(
                "Dikosongkan = memakai judul email. Diisi kalau judul "
                "emailnya terlalu panjang untuk daftar bel."
            ),
            order=210,
        ),

        "in_app_body": field.text(
            tab="in_app",
            label="Bell Subtitle",
            required=False,
            table=False,
            layout="full",
            help_text="Keterangan satu baris di bawah judul bel.",
            order=220,
        ),

        "event_label": {
            "table": False, "filter": False,
            "search": False, "sortable": False,
        },
        "company_name": {
            "table": False, "filter": False,
            "search": False, "sortable": False,
        },
        "unknown_placeholders": {
            "table": False, "filter": False,
            "search": False, "sortable": False,
        },
    },
}


class EmailTemplateViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = EmailTemplateSerializer
    service_class = EmailTemplateService

    framework_module = "administration/email-templates"
    schema = EMAIL_TEMPLATE_SCHEMA

    search_fields = ["event", "name", "subject", "body"]
    filterset_fields = ["event", "company", "is_active"]
    ordering_fields = ["event", "created_at"]
    ordering = ["event"]

    def get_queryset(self):
        return (
            EmailTemplate.objects
            .select_related("company")
            .filter(is_deleted=False)
        )

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """
        Pratinjau tanpa menyimpan dan tanpa mengirim.

        Memakai contoh nilai dari registry, bukan data sungguhan: yang
        sedang disunting adalah kalimatnya, dan menariknya dari satu
        pegawai nyata membuat pratinjaunya bergantung pada baris mana
        yang kebetulan pertama di tabel.

        Kesalahan render **ditampilkan**, tidak disembunyikan — ini satu-
        satunya layar tempat penulisnya bisa tahu templatenya rusak
        sebelum suratnya terkirim ke orang.
        """
        code = str(request.data.get("event") or "").strip().lower()
        spec = find_event(code)

        if spec is None:
            return success_response(
                data={
                    "error": (
                        f"Event '{code}' tidak terdaftar."
                        if code
                        else "Pilih event-nya dulu."
                    ),
                },
                message="Pratinjau gagal.",
            )

        context = spec.sample_context()
        context.setdefault("recipient_name", "Budi Santoso")
        context.setdefault("recipient_first_name", "Budi")

        subject, subject_error = safe_render(
            request.data.get("subject") or spec.default_subject,
            context,
            label=f"{code}.subject",
        )

        body, body_error = safe_render(
            request.data.get("body") or spec.default_body,
            context,
            label=f"{code}.body",
        )

        used = variables_used(
            f"{request.data.get('subject', '')} {request.data.get('body', '')}"
        )

        return success_response(
            data={
                "subject": subject,
                "body": body,
                "error": subject_error or body_error,
                "unknown_placeholders": unknown_placeholders(code, used),
                "placeholders": [
                    item.as_dict() for item in spec.all_placeholders()
                ],
            },
            message="Pratinjau siap.",
        )
