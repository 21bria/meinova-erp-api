from apps.accounts.models import UserSession


class UserSessionService:
    @staticmethod
    def list():
        return (
            UserSession.objects
            .select_related("user")
            .filter(is_deleted=False)
            .order_by("-login_at")
        )

    @staticmethod
    def logout_session(session):
        session.is_active_session = False
        session.save(update_fields=["is_active_session", "updated_at"])
        return session

    @staticmethod
    def logout_user_sessions(user_id):
        return UserSession.objects.filter(
            user_id=user_id,
            is_active_session=True,
            is_deleted=False,
        ).update(is_active_session=False)