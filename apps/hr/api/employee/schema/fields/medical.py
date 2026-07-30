from apps.framework.builders import field


MEDICAL_FIELDS = {
    "medical_type": field.select(
        tab="medical",
        label="Medical Type",
        options=[
            {
                "value": "medical_checkup",
                "label": "Medical Checkup",
            },
            {
                "value": "fitness_to_work",
                "label": "Fitness to Work",
            },
            {
                "value": "drug_test",
                "label": "Drug Test",
            },
            {
                "value": "vaccination",
                "label": "Vaccination",
            },
            {
                "value": "vision_test",
                "label": "Vision Test",
            },
            {
                "value": "hearing_test",
                "label": "Hearing Test",
            },
            {
                "value": "other",
                "label": "Other",
            },
        ],
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "event_date": field.date(
        tab="medical",
        label="Event Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=20,
    ),

    "provider_name": field.text(
        tab="medical",
        label="Hospital / Provider",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "doctor_name": field.text(
        tab="medical",
        label="Doctor",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=40,
    ),

    "result": field.text(
        tab="medical",
        label="Result",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=50,
    ),

    "fitness_status": field.select(
        tab="medical",
        label="Fitness Status",
        options=[
            {
                "value": "not_applicable",
                "label": "Not Applicable",
            },
            {
                "value": "fit",
                "label": "Fit",
            },
            {
                "value": "fit_with_restriction",
                "label": "Fit With Restriction",
            },
            {
                "value": "temporary_unfit",
                "label": "Temporary Unfit",
            },
            {
                "value": "permanent_unfit",
                "label": "Permanent Unfit",
            },
        ],
        default="not_applicable",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=60,
    ),

    "restriction_notes": field.textarea(
        tab="medical",
        label="Restriction Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),

    "next_due_date": field.date(
        tab="medical",
        label="Next Due Date",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=80,
    ),

    "attachment": field.file(
        tab="medical",
        label="Attachment",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=90,
    ),

    "is_confidential": field.boolean(
        tab="medical",
        label="Confidential",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=100,
    ),

    "is_verified": field.boolean(
        tab="medical",
        label="Verified",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=110,
    ),

    "is_active": field.boolean(
        tab="medical",
        label="Active",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=120,
    ),

    "notes": field.textarea(
        tab="medical",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=130,
    ),
}