from .seed_widgets import seed_widgets
from .seed_apps import seed_favorite_apps
from .seed_menus import seed_favorite_menus
from .seed_layout import seed_default_layout


class DashboardSeeder:

    @staticmethod
    def seed_widgets():
        return seed_widgets()

    @staticmethod
    def seed_favorite_apps():
        return seed_favorite_apps()

    @staticmethod
    def seed_favorite_menus():
        return seed_favorite_menus()

    @staticmethod
    def seed_default_layout():
        return seed_default_layout()