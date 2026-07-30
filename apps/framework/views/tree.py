from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.framework.introspection import build_ui_schema


class BaseTreeAPIView(APIView):
    schema_type = "tree"
    permission_classes = [IsAuthenticated]

    framework_module = None
    serializer_class = None
    schema = {}

    def get_object(self):
        raise NotImplementedError

    def get_schema_response(self, request):
        return Response(build_ui_schema(self, request))