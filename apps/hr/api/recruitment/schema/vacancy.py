from apps.framework.builders import field, tabs, ui


VACANCY_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Open", "value": "open"},
    {"label": "On Hold", "value": "on_hold"},
    {"label": "Filled", "value": "filled"},
    {"label": "Closed", "value": "closed"},
    {"label": "Cancelled", "value": "cancelled"},
]


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
        order=10,
    ),

    "title": field.text(
        tab="general",
        label="Title",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=VACANCY_STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=30,
    ),

    "quota": field.integer(
        tab="general",
        label="Quota",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=40,
    ),

    "open_date": field.date(
        tab="general",
        label="Open Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=50,
    ),

    "close_date": field.date(
        tab="general",
        label="Close Date",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=60,
    ),
}


# `lookup_params` mengirim SELURUH induk yang mungkin terisi, bukan
# hanya induk terdekat: level perantara boleh dilompati, dan penyaringan
# satu level akan gugur begitu itu terjadi (lihat CLAUDE.md).
ORGANIZATION_FIELDS = {
    "company": field.lookup(
        tab="organization",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        display_key="company_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=110,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint=(
            "/api/administration/organization/lookup/branches/"
        ),
        display_key="branch_name",
        lookup_params={"company_id": "$company"},
        depends_on="company",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=120,
    ),

    "location": field.lookup(
        tab="organization",
        label="Location",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        display_key="location_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        depends_on="company",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=130,
    ),

    "division": field.lookup(
        tab="organization",
        label="Division",
        lookup_endpoint=(
            "/api/administration/organization/lookup/divisions/"
        ),
        display_key="division_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
            "location_id": "$location",
        },
        depends_on="company",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=140,
    ),

    "department": field.lookup(
        tab="organization",
        label="Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        display_key="department_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
            "location_id": "$location",
            "division_id": "$division",
        },
        depends_on="company",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=150,
    ),

    "position": field.lookup(
        tab="organization",
        label="Position",
        lookup_endpoint=(
            "/api/administration/organization/lookup/positions/"
        ),
        display_key="position_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
            "location_id": "$location",
            "division_id": "$division",
            "department_id": "$department",
        },
        depends_on="company",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=160,
    ),

    "employment_type": field.lookup(
        tab="organization",
        label="Employment Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/employment-types/"
        ),
        display_key="employment_type_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=170,
    ),
}


DETAIL_FIELDS = {
    "description": field.textarea(
        tab="detail",
        label="Description",
        rows=5,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=210,
    ),

    "requirements": field.textarea(
        tab="detail",
        label="Requirements",
        rows=5,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=220,
    ),
}


JOB_VACANCY_FIELDS = {
    **GENERAL_FIELDS,
    **ORGANIZATION_FIELDS,
    **DETAIL_FIELDS,
}


JOB_VACANCY_DISPLAY_FIELDS = {
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
        "division_name",
        "department_name",
        "position_name",
        "employment_type_name",
        "status_label",
    )
}

JOB_VACANCY_DISPLAY_FIELDS["candidate_count"] = {
    "label": "Candidates",
    "table": True,
    "filter": False,
    "search": False,
    "sortable": False,
    "overview": True,
    "order": 70,
}


JOB_VACANCY_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="organization",
        label="Organization",
        fields=list(ORGANIZATION_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="detail",
        label="Description",
        fields=list(DETAIL_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),

    tabs.resource(
        key="candidates",
        label="Candidates",
        endpoint="/api/hr/candidates/",
        module="hr/candidates",
        foreign_key="vacancy",
        requires_record=True,
        order=40,
    ),
]


JOB_VACANCY_UI = {
    **ui.workspace(
        title="Recruitment",
        description=(
            "Kelola lowongan beserta kandidat yang melamar."
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


JOB_VACANCY_SCHEMA = {
    "module": "hr/recruitment",
    "name": "JobVacancy",
    "label": "Recruitment",
    "endpoint": "/api/hr/job-vacancies/",
    "schema_type": "crud",

    "ui": JOB_VACANCY_UI,
    "tabs": JOB_VACANCY_TABS,
    "fields": {
        **JOB_VACANCY_FIELDS,
        **JOB_VACANCY_DISPLAY_FIELDS,
    },
}
