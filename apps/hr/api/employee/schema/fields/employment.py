from apps.framework.builders import field


EMPLOYMENT_FIELDS = {
    "employment_status": field.lookup(
        tab="employment",
        label="Employment Status",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employment-statuses/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=10,
    ),

    "employment_type": field.lookup(
        tab="employment",
        label="Employment Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employment-types/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=20,
    ),

    "employee_group": field.lookup(
        tab="employment",
        label="Employee Group",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employee-groups/"
        ),
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=30,
    ),

    "employment_effective_date": field.date(
        tab="employment",
        label="Employment Effective Date",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=40,
    ),

    "contract_type": field.lookup(
        tab="employment",
        label="Contract Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/contract-types/"
        ),
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=50,
    ),

    "probation_type": field.lookup(
        tab="employment",
        label="Probation Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/probation-types/"
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=60,
    ),

    "join_date": field.date(
        tab="employment",
        label="Join Date",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=70,
    ),

    "confirmation_date": field.date(
        tab="employment",
        label="Confirmation Date",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=80,
    ),

    "probation_start": field.date(
        tab="employment",
        label="Probation Start",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=90,
    ),

    "probation_end": field.date(
        tab="employment",
        label="Probation End",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=100,
    ),

    "contract_start": field.date(
        tab="employment",
        label="Contract Start",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=110,
    ),

    "contract_end": field.date(
        tab="employment",
        label="Contract End",
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=120,
    ),

    "work_schedule": field.lookup(
        tab="employment",
        label="Work Schedule",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/work-schedules/"
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=130,
    ),

    "working_calendar": field.lookup(
        tab="employment",
        label="Working Calendar",
        lookup_endpoint=(
            "/api/administration/calendar/"
            "lookup/work-calendars/"
        ),
        depends_on=["company"],
        lookup_params={
            "company_id": "$company",
            "site_id": "$site",
        },
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=140,
    ),

    "shift": field.lookup(
        tab="employment",
        label="Shift",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/shifts/"
        ),
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=150,
    ),

    "notice_period_days": field.number(
        tab="employment",
        label="Notice Period (Days)",
        min=0,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=160,
    ),

    "employment_notes": field.textarea(
        tab="employment",
        label="Employment Notes",
        rows=4,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=170,
    ),
}