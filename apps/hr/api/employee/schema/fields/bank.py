from apps.framework.builders import field


BANK_FIELDS = {
    "bank": field.lookup(
        tab="bank",
        label="Bank",
        lookup_endpoint=(
            "/api/administration/references/bank/"
            "lookup/banks/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "branch_name": field.text(
        tab="bank",
        label="Branch",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "account_number": field.text(
        tab="bank",
        label="Account Number",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "account_name": field.text(
        tab="bank",
        label="Account Holder",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=40,
    ),

    "currency": field.lookup(
        tab="bank",
        label="Currency",
        lookup_endpoint=(
            "/api/administration/currency/"
            "lookup/currencies/"
        ),
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=50,
    ),

    "swift_code": field.text(
        tab="bank",
        label="SWIFT Code",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=60,
    ),

    "iban": field.text(
        tab="bank",
        label="IBAN",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=70,
    ),

    "is_primary": field.boolean(
        tab="bank",
        label="Primary Account",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=80,
    ),

    "is_active": field.boolean(
        tab="bank",
        label="Active",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=90,
    ),

    "notes": field.textarea(
        tab="bank",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=100,
    ),
}