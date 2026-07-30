from apps.framework.builders import field


EXPERIENCE_FIELDS = {
    "company_name": field.text(
        tab="experience",
        label="Company Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=10,
    ),

    "position_name": field.text(
        tab="experience",
        label="Position",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "employment_type": field.text(
        tab="experience",
        label="Employment Type",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "industry": field.text(
        tab="experience",
        label="Industry",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=40,
    ),

    "location": field.text(
        tab="experience",
        label="Location",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=50,
    ),

    "start_date": field.date(
        tab="experience",
        label="Start Date",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=60,
    ),

    "end_date": field.date(
        tab="experience",
        label="End Date",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=70,
    ),

    "is_current": field.boolean(
        tab="experience",
        label="Current Employment",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=80,
    ),

    "last_salary": field.number(
        tab="experience",
        label="Last Salary",
        min=0,
        step=0.01,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=90,
    ),

    "job_description": field.textarea(
        tab="experience",
        label="Job Description",
        rows=4,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=100,
    ),

    "reason_for_leaving": field.textarea(
        tab="experience",
        label="Reason for Leaving",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=110,
    ),

    "reference_name": field.text(
        tab="experience",
        label="Reference Name",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=120,
    ),

    "reference_phone": field.text(
        tab="experience",
        label="Reference Phone",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),

    "is_verified": field.boolean(
        tab="experience",
        label="Verified",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=140,
    ),

    "is_active": field.boolean(
        tab="experience",
        label="Active",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=150,
    ),

    "notes": field.textarea(
        tab="experience",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=160,
    ),
}