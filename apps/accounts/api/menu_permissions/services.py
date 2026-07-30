from apps.accounts.models import Menu, Role, RoleMenuPermission


class MenuPermissionService:
    @staticmethod
    def get_tree(role_id):
        allowed_menu_ids = set(
            RoleMenuPermission.objects.filter(
                role_id=role_id,
                can_view=True,
                is_deleted=False,
            ).values_list("menu_id", flat=True)
        )

        menus = list(
            Menu.objects.filter(
                is_deleted=False,
                is_active=True,
            ).order_by("sort_order", "title")
        )

        by_parent = {}
        for menu in menus:
            by_parent.setdefault(menu.parent_id, []).append(menu)

        def build(parent_id=None):
            items = []

            for menu in by_parent.get(parent_id, []):
                items.append({
                    "id": menu.id,
                    "code": menu.code,
                    "title": menu.title,
                    "route": menu.route,
                    "icon": menu.icon,
                    "module": menu.module,
                    "is_group": menu.is_group,
                    "checked": menu.id in allowed_menu_ids,
                    "children": build(menu.id),
                })

            return items

        return build(None)

    @staticmethod
    def save(role_id, menu_ids):
        role = Role.objects.get(id=role_id)

        RoleMenuPermission.objects.filter(role=role).delete()

        items = [
            RoleMenuPermission(
                role=role,
                menu_id=menu_id,
                can_view=True,
            )
            for menu_id in menu_ids
        ]

        RoleMenuPermission.objects.bulk_create(items)

        return {
            "role": role.id,
            "saved": len(items),
        }