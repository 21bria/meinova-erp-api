from __future__ import annotations

from typing import Any

from .model import humanize, inspect_model
from .serializer import inspect_serializer


SCHEMA_CRUD = "crud"
SCHEMA_SETTING = "setting"
SCHEMA_TREE = "tree"
SCHEMA_DASHBOARD = "dashboard"

UPLOAD_FIELD_TYPE = "file"
UPLOAD_WIDGET = "upload"
IMAGE_UPLOAD_WIDGET = "image-upload"
DEFAULT_UPLOAD_ENDPOINT = "/api/uploads/"


def deep_merge(
    base: dict,
    override: dict,
) -> dict:
    result = dict(base)

    for key, value in (override or {}).items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = deep_merge(
                result[key],
                value,
            )
        else:
            result[key] = value

    return result


def get_model_from_serializer(serializer_class):
    meta = getattr(
        serializer_class,
        "Meta",
        None,
    )

    return getattr(
        meta,
        "model",
        None,
    )


def build_module_meta(
    viewset,
    default_slug: str = "module",
):
    module = getattr(
        viewset,
        "framework_module",
        None,
    )

    serializer_class = getattr(
        viewset,
        "serializer_class",
        None,
    )

    if (
        serializer_class is None
        and hasattr(viewset, "get_serializer_class")
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


def get_schema_override(viewset) -> dict:
    return dict(
        getattr(
            viewset,
            "schema",
            {},
        )
        or {}
    )


def is_upload_field(
    name: str,
    options: dict,
) -> bool:
    return bool(
        options.get("type") == UPLOAD_FIELD_TYPE
        or options.get("widget") in {
            UPLOAD_WIDGET,
            IMAGE_UPLOAD_WIDGET,
        }
        or name == "uploaded_file"
    )


def normalize_upload_field(
    name: str,
    options: dict,
) -> dict:
    if not is_upload_field(name, options):
        return options

    normalized = dict(options)

    normalized["type"] = UPLOAD_FIELD_TYPE

    if normalized.get("widget") not in {
        UPLOAD_WIDGET,
        IMAGE_UPLOAD_WIDGET,
    }:
        normalized["widget"] = UPLOAD_WIDGET

    normalized.setdefault(
        "category",
        "attachment",
    )
    normalized.setdefault(
        "public",
        False,
    )
    normalized.setdefault(
        "multiple",
        False,
    )
    normalized.setdefault(
        "preview",
        True,
    )
    normalized.setdefault(
        "download",
        True,
    )
    normalized.setdefault(
        "replace",
        True,
    )
    normalized.setdefault(
        "delete",
        True,
    )
    normalized.setdefault(
        "upload_endpoint",
        DEFAULT_UPLOAD_ENDPOINT,
    )

    normalized["value_mode"] = "id"
    normalized["upload_mode"] = "separate"

    normalized.setdefault(
        "detail_field",
        f"{name}_detail",
    )

    normalized.setdefault(
        "table",
        False,
    )
    normalized.setdefault(
        "filter",
        False,
    )
    normalized.setdefault(
        "search",
        False,
    )
    normalized.setdefault(
        "sortable",
        False,
    )
    normalized.setdefault(
        "export",
        False,
    )

    normalized.pop(
        "lookup_endpoint",
        None,
    )
    normalized.pop(
        "label_key",
        None,
    )
    normalized.pop(
        "value_key",
        None,
    )

    return normalized


def normalize_fields(
    fields: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        name: normalize_upload_field(
            name,
            options,
        )
        for name, options in fields.items()
    }


def normalize_tabs(
    tabs: list[dict],
) -> list[dict]:
    normalized_tabs = []

    for tab in tabs or []:
        normalized_tab = dict(tab)

        tab_fields = normalized_tab.get("fields")

        if isinstance(tab_fields, dict):
            normalized_tab["fields"] = normalize_fields(
                tab_fields,
            )

        normalized_tabs.append(
            normalized_tab,
        )

    return normalized_tabs


def derive_i18n_namespace(module: str | None) -> str:
    """
    `hr/employees` -> `hr.employees`, `references/hr/genders` ->
    `references.hr.genders`.

    Namespace katalog frontend memang selalu bisa dihitung dari
    `framework_module`: keduanya menamai resource yang sama, cuma beda
    pemisah. Menulisnya lagi satu per satu di 180-an schema berarti 180
    kesempatan untuk salah ketik, dan yang salah ketik tidak error —
    modulnya cuma diam-diam tidak pernah ikut diterjemahkan.

    Schema tetap boleh menyetel `i18n.namespace` sendiri kalau memang
    perlu menyimpang; nilai eksplisit selalu menang.
    """
    if not module:
        return ""

    return module.strip("/").replace("/", ".")


def resolve_i18n_meta(
    *,
    override: dict,
    module: str | None,
) -> dict:
    meta = dict(override.get("i18n", {}) or {})

    if not meta.get("namespace"):
        derived = derive_i18n_namespace(module)

        if derived:
            meta["namespace"] = derived

    return meta


def build_common_schema_meta(
    *,
    override: dict,
    module: str | None,
    schema_type: str,
    slug: str,
    title: str,
) -> dict:
    return {
        "module": module,
        "type": schema_type,
        "entity": override.get(
            "entity",
            title.replace(" ", ""),
        ),
        "title": override.get(
            "title",
            title,
        ),
        "slug": slug,
        "endpoint": override.get("endpoint"),
        "description": override.get("description"),
        "ui": override.get("ui", {}),
        "tabs": normalize_tabs(
            override.get("tabs", []),
        ),
        "actions": override.get("actions", []),
        "permissions": override.get(
            "permissions",
            override.get(
                "permission",
                {},
            ),
        ),
        "workflow": override.get(
            "workflow",
            {},
        ),
        "layout": override.get(
            "layout",
            [],
        ),
        # Konfigurasi fitur import; dipakai generator frontend untuk
        # menerbitkan folder import/ pada module terkait.
        "import": override.get(
            "import",
            {},
        ),
        # Namespace katalog terjemahan frontend, mis.
        # `{"namespace": "workflow.steps"}`.
        #
        # Diteruskan apa adanya ke generator, yang memakainya untuk
        # memancarkan `resourceLabel("<ns>.fields.<field>", "<label>")`
        # alih-alih literal. Modul yang tidak menyetelnya mendapat `{}`,
        # dan generator memperlakukan itu sebagai "i18n mati" — keluaran
        # persis seperti sebelumnya.
        #
        # Di sini, bukan di tiap builder, karena keempat jenis schema
        # (crud/setting/tree/dashboard) melewati fungsi ini. Menaruhnya
        # di salah satunya berarti tiga jenis lain diam-diam tidak
        # pernah bisa diterjemahkan.
        "i18n": resolve_i18n_meta(
            override=override,
            module=module,
        ),
    }


def merge_introspection_fields(
    *,
    model_fields: dict,
    serializer_fields: dict,
) -> dict:
    fields = {
        name: dict(options)
        for name, options in model_fields.items()
    }

    for name, serializer_options in serializer_fields.items():
        if name not in fields:
            fields[name] = dict(
                serializer_options,
            )
            continue

        model_options = fields[name]
        model_is_upload = is_upload_field(
            name,
            model_options,
        )

        fields[name].update(
            serializer_options,
        )

        if model_is_upload:
            fields[name]["type"] = UPLOAD_FIELD_TYPE

            if fields[name].get("widget") not in {
                UPLOAD_WIDGET,
                IMAGE_UPLOAD_WIDGET,
            }:
                fields[name]["widget"] = UPLOAD_WIDGET

    return fields


def apply_filterset_fields(
    fields: dict,
    filterset_fields,
) -> None:
    for name in filterset_fields or []:
        if name in fields:
            fields[name]["filter"] = True


def build_crud_schema(
    viewset,
    request,
):
    serializer_class = viewset.get_serializer_class()

    module, slug, title, model = build_module_meta(
        viewset,
        default_slug="crud",
    )

    model_fields = (
        inspect_model(model)
        if model
        else {}
    )

    serializer_fields = inspect_serializer(
        serializer_class,
    )

    auto_fields = merge_introspection_fields(
        model_fields=model_fields,
        serializer_fields=serializer_fields,
    )

    apply_filterset_fields(
        auto_fields,
        getattr(
            viewset,
            "filterset_fields",
            [],
        ),
    )

    override = get_schema_override(
        viewset,
    )

    fields = deep_merge(
        auto_fields,
        override.get(
            "fields",
            {},
        ),
    )

    fields = normalize_fields(
        fields,
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


def build_setting_schema(
    viewset,
    request,
):
    serializer_class = getattr(
        viewset,
        "serializer_class",
        None,
    )

    module, slug, title, model = build_module_meta(
        viewset,
        default_slug="setting",
    )

    model_fields = (
        inspect_model(model)
        if model
        else {}
    )

    serializer_fields = (
        inspect_serializer(serializer_class)
        if serializer_class
        else {}
    )

    auto_fields = merge_introspection_fields(
        model_fields=model_fields,
        serializer_fields=serializer_fields,
    )

    override = get_schema_override(
        viewset,
    )

    fields = deep_merge(
        auto_fields,
        override.get(
            "fields",
            {},
        ),
    )

    fields = normalize_fields(
        fields,
    )

    sections = override.get(
        "sections",
    ) or []

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
            and options.get(
                "form",
                True,
            )
            and not options.get(
                "read_only",
                options.get(
                    "readonly",
                    False,
                ),
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


def build_tree_schema(
    viewset,
    request,
):
    module, slug, title, _model = build_module_meta(
        viewset,
        default_slug="tree",
    )

    override = get_schema_override(
        viewset,
    )

    return {
        **build_common_schema_meta(
            override=override,
            module=module,
            schema_type=SCHEMA_TREE,
            slug=slug,
            title=title,
        ),
        "save_endpoint": override.get(
            "save_endpoint",
        ),
        "query": override.get(
            "query",
            {},
        ),
        "nodes": override.get(
            "nodes",
            {},
        ),
    }


def build_dashboard_schema(
    viewset,
    request,
):
    override = get_schema_override(
        viewset,
    )

    module, slug, title, _model = build_module_meta(
        viewset,
        default_slug="dashboard",
    )

    # `ui-schema/` dilayani subclass yang sengaja mengosongkan
    # `framework_module` (lihat BaseDashboardAPIView.as_schema_view),
    # jadi modulnya diambil dari schema dulu — kalau tidak, respons
    # `ui-schema/` akan kehilangan nama module-nya.
    module = override.get("module") or module

    if module:
        slug = module.strip("/").split("/")[-1]
        title = override.get("label") or humanize(slug)

    return {
        **build_common_schema_meta(
            override=override,
            module=module,
            schema_type=SCHEMA_DASHBOARD,
            slug=slug,
            title=title,
        ),
        "columns": override.get("columns", 12),
        "filters": override.get("filters", []),
        "widgets": override.get("widgets", []),
    }


SCHEMA_BUILDERS = {
    SCHEMA_CRUD: build_crud_schema,
    SCHEMA_SETTING: build_setting_schema,
    SCHEMA_TREE: build_tree_schema,
    SCHEMA_DASHBOARD: build_dashboard_schema,
}


def build_ui_schema(
    viewset,
    request,
):
    schema_type = getattr(
        viewset,
        "schema_type",
        SCHEMA_CRUD,
    )

    builder = SCHEMA_BUILDERS.get(
        schema_type,
    )

    if builder is None:
        raise ValueError(
            f"Unsupported schema_type: {schema_type}"
        )

    return builder(
        viewset,
        request,
    )