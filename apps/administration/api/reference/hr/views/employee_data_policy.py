"""
Layar setting: bagian mana dari data pegawai yang boleh dilihat siapa.

Bentuknya sama dengan `EmployeeActionPolicy` — sasaran (company /
location / employee group) plus aturannya. Bagian terpenting layar ini
justru help text-nya: mengosongkan Company berarti "berlaku untuk
semua", **bukan** "tidak berlaku"; itu jebakan yang sudah tiga kali
muncul di master berjenjang lain di sistem ini.
"""

from rest_framework import serializers

from apps.administration.models import (
    EmployeeDataPolicy,
    EmployeeDataSubject,
)
from apps.core.services.master import BaseMasterService
from apps.framework.builders import action, field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.services.company_copy import (
    CompanyCopyMixin,
    CompanyCopyViewSetMixin,
)
from apps.framework.views.mixins import ServiceWriteMixin


class EmployeeDataPolicyService(CompanyCopyMixin, BaseMasterService):
    model = EmployeeDataPolicy

    copy_scope_fields = [
        "company",
        "location",
        "employee_group",
        "subject",
    ]

    copy_rule_fields = [
        "description",
        "allow_self",
        "allow_manager",
        "manager_levels",
        "allow_department_head",
        "role",
        "is_active",
        "sort_order",
    ]



class EmployeeDataPolicySerializer(serializers.ModelSerializer):
    subject_label = serializers.CharField(
        source="get_subject_display",
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

    role_name = serializers.CharField(
        source="role.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeDataPolicy
        fields = "__all__"

        read_only_fields = [
            "subject_label",
            "company_name",
            "location_name",
            "employee_group_name",
            "role_name",
        ]


SUBJECT_OPTIONS = [
    {"value": value, "label": label}
    for value, label in EmployeeDataSubject.choices
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

    "subject": field.select(
        tab="general",
        label="Protected Data",
        options=SUBJECT_OPTIONS,
        display_key="subject_label",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Kelompok yang tidak punya baris di sini tetap terlihat "
            "oleh siapa pun yang datanya masuk cakupannya."
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
            "site tertentu punya aturan kerahasiaannya sendiri."
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


AUDIENCE_FIELDS = {
    "allow_self": field.switch(
        tab="audience",
        label="The Employee",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Gajinya sendiri bukan rahasia darinya, jadi hampir tidak "
            "pernah ada alasan mematikannya."
        ),
        order=110,
    ),

    "allow_manager": field.switch(
        tab="audience",
        label="Direct Manager",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Atasan pegawai menurut garis pelaporan.",
        order=120,
    ),

    "manager_levels": field.integer(
        tab="audience",
        label="Manager Levels",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when={"field": "allow_manager", "op": "is_true"},
        help_text=(
            "1 = atasan langsung saja, 2 = sampai atasannya atasan."
        ),
        order=130,
    ),

    "allow_department_head": field.switch(
        tab="audience",
        label="Department Head",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Pemegang jabatan bertanda Manager di department pegawai "
            "itu. Perlu diketahui: kepala departemen tidak punya "
            "cakupan lokasi — di tenant yang satu departemennya "
            "tersebar di beberapa site, ini membuka data lintas site."
        ),
        order=140,
    ),

    "role": field.lookup(
        tab="audience",
        label="Role",
        lookup_endpoint="/api/accounts/lookup/roles/",
        display_key="role_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Role yang boleh melihat, mis. HR-MANAGER. Dikosongkan = "
            "tidak ada role tambahan di luar tiga pilihan di atas."
        ),
        order=150,
    ),

    "is_active": field.switch(
        tab="audience",
        label="Active",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dimatikan = aturannya diabaikan, dan kelompok ini kembali "
            "terlihat oleh siapa pun yang datanya masuk cakupannya."
        ),
        order=160,
    ),

    "sort_order": field.integer(
        tab="audience",
        label="Sort Order",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=170,
    ),
}


EMPLOYEE_DATA_POLICY_SCHEMA = {
    "module": "hr/employee-data-policies",
    "name": "EmployeeDataPolicy",
    "label": "Employee Data Policy",
    "endpoint": (
        "/api/administration/references/hr/employee-data-policies/"
    ),
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Employee Data Policy",
            description=(
                "Bagian mana dari data pegawai yang boleh dilihat "
                "siapa. Kelompok yang tidak punya aturan di sini "
                "terlihat oleh siapa pun yang datanya masuk "
                "cakupannya. Superuser selalu melihat semuanya."
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
            endpoint="/api/administration/references/hr/employee-data-policies/",
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
            key="audience",
            label="Who Can See",
            fields=list(AUDIENCE_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
    ],

    "fields": {
        **SCOPE_FIELDS,
        **AUDIENCE_FIELDS,
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
                "subject_label",
                "company_name",
                "location_name",
                "employee_group_name",
                "role_name",
            )
        },
    },
}


class EmployeeDataPolicyViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = EmployeeDataPolicySerializer
    service_class = EmployeeDataPolicyService

    framework_module = "hr/employee-data-policies"
    schema = EMPLOYEE_DATA_POLICY_SCHEMA

    search_fields = [
        "code",
        "name",
        "description",
        "subject",
    ]

    filterset_fields = [
        "subject",
        "company",
        "location",
        "employee_group",
        "role",
        "allow_self",
        "allow_manager",
        "allow_department_head",
        "is_active",
    ]

    ordering_fields = [
        "code",
        "name",
        "subject",
        "sort_order",
        "created_at",
    ]

    ordering = ["subject", "sort_order", "code"]

    def get_queryset(self):
        return (
            EmployeeDataPolicy.objects
            .select_related(
                "company",
                "location",
                "employee_group",
                "role",
            )
            .filter(is_deleted=False)
        )
