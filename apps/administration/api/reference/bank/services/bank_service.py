from apps.administration.models import Bank, BankBranch


class BankService:
    @staticmethod
    def list():
        return Bank.objects.select_related("country").order_by("name")


class BankBranchService:
    @staticmethod
    def list():
        return BankBranch.objects.select_related(
            "bank",
            "city",
            "city__province",
        ).order_by("bank__name", "name")