from apps.framework.builders import field
from apps.hr.models import AttendanceApprovalStatus


APPROVAL_FIELDS = {
    "approval_status": field.select(
        tab="approval",
        label="Approval Status",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        options=[
            {
                "value": value,
                "label": label,
            }
            for value, label in AttendanceApprovalStatus.choices
        ],
        order=10,
    ),

    "is_manual_adjustment": field.boolean(
        tab="approval",
        label="Manual Adjustment",
        default=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=20,
    ),

    "adjustment_reason": field.textarea(
        tab="approval",
        label="Adjustment Reason",
        rows=3,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=30,
    ),
}