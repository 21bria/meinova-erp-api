from apps.accounts.models import PasswordPolicy


class PasswordPolicyService:
    @staticmethod
    def list():
        return PasswordPolicy.objects.filter(
            is_deleted=False,
        ).order_by("name")