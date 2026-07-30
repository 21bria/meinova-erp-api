EMPLOYEE_HISTORY_SECTIONS = [
    {
        "key": "organization",
        "label": "Organization",
        "endpoint": (
            "/api/hr/employees/{employee_id}/"
            "organization-history/"
        ),
        "order": 10,
    },
    {
        "key": "employment",
        "label": "Employment",
        "endpoint": (
            "/api/hr/employees/{employee_id}/"
            "employment-history/"
        ),
        "order": 20,
    },
    {
        "key": "payroll",
        "label": "Payroll",
        "endpoint": (
            "/api/hr/employees/{employee_id}/"
            "payroll-history/"
        ),
        "order": 30,
    },
    {
        "key": "promotion",
        "label": "Promotion",
        "endpoint": (
            "/api/hr/employees/{employee_id}/"
            "promotion-history/"
        ),
        "order": 40,
    },
    {
        "key": "transfer",
        "label": "Transfer",
        "endpoint": (
            "/api/hr/employees/{employee_id}/"
            "transfer-history/"
        ),
        "order": 50,
    },
    {
        "key": "termination",
        "label": "Termination",
        "endpoint": (
            "/api/hr/employees/{employee_id}/"
            "termination-history/"
        ),
        "order": 60,
    },
]