from django.urls import path

from .views import PasswordPolicyViewSet

urlpatterns = [
    path("", PasswordPolicyViewSet.as_view(), name="password-policy"),
]