from apps.framework.builders import field


PROMOTION_ACTION = {
    "key": "promotion",
    "label": "Promote Employee",
    "endpoint": (
        "/api/hr/employees/{employee_id}/promote/"
    ),
    "method": "POST",
    "fields": {
        "position": field.lookup(
            label="New Position",
            lookup_endpoint=(
                "/api/administration/organization/"
                "lookup/positions/"
            ),
            required=True,
            order=10,
        ),
        "effective_date": field.date(
            label="Effective Date",
            required=True,
            order=20,
        ),
        "reason": field.textarea(
            label="Reason",
            rows=3,
            order=30,
        ),
    },
}