from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    label = "finance"
    verbose_name = "Finance"

    def ready(self):
        """
        Mendaftarkan lookup dan penyambung alur.

        **Keduanya wajib di-import di sini, dan lupa melakukannya gagal
        diam-diam** — dua kegagalan berbeda yang sama-sama tidak
        berbunyi:

        * Lookup yang tidak terdaftar membuat endpoint dropdown-nya 404,
          dan dropdown yang 404 tampil sebagai daftar kosong tanpa satu
          pun pesan.
        * Handler alur yang tidak terdaftar membuat tombol Approve di
          kotak masuk tetap jalan, tapi status jurnalnya **tidak ikut
          berpindah**.

        Pola yang sama dengan `HrConfig.ready()`.
        """
        from apps.finance.api import lookup  # noqa: F401
        from apps.finance import workflow_handlers  # noqa: F401
