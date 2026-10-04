from apps.framework.builders import ui


# Nama key harus `import` / `export` / `bulk_delete` — itu yang dibaca
# generator frontend. Sebelumnya memakai `import_data`/`export_data`
# sehingga tombolnya tidak pernah muncul di menu Actions.
ATTENDANCE_UI = {
    **ui.workspace(
        title="Attendance",
        description=(
            "Manage employee attendance across "
            "companies, branches, and locations."
        ),
        size="full",
        columns=3,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),

    # `import` adalah keyword Python, tidak bisa jadi kwarg.
    "import": True,
}
