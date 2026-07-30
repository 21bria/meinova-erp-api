# apps/core/framework/urls.py
from django.urls import path
from apps.framework.views.framework import framework_schema_view

urlpatterns = [
    path("schema/<path:module>/", framework_schema_view, name="framework-schema"),
]