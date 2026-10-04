from django.urls import path

from .views import EmployeeReminderPolicyView

urlpatterns = [
    path("", EmployeeReminderPolicyView.as_view(), name="hr-reminder-policy"),
]
