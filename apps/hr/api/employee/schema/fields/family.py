from apps.framework.builders import field


FAMILY_FIELDS = {
    "relationship": field.lookup(
        tab="family",
        label="Relationship",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/family-relationships/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "full_name": field.text(
        tab="family",
        label="Full Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "gender": field.lookup(
        tab="family",
        label="Gender",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/genders/"
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "birth_place": field.text(
        tab="family",
        label="Birth Place",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),

    "birth_date": field.date(
        tab="family",
        label="Birth Date",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=50,
    ),

    "occupation": field.text(
        tab="family",
        label="Occupation",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=60,
    ),

    "phone": field.text(
        tab="family",
        label="Phone",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),

    "is_dependent": field.boolean(
        tab="family",
        label="Dependent",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=80,
    ),

    "is_emergency_contact": field.boolean(
        tab="family",
        label="Emergency Contact",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=90,
    ),

    "is_active": field.boolean(
        tab="family",
        label="Active",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=100,
    ),

    "notes": field.textarea(
        tab="family",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=110,
    ),
}