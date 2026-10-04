"""
Layar setting: siapa yang boleh mengusulkan perubahan kepegawaian.

Bentuknya sama dengan `LeavePolicy` — sasaran (company / location /
employee group) plus aturannya, dan bagian terpenting dari layar ini
justru help text-nya. Mengosongkan Company berarti "berlaku untuk
semua", **bukan** "tidak berlaku"; itu jebakan yang sudah dua kali
muncul di master berjenjang lain di sistem ini.
"""

from rest_framework import serializers

from apps.administration.models import EmployeeActionPolicy
from apps.core.services.master import BaseMasterService
from apps.framework.builders import action, field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.services.company_copy import (
    CompanyCopyMixin,
    CompanyCopyViewSetMixin,
)
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import EmployeeActionType


class EmployeeActionPolicyService(CompanyCopyMixin, BaseMasterService):
    model = EmployeeActionPolicy

    copy_scope_fields = [
        "company",
        "location",
        "employee_group",
        "action_type",
    ]

    copy_rule_fields = [
        "description",
        "initiator_type",
        "initiator_role",
        "allow_on_behalf",
        "on_behalf_role",
        "is_active",
        "sort_order",
    ]



class EmployeeActionPolicySerializer(serializers.ModelSerializer):
    action_type_label = serializers.CharField(
        source="get_action_type_display",
        read_only=True,
        default=None,
    )

    initiator_type_label = serializers.CharField(
        source="get_initiator_type_display",
        read_only=True,
        default=None,
    )

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    employee_group_name = serializers.CharField(
        source="employee_group.name",
        read_only=True,
        default=None,
    )

    initiator_role_name = serializers.CharField(
        source="initiator_role.name",
        read_only=True,
        default=None,
    )

    on_behalf_role_name = serializers.CharField(
        source="on_behalf_role.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeActionPolicy
        fields = "__all__"

        read_only_fields = [
            "action_type_label",
            "initiator_type_label",
            "company_name",
            "location_name",
            "employee_group_name",
            "initiator_role_name",
            "on_behalf_role_name",
        ]


ACTION_TYPE_OPTIONS = [
    {"value": value, "label": label}
    for value, label in EmployeeActionType.choices
]

INITIATOR_OPTIONS = [
    {"value": "any", "label": "Anyone With Permission"},
    {"value": "manager", "label": "Direct Manager"},
    {"value": "department_head", "label": "Department Head"},
    {"value": "role", "label": "Role Holder"},
    {"value": "employee", "label": "The Employee"},
]


SCOPE_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "action_type": field.select(
        tab="general",
        label="Action Type",
        options=ACTION_TYPE_OPTIONS,
        display_key="action_type_label",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Satu baris satu jenis. Kenaikan gaji dan perpanjangan "
            "kontrak memang diusulkan orang yang berbeda."
        ),
        order=30,
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
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua company. Aturan yang "
            "menyebut company mengalahkan yang global."
        ),
        order=40,
    ),

    "location": field.lookup(
        tab="general",
        label="Location",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        display_key="location_name",
        depends_on=["company"],
        lookup_params={"company_id": "$company"},
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua lokasi. Diisi kalau "
            "site tertentu punya jalur usulan sendiri."
        ),
        order=50,
    ),

    "employee_group": field.lookup(
        tab="general",
        label="Employee Group",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/employee-groups/"
        ),
        display_key="employee_group_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        help_text="Dikosongkan = berlaku untuk semua golongan.",
        order=60,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),
}


