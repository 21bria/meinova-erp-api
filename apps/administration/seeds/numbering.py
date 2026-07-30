from apps.administration.models import NumberingSequence

from .base import seed_reference


NUMBERINGS = [
    # HR
    ("hr", "employee", "EMP", "Employee", "EMP", "", "-", 5, True, False),
    ("hr", "leave", "LV", "Leave Request", "LV", "", "-", 5, True, False),

    # Payroll
    ("payroll", "payroll_run", "PAY", "Payroll Run", "PAY", "", "-", 5, True, False),

    # Procurement
    ("procurement", "purchase_request", "PR", "Purchase Request", "PR", "", "-", 5, True, False),
    ("procurement", "purchase_order", "PO", "Purchase Order", "PO", "", "-", 5, True, False),

    # Inventory
    ("inventory", "goods_receipt", "GR", "Goods Receipt", "GR", "", "-", 5, True, False),
    ("inventory", "goods_issue", "GI", "Goods Issue", "GI", "", "-", 5, True, False),

    # Finance
    ("finance", "journal", "JV", "Journal Voucher", "JV", "", "-", 5, False, True),
    ("finance", "payment", "PAY", "Payment", "PAY", "", "-", 5, False, True),

    # Sales
    ("sales", "quotation", "SQ", "Sales Quotation", "SQ", "", "-", 5, True, False),
    ("sales", "sales_order", "SO", "Sales Order", "SO", "", "-", 5, True, False),
    ("sales", "invoice", "INV", "Invoice", "INV", "", "-", 5, True, False),
]


def seed_numbering() -> None:
    seed_reference(
        NumberingSequence,
        [
            {
                "company": None,
                "module": module,
                "document_type": document_type,
                "code": code,
                "name": name,
                "prefix": prefix,
                "suffix": suffix,
                "separator": separator,
                "padding": padding,
                "current_number": 0,
                "reset_yearly": reset_yearly,
                "reset_monthly": reset_monthly,
            }
            for (
                module,
                document_type,
                code,
                name,
                prefix,
                suffix,
                separator,
                padding,
                reset_yearly,
                reset_monthly,
            ) in NUMBERINGS
        ],
    )