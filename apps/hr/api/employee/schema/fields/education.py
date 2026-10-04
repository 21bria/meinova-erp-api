from apps.framework.builders import field


EDUCATION_FIELDS = {
    "education": field.lookup(
        tab="education",
        label="Education Level",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/education-levels/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "degree": field.lookup(
        tab="education",
        label="Degree",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/degrees/"
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=20,
    ),

    "study_field": field.lookup(
        tab="education",
        label="Study Field",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/study-fields/"
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "institution_name": field.text(
        tab="education",
        label="Institution",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=40,
    ),

    "city": field.text(
        tab="education",
        label="City",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=50,
    ),

    "country": field.text(
        tab="education",
        label="Country",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=60,
    ),

    "start_date": field.date(
        tab="education",
        label="Start Date",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=70,
    ),

    "end_date": field.date(
        tab="education",
        label="End Date",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=80,
    ),

    "graduation_year": field.number(
        tab="education",
        label="Graduation Year",
        min=1900,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=90,
    ),

    "gpa": field.number(
        tab="education",
        label="GPA",
        min=0,
        max=4,
        step=0.01,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=100,
    ),

    "certificate_number": field.text(
        tab="education",
        label="Certificate Number",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=110,
    ),

    "is_highest_education": field.boolean(
        tab="education",
        label="Highest Education",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=120,
    ),

    "is_active": field.boolean(
        tab="education",
        label="Active",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=130,
    ),

    "notes": field.textarea(
        tab="education",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=140,
    ),
}