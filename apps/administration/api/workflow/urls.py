from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.workflow.views.workflow import *

router = DefaultRouter()

router.register("definitions", WorkflowDefinitionViewSet, basename="workflow-definition")
router.register("steps", WorkflowStepViewSet, basename="workflow-step")
router.register("instances", WorkflowInstanceViewSet, basename="workflow-instance")
router.register("approvals", WorkflowApprovalViewSet, basename="workflow-approval")
router.register("delegations", WorkflowDelegationViewSet, basename="workflow-delegation")

urlpatterns = [
    path("", include(router.urls)),
]