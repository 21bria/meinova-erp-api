from apps.framework.builders import field


SYSTEM_FIELDS = {
    "external_id": field.text(
        tab="system",
        label="External ID",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=10,
    ),

    "device_code": field.text(
        tab="system",
        label="Device Code",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "import_batch_id": field.text(
        tab="system",
        label="Import Batch ID",
        table=False,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "notes": field.textarea(
        tab="system",
        label="Notes",
        rows=4,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),
}