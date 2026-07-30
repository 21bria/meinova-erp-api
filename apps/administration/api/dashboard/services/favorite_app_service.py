from apps.administration.models import FavoriteApp


class FavoriteAppService:
    @staticmethod
    def get_favorites(user):
        return FavoriteApp.objects.filter(
            user=user,
        ).order_by("position")

    @staticmethod
    def delete_favorite(user, app_code):
        return FavoriteApp.objects.filter(
            user=user,
            app_code=app_code,
        ).delete()