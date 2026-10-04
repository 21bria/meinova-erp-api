from apps.framework.builders import field, tabs, ui


GENERAL_FIELDS = {
    "candidate_number": field.text(
        tab="general",
        label="Candidate Number",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "full_name": field.text(
        tab="general",
        label="Full Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "vacancy": field.lookup(
        tab="general",
        label="Vacancy",
        lookup_endpoint="/api/hr/lookup/job-vacancies/",
        display_key="vacancy_title",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "status": field.lookup(
        tab="general",
        label="Status",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/candidate-statuses/"
        ),
        display_key="status_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=40,
    ),

    "source": field.lookup(
        tab="general",
        label="Source",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/recruitment-sources/"
        ),
        display_key="source_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=50,
    ),

    "applied_date": field.date(
        tab="general",
        label="Applied Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=60,
    ),
}


PROFILE_FIELDS = {
    "email": field.email(
        tab="profile",
        label="Email",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=110,
    ),

    "phone": field.phone(
        tab="profile",
        label="Phone",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=120,
    ),

    "gender": field.lookup(
        tab="profile",
        label="Gender",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/genders/"
        ),
        display_key="gender_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=130,
    ),

    "birth_date": field.date(
        tab="profile",
        label="Birth Date",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=140,
    ),

    "education": field.lookup(
        tab="profile",
        label="Education",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/educations/"
        ),
        display_key="education_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=150,
    ),

    "resume_file": field.file(
        tab="profile",
        label="Resume",
        accept=".pdf,.doc,.docx",
        max_size_mb=10,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=160,
    ),
}


OFFER_FIELDS = {
    "expected_salary": field.currency(
        tab="offer",
        label="Expected Salary",
        currency_field="currency",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=210,
    ),

    "currency": field.lookup(
        tab="offer",
        label="Currency",
        lookup_endpoint=(
            "/api/administration/currency/lookup/currencies/"
        ),
        display_key="currency_code",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=220,
    ),

    "rejection_reason": field.lookup(
        tab="offer",
        label="Rejection Reason",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/rejection-reasons/"
        ),
        display_key="rejection_reason_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=230,
    ),

    "hired_employee": field.lookup(
        tab="offer",
        label="Hired Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="hired_employee_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Diisi setelah kandidat diterima dan datanya dibuat jadi "
            "pegawai — supaya asal-usulnya tidak hilang."
        ),
        order=240,
    ),

    "hired_date": field.date(
        tab="offer",
        label="Hired Date",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=250,
    ),

    "notes": field.textarea(
        tab="offer",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=260,
    ),
}


CANDIDATE_FIELDS = {
    **GENERAL_FIELDS,
    **PROFILE_FIELDS,
    **OFFER_FIELDS,
}


CANDIDATE_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "vacancy_code",
        "vacancy_title",
        "gender_name",
        "education_name",
        "source_name",
        "status_name",
        "currency_code",
        "rejection_reason_name",
        "hired_employee_name",
        "resume_file_detail",
    )
}


CANDIDATE_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="profile",
        label="Profile",
        fields=list(PROFILE_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="offer",
        label="Offer & Outcome",
        fields=list(OFFER_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),

    tabs.resource(
        key="interviews",
        label="Interviews",
        endpoint="/api/hr/candidate-interviews/",
        module="hr/candidate-interviews",
        foreign_key="candidate",
        requires_record=True,
        order=40,
    ),
]


CANDIDATE_UI = {
    **ui.workspace(
        title="Candidates",
        description=(
            "Pelamar beserta tahapan wawancara dan hasil akhirnya."
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


CANDIDATE_SCHEMA = {
    "module": "hr/candidates",
    "name": "Candidate",
    "label": "Candidates",
    "endpoint": "/api/hr/candidates/",
    "schema_type": "crud",

    "ui": CANDIDATE_UI,
    "tabs": CANDIDATE_TABS,
    "fields": {
        **CANDIDATE_FIELDS,
        **CANDIDATE_DISPLAY_FIELDS,
    },
}
