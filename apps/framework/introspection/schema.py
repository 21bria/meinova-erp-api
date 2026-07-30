from .model import inspect_model, humanize
from .serializer import inspect_serializer

SCHEMA_CRUD = "crud"
SCHEMA_SETTING = "setting"
SCHEMA_TREE = "tree"


def deep_merge(base: dict, override: dict):
    result = dict(base)

    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def get_model_from_serializer(serializer_class):
    meta = getattr(serializer_class, "Meta", None)
    return getattr(meta, "model", None)


def build_module_meta(viewset, default_slug="module"):
    module = getattr(viewset, "framework_module", None)

    serializer_class = getattr(viewset, "serializer_class", None)

    if serializer_class is None and hasattr(
        viewset,
        "get_serializer_class",
    ):
        serializer_class = viewset.get_serializer_class()

    model = (
        get_model_from_serializer(serializer_class)
        if serializer_class
        else None
    )

    if module:
        slug = module.strip("/").split("/")[-1]
    elif model:
        slug = model._meta.model_name
    else:
        slug = default_slug

    title = humanize(slug)

    return module, slug, title, model


def get_schema_override(viewset):
    """
    Return a safe copy of the schema override defined on the ViewSet.
    """
    return dict(
        getattr(viewset, "schema", {}) or {}
    )


def build_common_schema_meta(
    *,
    override,
    module,
    schema_type,
    slug,
    title,
):
    """
    Metadata shared by CRUD, setting, and tree schemas.

    Existing modules remain compatible because all new keys have
    safe empty defaults.
    """
    return {
        "module": module,
        "type": schema_type,
        "entity": override.get(
            "entity",
            title.replace(" ", ""),
        ),
        "title": override.get("title", title),
        "slug": slug,
        "endpoint": override.get("endpoint"),
        "description": override.get("description"),
        "ui": override.get("ui", {}),
        "tabs": override.get("tabs", []),
        "actions": override.get("actions", []),
        "permissions": override.get(
            "permissions",
            override.get("permission", {}),
        ),
        "workflow": override.get("workflow", {}),
        "layout": override.get("layout", []),
    }


def build_crud_schema(viewset, request):
    serializer_class = viewset.get_serializer_class()

    module, slug, title, model = build_module_meta(
        viewset,
        default_slug="crud",
    )

    auto_fields = inspect_model(model) if model else {}
    serializer_fields = inspect_serializer(serializer_class)

    for name, options in serializer_fields.items():
        if name in auto_fields:
            auto_fields[name].update(options)
        else:
            auto_fields[name] = options

    filterset_fields = (
        getattr(viewset, "filterset_fields", []) or []
    )

    for name in filterset_fields:
        if name in auto_fields:
            auto_fields[name]["filter"] = True

    override = get_schema_override(viewset)
    override_fields = override.get("fields", {})

    fields = deep_merge(
        auto_fields,
        override_fields,
    )

    return {
        **build_common_schema_meta(
            override=override,
            module=module,
            schema_type=SCHEMA_CRUD,
            slug=slug,
            title=title,
        ),
        "fields": fields,
    }


def build_setting_schema(viewset, request):
    serializer_class = getattr(
        viewset,
        "serializer_class",
        None,
    )

    module, slug, title, model = build_module_meta(
        viewset,
        default_slug="setting",
    )

    auto_fields = inspect_model(model) if model else {}

    serializer_fields = (
        inspect_serializer(serializer_class)
        if serializer_class
        else {}
    )

    for name, options in serializer_fields.items():
        if name in auto_fields:
            auto_fields[name].update(options)
        else:
            auto_fields[name] = options

    override = get_schema_override(viewset)
    override_fields = override.get("fields", {})

    fields = deep_merge(
        auto_fields,
        override_fields,
    )

    sections = override.get("sections") or []

    if not sections:
        excluded_fields = {
            "id",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
            "created_by",
            "updated_by",
            "deleted_by",
        }

        editable_fields = [
            name
            for name, options in fields.items()
            if name not in excluded_fields
            and options.get("form", True)
            and not options.get(
                "read_only",
                options.get("readonly", False),
            )
        ]

        sections = [
            {
                "key": "general",
                "title": "General Settings",
                "description": (
                    "Configure general application settings."
                ),
                "columns": 2,
                "fields": editable_fields,
            }
        ]

    return {
        **build_common_schema_meta(
            override=override,
            module=module,
            schema_type=SCHEMA_SETTING,
            slug=slug,
            title=title,
        ),
        "sections": sections,
        "fields": fields,
    }


def build_tree_schema(viewset, request):
    module, slug, title, _model = build_module_meta(
        viewset,
        default_slug="tree",
    )

    override = get_schema_override(viewset)

    return {
        **build_common_schema_meta(
            override=override,
            module=module,
            schema_type=SCHEMA_TREE,
            slug=slug,
            title=title,
        ),
        "save_endpoint": override.get("save_endpoint"),
        "query": override.get("query", {}),
        "nodes": override.get("nodes", {}),
    }


SCHEMA_BUILDERS = {
    SCHEMA_CRUD: build_crud_schema,
    SCHEMA_SETTING: build_setting_schema,
    SCHEMA_TREE: build_tree_schema,
}


def build_ui_schema(viewset, request):
    schema_type = getattr(
        viewset,
        "schema_type",
        SCHEMA_CRUD,
    )

    builder = SCHEMA_BUILDERS.get(schema_type)

    if builder is None:
        raise ValueError(
            f"Unsupported schema_type: {schema_type}"
        )

    return builder(viewset, request)