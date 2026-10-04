from apps.framework.lookup.views import BaseLookupView


class AllowanceTemplateLineLookupView(BaseLookupView):
    lookup_name = "allowance-template-lines"

    def get(self, request, pk=None, *args, **kwargs):
        return super().get(
            request, lookup_name=self.lookup_name, pk=pk, *args, **kwargs,
        )
