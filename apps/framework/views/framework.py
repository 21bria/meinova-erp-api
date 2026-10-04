from django.http import Http404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.framework.introspection import build_ui_schema
from apps.framework.views.dashboard import BaseDashboardAPIView
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.tree import BaseTreeAPIView
from apps.framework.views.setting import BaseSettingAPIView

FRAMEWORK_BASES = (
    BaseMasterViewSet,
    BaseTreeAPIView,
    BaseSettingAPIView,
    BaseDashboardAPIView,
)

def _all_subclasses(cls):
    subclasses = []
    for subclass in cls.__subclasses__():
        subclasses.append(subclass)
        subclasses.extend(_all_subclasses(subclass))
    return subclasses


@api_view(["GET"])
@permission_classes([AllowAny])
def framework_schema_view(request, module):
    framework_classes = []
    
    for base in FRAMEWORK_BASES:
        framework_classes.extend(_all_subclasses(base))

    for view_class in framework_classes:
        if getattr(view_class, "framework_module", None) == module:
            view = view_class()
            view.request = request
            view.format_kwarg = None
            view.kwargs = {}

            if hasattr(view, "action"):
                view.action = "ui_schema_view"

            return Response(build_ui_schema(view, request))

    raise Http404(f"Framework module '{module}' not found.")