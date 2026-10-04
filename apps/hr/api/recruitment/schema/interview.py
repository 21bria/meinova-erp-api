from apps.framework.builders import field, tabs, ui


INTERVIEW_RESULT_OPTIONS = [
    {"label": "Scheduled", "value": "scheduled"},
    {"label": "Passed", "value": "passed"},
    {"label": "Failed", "value": "failed"},
    {"label": "No Show", "value": "no_show"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "candidate": field.lookup(
        tab="general",
        label="Candidate",
        lookup_endpoint="/api/hr/lookup/candidates/",
        display_key="candidate_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=10,
    ),

    "stage": field.integer(
        tab="general",
        label="Stage",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Urutan tahap wawancara. Tidak dibatasi jumlahnya."
        ),
        order=20,
    ),

    "interview_type": field.lookup(
        tab="general",
        label="Interview Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/interview-types/"
        ),
        display_key="interview_type_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "scheduled_at": field.datetime(
        tab="general",
        label="Scheduled At",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=40,
    ),

    "interviewer": field.lookup(
        tab="general",
        label="Interviewer",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="interviewer_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=False,
        order=50,
    ),
}


RESULT_FIELDS = {
    "result": field.select(
        tab="result",
        label="Result",
        display_key="result_label",
        options=INTERVIEW_RESULT_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=110,
    ),

    "score": field.decimal(
        tab="result",
        label="Score",
        decimal_places=2,
        max_digits=6,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=120,
    ),

    "notes": field.textarea(
        tab="result",
        label="Notes",
        rows=4,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),
}


CANDIDATE_INTERVIEW_FIELDS = {
    **GENERAL_FIELDS,
    **RESULT_FIELDS,
}


CANDIDATE_INTERVIEW_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "candidate_number",
        "candidate_name",
        "interview_type_name",
        "interviewer_name",
        "result_label",
    )
}


CANDIDATE_INTERVIEW_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="result",
        label="Result",
        fields=list(RESULT_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
]


CANDIDATE_INTERVIEW_UI = {
    **ui.dialog(
        title="Interview",
        description="Tahapan wawancara kandidat.",
        size="lg",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


CANDIDATE_INTERVIEW_SCHEMA = {
    "module": "hr/candidate-interviews",
    "name": "CandidateInterview",
    "label": "Interview",
    "endpoint": "/api/hr/candidate-interviews/",
    "schema_type": "crud",

    "ui": CANDIDATE_INTERVIEW_UI,
    "tabs": CANDIDATE_INTERVIEW_TABS,
    "fields": {
        **CANDIDATE_INTERVIEW_FIELDS,
        **CANDIDATE_INTERVIEW_DISPLAY_FIELDS,
    },
}
