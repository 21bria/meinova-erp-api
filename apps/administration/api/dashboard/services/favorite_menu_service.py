from apps.administration.models import FavoriteMenu


class FavoriteMenuService:
    @staticmethod
    def get_favorites(user):
        return FavoriteMenu.objects.filter(
            user=user,
        ).order_by("position")

    @staticmethod
    def delete_favorite(user, menu_code):
        return FavoriteMenu.objects.filter(
            user=user,
            menu_code=menu_code,
        ).delete()