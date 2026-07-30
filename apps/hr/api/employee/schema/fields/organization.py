from apps.framework.builders import field


ORGANIZATION_FIELDS = {
    "company": field.lookup(
        tab="organization",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        required=True,
        table=False,
        filter=True,
        order=10,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint=(
            "/api/administration/organization/lookup/branches/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        filter=True,
        order=20,
    ),

    "site": field.lookup(
        tab="organization",
        label="Site",
        lookup_endpoint=(
            "/api/administration/organization/lookup/sites/"
        ),
        depends_on="branch",
        lookup_params={
            "branch_id": "$branch",
        },
        table=False,
        filter=True,
        order=30,
    ),

    "division": field.lookup(
        tab="organization",
        label="Division",
        lookup_endpoint=(
            "/api/administration/organization/lookup/divisions/"
        ),
        depends_on="site",
        lookup_params={
            "site_id": "$site",
        },
        table=False,
        filter=True,
        order=40,
    ),

    "department": field.lookup(
        tab="organization",
        label="Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        depends_on="division",
        lookup_params={
            "division_id": "$division",
        },
        table=False,
        filter=True,
        order=50,
    ),

    "section": field.lookup(
        tab="organization",
        label="Section",
        lookup_endpoint=(
            "/api/administration/organization/lookup/sections/"
        ),
        depends_on="department",
        lookup_params={
            "department_id": "$department",
        },
        table=False,
        filter=True,
        order=60,
    ),

    "position": field.lookup(
        tab="organization",
        label="Position",
        lookup_endpoint=(
            "/api/administration/organization/lookup/positions/"
        ),
        depends_on="section",
        lookup_params={
            "section_id": "$section",
        },
        table=False,
        filter=True,
        order=70,
    ),

    "job_level": field.lookup(
        tab="organization",
        label="Job Level",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/job-levels/"
        ),
        table=False,
        filter=True,
        order=80,
    ),

    "job_grade": field.lookup(
        tab="organization",
        label="Job Grade",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/job-grades/"
        ),
        table=False,
        filter=True,
        order=90,
    ),

    "reports_to": field.lookup(
        tab="organization",
        label="Reports To",
        lookup_endpoint="/api/hr/lookup/employees/",
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        filter=True,
        order=100,
    ),

    "cost_center": field.lookup(
        tab="organization",
        label="Cost Center",
        lookup_endpoint=(
            "/api/administration/organization/"
            "lookup/cost-centers/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        filter=True,
        order=120,
    ),

    "project": field.lookup(
        tab="organization",
        label="Project",
        lookup_endpoint="/api/projects/lookup/projects/",
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        order=130,
    ),

    "organization_effective_date": field.date(
        tab="organization",
        label="Effective Date",
        required=True,
        table=False,
        order=140,
    ),

    "organization_notes": field.textarea(
        tab="organization",
        label="Organization Notes",
        rows=4,
        layout="full",
        table=False,
        order=150,
    ),
}