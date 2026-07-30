from apps.framework.builders import field


CERTIFICATE_FIELDS = {
    "certificate_type": field.lookup(
        tab="certificate",
        label="Certificate Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/certificate-types/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "certificate_name": field.text(
        tab="certificate",
        label="Certificate Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "certificate_number": field.text(
        tab="certificate",
        label="Certificate Number",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "issuing_organization": field.text(
        tab="certificate",
        label="Issuing Organization",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=40,
    ),

    "issue_date": field.date(
        tab="certificate",
        label="Issue Date",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=50,
    ),

    "expiry_date": field.date(
        tab="certificate",
        label="Expiry Date",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=60,
    ),

    "credential_id": field.text(
        tab="certificate",
        label="Credential ID",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),

    "credential_url": field.text(
        tab="certificate",
        label="Credential URL",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=80,
    ),

    "attachment": field.file(
        tab="certificate",
        label="Attachment",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=90,
    ),

    "is_lifetime": field.boolean(
        tab="certificate",
        label="Lifetime Certificate",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=100,
    ),

    "is_verified": field.boolean(
        tab="certificate",
        label="Verified",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=110,
    ),

    "verification_notes": field.textarea(
        tab="certificate",
        label="Verification Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=120,
    ),

    "is_active": field.boolean(
        tab="certificate",
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
        tab="certificate",
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