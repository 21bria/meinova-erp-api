from django.contrib import admin
from django.urls import path,include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/accounts/", include("apps.accounts.api.urls")),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    path("api/framework/", include("apps.framework.urls")),

    # Administration
    path("api/administration/", include("apps.administration.api.urls")),

    # Apps Hr
    path("api/hr/", include("apps.hr.api.urls")),
    # Apps Payroll
    path("api/payroll/", include("apps.payroll.api.urls")),

]
