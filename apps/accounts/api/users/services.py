from django.contrib.auth import get_user_model

User = get_user_model()


class UserService:
    @staticmethod
    def list():
        return User.objects.all().order_by("username")