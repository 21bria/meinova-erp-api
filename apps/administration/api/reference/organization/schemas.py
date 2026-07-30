def _base_schema(title: str):
    return {
        "ui": {"title": title},
        "fields": {
            "code": {"label": "Code", "required": True},
            "name": {"label": "Name", "required": True},
            "description": {"label": "Description", "type": "textarea"},
            "sort_order": {"label": "Sort Order"},
            "is_active": {"label": "Active"},
        },
    }


def company_type_schema(module: str):
    return _base_schema("Company Types")


def branch_type_schema(module: str):
    return _base_schema("Branch Types")


def site_type_schema(module: str):
    return _base_schema("Site Types")


def work_location_type_schema(module: str):
    return _base_schema("Work Location Types")