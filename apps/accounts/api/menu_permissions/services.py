from apps.accounts.models import (
    Menu,
    MenuVisibilityRule,
    Role,
    RoleMenuPermission,
)


# Pilihan syarat, dikirim ke frontend supaya labelnya satu sumber.
RULE_OPTIONS = [
    {"value": value, "label": label}
    for value, label in MenuVisibilityRule.choices
]


class MenuPermissionService:
    @staticmethod
    def get_tree(role_id):
        rows = list(
            RoleMenuPermission.objects.filter(
                role_id=role_id,
                can_view=True,
                is_deleted=False,
            ).values_list("menu_id", "visibility_rule")
        )

        allowed_menu_ids = {menu_id for menu_id, _rule in rows}

        # Syarat pola kerja per menu, ikut dikirim supaya layarnya bisa
        # menampilkan **dan mengubahnya** — tanpa ini kolomnya cuma bisa
        # diisi lewat seed, dan itu sama saja dengan hardcode.
        rules = {
            menu_id: rule or str(MenuVisibilityRule.ALWAYS)
            for menu_id, rule in rows
        }

        menus = list(
            Menu.objects.filter(
                is_deleted=False,
                is_active=True,
            ).order_by("sort_order", "title")
        )

        by_parent = {}
        for menu in menus:
            by_parent.setdefault(menu.parent_id, []).append(menu)

        # Judul grup diberi nama modulnya. Tanpa itu daftarnya memuat dua
        # "Masters" dan dua "Reports" dari modul berbeda, berjajar tanpa
        # apa pun yang membedakan — dan orang mencentang yang salah.
        module_labels = {
            "hr": "HR",
            "payroll": "Payroll",
            "workflow": "Workflow",
            "scm": "Supply Chain",
            "finance": "Finance",
            "administration": "Administration",
        }

        def title_of(menu):
            if not menu.is_group or not menu.module:
                return menu.title

            label = module_labels.get(menu.module, menu.module.title())

            return f"{label} — {menu.title}"

        def build(parent_id=None):
            items = []

            for menu in by_parent.get(parent_id, []):
                items.append({
                    "id": menu.id,
                    "code": menu.code,
                    "title": title_of(menu),
                    "route": menu.route,
                    "icon": menu.icon,
                    "module": menu.module,
                    "is_group": menu.is_group,
                    "checked": menu.id in allowed_menu_ids,
                    "rule": rules.get(
                        menu.id,
                        str(MenuVisibilityRule.ALWAYS),
                    ),
                    # Menu grup tidak punya rute, jadi syarat pola kerja
                    # tidak berlaku untuknya — dan menawarkannya cuma
                    # membuat orang mengira grupnya bisa dikondisikan.
                    "rule_options": [] if menu.is_group else RULE_OPTIONS,
                    "children": build(menu.id),
                })

            return items

        return build(None)

    @staticmethod
    def save(role_id, menu_ids, rules=None):
        role = Role.objects.get(id=role_id)

        RoleMenuPermission.objects.filter(role=role).delete()

        # Kunci dict dari JSON selalu string; id menu-nya integer.
        # Tanpa penyeragaman ini syaratnya tersimpan diam-diam sebagai
        # bawaan, dan yang mengaturnya tidak pernah tahu.
        by_menu = {
            int(key): value
            for key, value in (rules or {}).items()
            if str(key).lstrip("-").isdigit()
        }

        items = [
            RoleMenuPermission(
                role=role,
                menu_id=menu_id,
                can_view=True,
                visibility_rule=by_menu.get(
                    menu_id,
                    MenuVisibilityRule.ALWAYS,
                ),
            )
            for menu_id in menu_ids
        ]

        RoleMenuPermission.objects.bulk_create(items)

        return {
            "role": role.id,
            "saved": len(items),
        }