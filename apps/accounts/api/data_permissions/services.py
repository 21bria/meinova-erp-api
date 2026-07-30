from apps.accounts.models import Role, RoleDataPermission
from apps.administration.models import (
    Company,
    Branch,
    Site,
    Division,
    Department,
    Section,
    CostCenter,
)


RESOURCE_MODELS = {
    "company": Company,
    "branch": Branch,
    "site": Site,
    "division": Division,
    "department": Department,
    "section": Section,
    "cost_center": CostCenter,
}


class DataPermissionService:
    @staticmethod
    def get_tree(role_id):
        selected = {}

        permissions = RoleDataPermission.objects.filter(
            role_id=role_id,
            is_deleted=False,
        )

        for permission in permissions:
            selected.setdefault(permission.resource_type, set()).add(
                permission.resource_id
            )

        result = []

        for resource_type, model in RESOURCE_MODELS.items():
            queryset = model.objects.filter(
                is_deleted=False,
                is_active=True,
            ).order_by("name")

            items = [
                {
                    "id": item.id,
                    "title": item.name,
                    "code": getattr(item, "code", ""),
                    "checked": item.id in selected.get(resource_type, set()),
                }
                for item in queryset
            ]

            result.append({
                "resource_type": resource_type,
                "title": resource_type.replace("_", " ").title(),
                "items": items,
            })

        return result

    @staticmethod
    def save(role_id, resources):
        role = Role.objects.get(id=role_id)

        RoleDataPermission.objects.filter(role=role).delete()

        items = []

        for resource_type, ids in resources.items():
            for resource_id in ids:
                items.append(
                    RoleDataPermission(
                        role=role,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        can_view=True,
                    )
                )

        RoleDataPermission.objects.bulk_create(items)

        return {
            "role": role.id,
            "saved": len(items),
        }