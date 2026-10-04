"""
Pohon izin per model untuk satu role.

Ini layar yang membuat penjagaan `ModelPermission` bisa diatur tanpa
rilis kode: 708 baris `auth.Permission` dikelompokkan jadi app -> model
-> empat kata kerja, lalu dicentang.

**Dikelompokkan, bukan didaftar rata.** 708 kotak centang dalam satu
daftar tidak bisa dipakai siapa pun; yang dicari orang selalu "modul
apa" lebih dulu, baru "boleh apa".
"""

from __future__ import annotations

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role


# Urutan kata kerja mengikuti alur pikir orang: lihat -> tambah ->
# ubah -> hapus, bukan urutan abjad `add/change/delete/view`.
VERB_ORDER = ["view", "add", "change", "delete"]

VERB_LABELS = {
    "view": "View",
    "add": "Create",
    "change": "Edit",
    "delete": "Delete",
}

# Nama app yang enak dibaca. App yang tidak terdaftar memakai namanya
# sendiri — daftar ini pelengkap, bukan penyaring.
APP_LABELS = {
    "accounts": "Security",
    "administration": "Administration",
    "assets": "Assets",
    "core": "Core",
    "finance": "Finance",
    "framework": "Framework",
    "hr": "Human Resources",
    "imports": "Imports",
    "payroll": "Payroll",
    "reports": "Reports",
    "scm": "Supply Chain",
    "tenants": "Tenants",
    "uploads": "Uploads",
    "workflow": "Workflow",
}

# App infrastruktur Django yang tidak pernah diatur lewat layar ini.
HIDDEN_APPS = {
    "admin",
    "auth",
    "contenttypes",
    "sessions",
}


class RolePermissionService:
    @staticmethod
    def get_tree(role_id) -> list[dict]:
        if not role_id:
            return []

        granted = set(
            Role.objects
            .filter(pk=role_id)
            .values_list("permissions__id", flat=True)
        )

        content_types = {
            row.pk: row
            for row in ContentType.objects.all()
        }

        permissions = (
            Permission.objects
            .select_related("content_type")
            .order_by("content_type__app_label", "content_type__model", "codename")
        )

        # app_label -> model -> [permission]
        grouped: dict[str, dict[str, list[Permission]]] = {}

        for permission in permissions:
            content_type = content_types.get(permission.content_type_id)

            if content_type is None or content_type.app_label in HIDDEN_APPS:
                continue

            grouped.setdefault(content_type.app_label, {}).setdefault(
                content_type.model, []
            ).append(permission)

        tree = []

        for app_label in sorted(grouped):
            models = []

            for model in sorted(grouped[app_label]):
                rows = grouped[app_label][model]

                children = [
                    {
                        "id": permission.pk,
                        "label": RolePermissionService._verb_label(permission),
                        "code": permission.codename,
                        "checked": permission.pk in granted,
                    }
                    for permission in sorted(
                        rows,
                        key=lambda item: RolePermissionService._verb_rank(item),
                    )
                ]

                models.append({
                    # Simpul model bukan izin; id-nya sengaja string
                    # supaya tidak pernah tertukar dengan id Permission
                    # saat daftar centang dikumpulkan.
                    "id": f"model:{app_label}.{model}",
                    "label": RolePermissionService._model_label(
                        content_types, app_label, model
                    ),
                    "is_group": True,
                    "checked": all(child["checked"] for child in children),
                    "children": children,
                })

            tree.append({
                "id": f"app:{app_label}",
                "label": APP_LABELS.get(app_label, app_label.title()),
                "is_group": True,
                "checked": all(item["checked"] for item in models),
                "children": models,
            })

        return tree

    @staticmethod
    def _verb_rank(permission: Permission) -> tuple[int, str]:
        verb = permission.codename.split("_", 1)[0]

        return (
            VERB_ORDER.index(verb) if verb in VERB_ORDER else len(VERB_ORDER),
            permission.codename,
        )

    @staticmethod
    def _verb_label(permission: Permission) -> str:
        verb, _, _rest = permission.codename.partition("_")

        if verb in VERB_LABELS:
            return VERB_LABELS[verb]

        # Izin kustom (mis. `can_approve_payroll`) memakai nama aslinya —
        # menebak labelnya justru menyembunyikan apa yang sebenarnya
        # diberikan.
        return permission.name

    @staticmethod
    def _model_label(content_types, app_label, model) -> str:
        for row in content_types.values():
            if row.app_label == app_label and row.model == model:
                target = row.model_class()

                if target is not None:
                    return str(target._meta.verbose_name).title()

        return model.replace("_", " ").title()

    @staticmethod
    def save(role_id, permission_ids) -> dict:
        role = Role.objects.get(pk=role_id)

        # Simpul app/model ikut terkirim dari pohon; yang bukan angka
        # dilewati, bukan ditolak — menolaknya menggagalkan seluruh
        # penyimpanan gara-gara simpul yang memang bukan izin.
        ids = []

        for value in permission_ids or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue

        permissions = list(Permission.objects.filter(pk__in=ids))

        role.permissions.set(permissions)

        return {
            "role": role.pk,
            "saved": len(permissions),
        }
