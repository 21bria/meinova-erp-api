from apps.framework.views.setting import BaseSettingAPIView
from apps.hr.models import EmployeeReminderPolicy

from .serializers import EmployeeReminderPolicySerializer


class EmployeeReminderPolicyView(BaseSettingAPIView):
    """
    Ambang pengingat tanggal kepegawaian.

    Layar setting, bukan CRUD: yang berlaku selalu satu baris per
    tenant. Daftar kebijakan yang bisa ditambah-tambah cuma memunculkan
    pertanyaan "yang mana yang dipakai" tanpa ada jawabannya.
    """

    serializer_class = EmployeeReminderPolicySerializer

    framework_module = "hr/reminder-policy"
    schema_type = "setting"

    schema = {
        "title": "Reminder Policy",
        "description": (
            "Berapa hari sebelum tanggal kepegawaian pengingatnya "
            "muncul di dashboard HR."
        ),
        "endpoint": "/api/hr/reminder-policy/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
        "sections": [
            {
                "title": "Probation & Contract",
                "fields": [
                    "probation_enabled",
                    "probation_lead_days",
                    "contract_enabled",
                    "contract_lead_days",
                ],
            },
            {
                "title": "Personal Dates",
                "fields": [
                    "birthday_enabled",
                    "birthday_lead_days",
                    "anniversary_enabled",
                    "anniversary_lead_days",
                ],
            },
            {
                "title": "Recipients",
                "fields": [
                    "notify_hr",
                    "notify_employee",
                ],
            },
            {
                "title": "Behaviour",
                "fields": [
                    "keep_overdue_days",
                    # Tonggak email. Ditaruh di sini, bukan di
                    # "Recipients": yang diatur bukan siapa yang
                    # menerima melainkan seberapa sering — belnya tetap
                    # jadi hitung mundur harian, emailnya hanya pada
                    # tonggak. Siapa penerimanya diatur di layar
                    # Notification Rules.
                    "email_milestones",
                ],
            },
        ],
    }

    def get_object(self):
        return EmployeeReminderPolicy.resolve()
