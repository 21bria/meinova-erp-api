from __future__ import annotations

from typing import Any, Mapping, Sequence


ImportConfig = dict[str, Any]

DEFAULT_JOB_ENDPOINT = "/api/imports/jobs/{jobPublicId}/"
DEFAULT_ERROR_REPORT_ENDPOINT = (
    "/api/imports/jobs/{jobPublicId}/error-report/"
)
DEFAULT_PROFILE_ENDPOINT = "/api/imports/profiles/lookup/"


def column(
    key: str,
    label: str,
    *,
    align: str | None = None,
    width: int | str | None = None,
) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "key": key,
            "label": label,
            "align": align,
            "width": width,
        }.items()
        if v is not None
    }


def options(
    *,
    skip_invalid: bool = True,
    skip_duplicates: bool = True,
    stop_on_error: bool = False,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, bool]:
    return {
        "skip_invalid": skip_invalid,
        "skip_duplicates": skip_duplicates,
        "stop_on_error": stop_on_error,
        "dry_run": dry_run,
        "overwrite": overwrite,
    }


def config(
    *,
    module: str,
    title: str,
    description: str = "",
    back_route: str = "",
    back_label: str = "Back",
    completed_title: str = "",
    completed_description: str = "",
    import_another_label: str = "Import Another File",
    profile_label: str = "Import Profile",
    file_label: str = "CSV File",
    file_accept: str = ".csv,text/csv",
    source_type: str = "csv",
    preview_columns: Sequence[Mapping[str, Any]] | None = None,
    max_file_size_mb: int = 20,
    poll_interval_ms: int = 1500,
    poll_timeout_ms: int = 10 * 60 * 1000,
    profile_endpoint: str | None = None,
    preview_endpoint: str | None = None,
    confirm_endpoint: str | None = None,
    template_endpoint: str | None = None,
    template_label: str = "Download Template",
    job_endpoint: str = DEFAULT_JOB_ENDPOINT,
    error_report_endpoint: str = DEFAULT_ERROR_REPORT_ENDPOINT,
    import_options: Mapping[str, Any] | None = None,
    **extra: Any,
) -> ImportConfig:
    """
    Deklarasi fitur import untuk satu resource.

    Endpoint preview/confirm/profile diturunkan otomatis dari `module`
    supaya konsisten dengan router generik di `apps.imports`.
    """
    normalized_module = str(module or "").strip().strip("/")

    if not normalized_module:
        raise ValueError(
            "importer.config() membutuhkan 'module'.",
        )

    return {
        "enabled": True,
        "module": normalized_module,
        "source_type": source_type,

        "title": title,
        "description": description,

        "completed_title": (
            completed_title
            or f"{title} Completed"
        ),
        "completed_description": (
            completed_description
            or "Records have been processed successfully."
        ),

        "back_label": back_label,
        "back_route": back_route,
        "import_another_label": import_another_label,

        "profile_endpoint": (
            profile_endpoint
            or (
                f"{DEFAULT_PROFILE_ENDPOINT}"
                f"?module={normalized_module}"
            )
        ),
        "profile_label": profile_label,

        "file_label": file_label,
        "file_accept": file_accept,

        "preview_endpoint": (
            preview_endpoint
            or f"/api/imports/{normalized_module}/preview/"
        ),
        "confirm_endpoint": (
            confirm_endpoint
            or f"/api/imports/{normalized_module}/confirm/"
        ),

        "template_endpoint": (
            template_endpoint
            or f"/api/imports/{normalized_module}/template/"
        ),
        "template_label": template_label,

        "job_endpoint": job_endpoint,
        "error_report_endpoint": error_report_endpoint,

        "poll_interval_ms": poll_interval_ms,
        "poll_timeout_ms": poll_timeout_ms,
        "max_file_size_mb": max_file_size_mb,

        "preview_columns": [
            dict(item)
            for item in (preview_columns or ())
        ],

        "options": dict(
            import_options
            if import_options is not None
            else options()
        ),

        **extra,
    }


def none() -> ImportConfig:
    return {
        "enabled": False,
    }
