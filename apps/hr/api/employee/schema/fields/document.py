# apps/hr/api/employee/schema/fields/document.py

from apps.framework.builders import field


DOCUMENT_FIELDS = {
    "document_type": field.lookup(
        tab="document",
        label="Document Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/document-types/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "document_name": field.text(
        tab="document",
        label="Document Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "document_number": field.text(
        tab="document",
        label="Document Number",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "issue_date": field.date(
        tab="document",
        label="Issue Date",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=40,
    ),

    "expiry_date": field.date(
        tab="document",
        label="Expiry Date",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=50,
    ),

    "issuing_authority": field.text(
        tab="document",
        label="Issuing Authority",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=60,
    ),

    "file": field.file(
        tab="document",
        label="File",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=70,
    ),

    "is_required": field.boolean(
        tab="document",
        label="Required Document",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=80,
    ),

    "is_verified": field.boolean(
        tab="document",
        label="Verified",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=90,
    ),

    "verification_notes": field.textarea(
        tab="document",
        label="Verification Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=100,
    ),

    "is_active": field.boolean(
        tab="document",
        label="Active",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=110,
    ),

    "notes": field.textarea(
        tab="document",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=120,
    ),
}