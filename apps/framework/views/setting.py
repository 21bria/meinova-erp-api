from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.framework.introspection import build_ui_schema
from apps.framework.views.ui_schema import UISchemaMixin

class BaseSettingAPIView(UISchemaMixin, APIView):
    schema_type = "setting"
    permission_classes = [IsAuthenticated]

    framework_module = None
    serializer_class = None
    ui_schema = {}

    def get_object(self):
        raise NotImplementedError

    def get(self, request):
        obj = self.get_object()
        serializer = self.serializer_class(obj)
        return Response(serializer.data)

    def patch(self, request):
        obj = self.get_object()
        serializer = self.serializer_class(
            obj,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def ui_schema_view(self, request):
        return Response(build_ui_schema(self, request))