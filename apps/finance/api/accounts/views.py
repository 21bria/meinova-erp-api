from django.db.models import Count, Q

from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.finance.models import Account
from apps.finance.services import AccountService

from .schema import ACCOUNT_SCHEMA
from .serializers import AccountSerializer


class AccountViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Chart of Accounts.

    `ServiceWriteMixin` **wajib** di sini, bukan opsional: tanpa itu
    jalur tulisnya `serializer.save()` bawaan DRF, dan `path`/`level`
    yang ditulis `AccountService.after_create` tidak pernah jalan lewat
    API — laporan berhierarki lalu kehilangan setiap akun yang dibuat
    dari layar, tanpa satu pun pesan.
    """

    serializer_class = AccountSerializer
    service_class = AccountService

    framework_module = "finance/chart-of-accounts"
    schema = ACCOUNT_SCHEMA

    # Bagan akun milik satu perusahaan, jadi cakupannya lewat kolom
    # company. Tidak lebih dalam dari itu: akun bukan dokumen — ia tidak
    # punya site maupun departemen, dan menyaringnya ke sana akan
    # mengosongkan dropdown akun untuk setiap admin site.
    data_scope = {"company": "company"}

    search_fields = ["code", "name", "description"]

    filterset_fields = [
        "company",
        "parent",
        "account_type",
        "account_category",
        "posting_allowed",
        "control_account",
        "reconciliation_required",
        "is_active",
    ]

    ordering_fields = ["code", "name", "account_type", "level", "sort_order"]
    ordering = ["company_id", "code"]

    def get_queryset(self):
        return (
            Account.objects
            .filter(is_deleted=False)
            .select_related("company", "parent", "default_currency")
            # Dihitung sekali di database. Tanpa anotasi ini,
            # `has_entries` di serializer menembak satu `EXISTS` per
            # baris — dua puluh query tambahan untuk satu halaman.
            .annotate(
                journal_line_count=Count(
                    "journal_lines",
                    filter=Q(journal_lines__is_deleted=False),
                ),
            )
        )

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        """
        Bagan akun sebagai pohon.

        Lewat `filter_queryset()`, jadi cakupan data berlaku sama persis
        dengan daftarnya. Menyusun pohon dari queryset yang tidak
        tersaring adalah cara membocorkan seluruh bagan akun lewat satu
        endpoint yang terlihat seperti sekadar tampilan lain.
        """
        queryset = self.filter_queryset(self.get_queryset())

        return success_response(
            data=AccountService.tree(queryset),
            message="Chart of accounts tree.",
        )
