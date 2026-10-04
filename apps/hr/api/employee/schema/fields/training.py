from apps.framework.builders import field


TRAINING_FIELDS = {
    "training_category": field.lookup(
        tab="training",
        label="Training Category",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/training-categories/"
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "training_name": field.text(
        tab="training",
        label="Training Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "provider": field.lookup(
        tab="training",
        label="Training Provider",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/training-providers/"
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "start_date": field.date(
        tab="training",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=40,
    ),

    "end_date": field.date(
        tab="training",
        label="End Date",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=50,
    ),

    "duration_hours": field.number(
        tab="training",
        label="Duration (Hours)",
        min=0,
        step=0.01,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=60,
    ),

    "score": field.number(
        tab="training",
        label="Score",
        min=0,
        step=0.01,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=70,
    ),

    "certificate_number": field.text(
        tab="training",
        label="Certificate Number",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=80,
    ),

    "expiry_date": field.date(
        tab="training",
        label="Expiry Date",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=90,
    ),

    "uploaded_file": field.file(
        tab="training",
        label="Attachment",
        required=False,
        multiple=False,
        accept=[
            "pdf",
            "jpg",
            "jpeg",
            "png",
            "doc",
            "docx",
        ],
        max_size=10,
        order=100,
    ),
    "uploaded_file": field.file(
            tab="training",
            label="Attachment",
            category="attachment",   # default
            public=False,
            required=False,
            multiple=False,
            accept=[
                "pdf",
                "jpg",
                "jpeg",
                "png",
                "doc",
                "docx",
            ],

            max_size=10,
            preview=True,
            download=True,
            replace=True,
            delete=True,
            table=False,
            filter=False,
            search=False,
            sortable=False,
            order=70,
        ),
    "is_mandatory": field.boolean(
        tab="training",
        label="Mandatory",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=110,
    ),

    "is_completed": field.boolean(
        tab="training",
        label="Completed",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=120,
    ),

    "is_active": field.boolean(
        tab="training",
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
        tab="training",
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