from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assets"
    verbose_name = "Asset Management"

    def ready(self):
        # Mendaftarkan lookup Asset Management ke registry global.
        # Tanpa ini /api/assets/lookup/asset-categories/ 404, dan dropdown
        # kategori di form aset tampil kosong tanpa error.
        from apps.assets.api.lookup import registry  # noqa: F401

        # Handler penyelesaian alur + rute dokumen. Tanpa ini keputusan
        # dari kotak masuk generik tidak menggerakkan status Assignment/Return/Transfer.
        from apps.assets import workflow_handlers  # noqa: F401
