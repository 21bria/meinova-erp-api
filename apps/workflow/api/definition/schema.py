"""
Schema layar Workflow Definition.

Bentuknya workspace bertab dengan tabel step **inline**: alur
persetujuan dibaca sebagai urutan, dan menambah empat tingkat lewat
empat dialog membuat tingkat-tingkat yang justru harus dibandingkan
tidak pernah terlihat bersamaan. Pola yang sama dengan tabel periode di
Site Rotation.
"""

from apps.framework.builders import action, field, tabs, ui

from apps.workflow.api.step.schema import STEP_GRID_FIELDS
from apps.workflow.labels import WORKFLOW_STATUS_LABELS, choices


# Diambil dari peta label yang sama dengan kolom `status_label` di
# serializer. Ditulis tangan di sini sebelumnya, dan itu berarti dropdown
# dan kolom tampilan punya dua sumber untuk satu enum — begitu salah satu
# diterjemahkan, layarnya menyebut hal yang sama dengan dua nama tanpa
# satu pun error. Nilainya tetap `draft` / `active` / `inactive`.
STATUS_OPTIONS = choices(WORKFLOW_STATUS_LABELS)


GENERAL_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        help_text="Kode unik alur, mis. HR-HO-ANNUAL-LEAVE.",
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

    "module": field.text(
        tab="general",
        label="Module",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        help_text="Modul pemilik dokumen, mis. hr.",
        order=30,
    ),

    "document_type": field.text(
        tab="general",
        label="Document Type",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        help_text=(
            "Jenis dokumen yang dilayani, mis. leave_request atau "
            "travel_request."
        ),
        order=40,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Hanya alur berstatus Aktif yang dipakai saat dokumen "
            "diajukan."
        ),
        order=50,
    ),

    "version": field.integer(
        tab="general",
        label="Version",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Penanda untuk manusia. Dokumen yang sudah berjalan "
            "menunjuk step-nya langsung, jadi mengubah alur tidak "
            "mengubah dokumen yang sedang berjalan."
        ),
        order=60,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),
}


SCOPE_FIELDS = {
    "company": field.lookup(
        tab="scope",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua company. Kosong berarti "
            "'semua', bukan 'belum diisi'."
        ),
        order=110,
    ),

    "branch": field.lookup(
        tab="scope",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        display_key="branch_name",
        lookup_params={"company_id": "$company"},
        depends_on="company",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        help_text="Dikosongkan = berlaku untuk semua branch.",
        order=120,
    ),

    "location": field.lookup(
        tab="scope",
        label="Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        depends_on="company",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Lokasi kerja pengaju. Ini kolom yang membedakan alur Head "
            "Office dari alur site."
        ),
        order=130,
    ),

    "employee_group": field.lookup(
        tab="scope",
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
        help_text="Dikosongkan = berlaku untuk semua golongan pegawai.",
        order=140,
    ),

    "scope_label": field.text(
        tab="scope",
        label="Applies To",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text="Ringkasan cakupan alur ini.",
        order=150,
    ),

    "specificity": field.integer(
        tab="scope",
        label="Priority Score",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Makin tinggi makin menang saat beberapa alur sama-sama "
            "cocok. Dihitung dari cakupan, bukan diketik."
        ),
        order=160,
    ),
}


WORKFLOW_DEFINITION_FIELDS = {
    **GENERAL_FIELDS,
    **SCOPE_FIELDS,
}


DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "company_name",
        "branch_name",
        "location_name",
        "employee_group_name",
        "status_label",
        "step_count",
    )
}


WORKFLOW_DEFINITION_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="scope",
        label="Scope",
        fields=list(SCOPE_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.resource(
        key="steps",
        label="Approval Steps",
        endpoint="/api/workflow/steps/",
        module="workflow/steps",
        foreign_key="definition",
        fields=STEP_GRID_FIELDS,
        inline=True,
        requires_record=True,
        order=30,
    ),
    tabs.resource(
        key="instances",
        label="Running Documents",
        endpoint="/api/workflow/instances/",
        module="workflow/instances",
        foreign_key="definition",
        readonly=True,
        create=False,
        requires_record=True,
        order=40,
    ),
]


WORKFLOW_DEFINITION_UI = {
    **ui.workspace(
        title="Workflow Definition",
        description=(
            "Alur persetujuan per jenis dokumen. Cakupan yang "
            "dikosongkan berarti berlaku untuk semua."
        ),
        size="full",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


WORKFLOW_DEFINITION_SCHEMA = {
    # Namespace katalog terjemahan frontend.
    #
    # Dibaca generator (`scripts/meinova/generators/i18n.mjs`): label
    # kolom/form/filter dipancarkan sebagai
    # `resourceLabel("workflow.definitions.fields.<field>", "<label Inggris>")`
    # alih-alih literal. Argumen keduanya label yang ada di berkas ini,
    # jadi modul tetap benar walau katalognya belum diisi.
    #
    # **Nama field tidak ikut** — hanya labelnya. `approver_type` tetap
    # `approver_type` di payload, di query string, dan di database.
    "i18n": {"namespace": "workflow.definitions"},

    "module": "workflow/definitions",
    "name": "Workflow Definition",
    "label": "Workflow Definition",
    "endpoint": "/api/workflow/definitions/",
    "schema_type": "crud",

    "ui": WORKFLOW_DEFINITION_UI,
    "tabs": WORKFLOW_DEFINITION_TABS,

    "actions": [
        action.copy_to_companies(
            endpoint="/api/workflow/definitions/",
            help_text=(
                "Step dan rantai cadangannya ikut. Salinannya selalu "
                "berstatus Draft — periksa dulu approver-nya lewat "
                "Preview Approvers sebelum diaktifkan, karena struktur "
                "organisasi perusahaan tujuan bisa saja belum punya "
                "pemegang role yang sama."
            ),
        ),
    ],
    "fields": {
        **WORKFLOW_DEFINITION_FIELDS,
        **DISPLAY_FIELDS,
    },
}
