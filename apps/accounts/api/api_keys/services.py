from apps.accounts.models import APIKey


class APIKeyService:
    @staticmethod
    def list():
        return (
            APIKey.objects
            .select_related("user")
            .filter(is_deleted=False)
            .order_by("name")
        )