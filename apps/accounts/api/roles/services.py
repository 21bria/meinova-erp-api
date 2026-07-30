from apps.accounts.models import Role

class RoleService:
    @staticmethod
    def list():
        return (
            Role.objects
            .prefetch_related("permissions")
            .filter(is_deleted=False)
            .order_by("name")
        )