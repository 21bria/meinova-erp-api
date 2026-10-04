from apps.framework.lookup.views import BaseLookupView


class DeductionTemplateLineLookupView(BaseLookupView):
    lookup_name = "deduction-template-lines"

    def get(self, request, pk=None, *args, **kwargs):
        return super().get(
            request, lookup_name=self.lookup_name, pk=pk, *args, **kwargs,
        )