INITIATOR_FIELDS = {
    "initiator_type": field.select(
        tab="initiator",
        label="Requested By",
        options=INITIATOR_OPTIONS,
        display_key="initiator_type_label",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Dinilai terhadap pegawai yang datanya diubah, bukan "
            "terhadap yang mengetik dokumennya. Kepala Departemen = "
            "pemegang jabatan bertanda Manager di department pegawai "
            "itu."
        ),
        order=110,
    ),

    "initiator_role": field.lookup(
        tab="initiator",
        label="Initiator Role",
        lookup_endpoint="/api/accounts/lookup/roles/",
        display_key="initiator_role_name",
        required=False,
        visible_when={
            "field": "initiator_type",
            "op": "eq",
            "value": "role",
        },
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text="Wajib diisi kalau pengusulnya ditentukan lewat Role.",
        order=120,
    ),

    "allow_on_behalf": field.switch(
        tab="initiator",
        label="Allow On Behalf",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        visible_when={
            "field": "initiator_type",
            "op": "ne",
            "value": "any",
        },
        help_text=(
            "Menyala: HR boleh mengetikkan dokumennya untuk pengusul "
            "yang menyampaikan lisan, asalkan Requested By diisi. "
            "Mati: usulannya harus dibuat sendiri oleh yang "
            "bersangkutan."
        ),
        order=130,
    ),

    "on_behalf_role": field.lookup(
        tab="initiator",
        label="On Behalf Role",
        lookup_endpoint="/api/accounts/lookup/roles/",
        display_key="on_behalf_role_name",
        required=False,
        visible_when={
            "all": [
                {
                    "field": "initiator_type",
                    "op": "ne",
                    "value": "any",
                },
                {"field": "allow_on_behalf", "op": "is_true"},
            ],
        },
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Dikosongkan = siapa pun yang punya izin membuat Employee "
            "Action boleh mengetikkannya."
        ),
        order=140,
    ),

    "is_active": field.switch(
        tab="initiator",
        label="Active",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dimatikan = aturannya diabaikan, dan jenis ini kembali "
            "boleh diajukan siapa pun yang punya izin."
        ),
        order=150,
    ),

    "sort_order": field.integer(
        tab="initiator",
        label="Sort Order",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=160,
    ),
}


EMPLOYEE_ACTION_POLICY_SCHEMA = {
    "module": "hr/employee-action-policies",
    "name": "EmployeeActionPolicy",
    "label": "Employee Action Policy",
    "endpoint": (
        "/api/administration/references/hr/employee-action-policies/"
    ),
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Employee Action Policy",
            description=(
                "Siapa yang boleh mengusulkan perubahan kepegawaian. "
                "Jenis yang tidak punya aturan di sini boleh diajukan "
                "siapa pun yang punya izin membuat Employee Action."
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

    # Menyalin baris ini ke perusahaan lain, tanpa mengetik
    # ulang. Cakupannya tetap per company — yang ditambahkan
    # cuma cara membuatnya.
    "actions": [
        action.save(),
        action.save_and_close(),
        action.delete(),
        action.export(),
        action.copy_to_companies(
            endpoint="/api/administration/references/hr/employee-action-policies/",
        ),
    ],

    "tabs": [
        tabs.form(
            key="general",
            label="Scope",
            fields=list(SCOPE_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="initiator",
            label="Requester",
            fields=list(INITIATOR_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
    ],

    "fields": {
        **SCOPE_FIELDS,
        **INITIATOR_FIELDS,
        # Kolom turunan yang sudah diwakili `display_key` di atas.
        # Tanpa dimatikan, tiap relasi muncul dua kali di tabel.
        **{
            name: {
                "table": False,
                "filter": False,
                "search": False,
                "sortable": False,
            }
            for name in (
                "action_type_label",
                "initiator_type_label",
                "company_name",
                "location_name",
                "employee_group_name",
                "initiator_role_name",
                "on_behalf_role_name",
            )
        },
    },
}


class EmployeeActionPolicyViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = EmployeeActionPolicySerializer
    service_class = EmployeeActionPolicyService

    framework_module = "hr/employee-action-policies"
    schema = EMPLOYEE_ACTION_POLICY_SCHEMA

    search_fields = [
        "code",
        "name",
        "description",
        "action_type",
    ]

    filterset_fields = [
        "action_type",
        "initiator_type",
        "company",
        "location",
        "employee_group",
        "allow_on_behalf",
        "is_active",
    ]

    ordering_fields = [
        "code",
        "name",
        "action_type",
        "sort_order",
        "created_at",
    ]

    ordering = ["action_type", "sort_order", "code"]

    def get_queryset(self):
        return (
            EmployeeActionPolicy.objects
            .select_related(
                "company",
                "location",
                "employee_group",
                "initiator_role",
                "on_behalf_role",
            )
            .filter(is_deleted=False)
        )
