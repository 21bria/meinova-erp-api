"""
Baris master widget beranda, diisi dari katalog di kode.

Sumber kebenarannya `apps/administration/api/dashboard/widget_catalog.py`
— `component` menunjuk komponen Vue yang memang ada di repo frontend,
dan baris database tidak bisa mengarang komponen. Tabelnya tetap diisi
karena `UserDashboardLayout.widget` sebuah FK.
"""

from apps.administration.models import DashboardWidget, UserDashboardLayout

from apps.administration.api.dashboard.widget_catalog import (
    HOME_WIDGETS,
    OBSOLETE_CODES,
)


def seed_widgets():
    created = 0
    updated = 0

    for widget in HOME_WIDGETS:
        _, is_created = DashboardWidget.objects.update_or_create(
            code=widget["code"],
            defaults={
                "title": widget["title"],
                "description": widget["description"],
                "component": widget["component"],
                "module": "core",
                "default_width": widget["span"],
                "default_height": 1,
                "is_active": True,
                "is_deleted": False,
            },
        )

        created += int(is_created)
        updated += int(not is_created)

    return {
        "created": created,
        "updated": updated,
        "retired": _retire_obsolete(),
    }


def _retire_obsolete() -> int:
    """
    Widget sisa rancangan awal (`executive_insight`, `pending_approvals`,
    `favorite_apps`): `component`-nya kosong dan tidak satu pun pernah
    punya komponen di frontend.

    **Hard delete**, termasuk baris susunan pengguna yang menunjuknya.
    Baris bertanda terhapus tetap menempati kunik uniknya, dan susunan
    yang memuat widget tanpa komponen merender kotak kosong yang tidak
    bisa dihapus siapa pun dari layar.
    """
    widgets = DashboardWidget.objects.filter(code__in=OBSOLETE_CODES)

    if not widgets.exists():
        return 0

    UserDashboardLayout.objects.filter(widget__in=widgets).delete()

    removed, _ = widgets.delete()

    return removed
