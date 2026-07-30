from apps.framework.views.master import BaseMasterViewSet


class BaseReferenceViewSet(BaseMasterViewSet):
    ordering = ["sort_order", "name"]
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]