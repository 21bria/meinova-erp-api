from apps.framework.lookup.views import BaseLookupView


class PayrollPeriodLookupView(BaseLookupView):
    lookup_name = "payroll-periods"

    def get(self, request, pk=None, *args, **kwargs):
        return super().get(
            request, lookup_name=self.lookup_name, pk=pk, *args, **kwargs,
        )
