from apps.framework.lookup import BaseLookup, register_lookup

from apps.helpcenter.models import HelpCategory


@register_lookup
class HelpCategoryLookup(BaseLookup):
    # Registry lookup memakai nama global lintas domain, jadi
    # namanya diberi awalan `help-` supaya tidak bertabrakan dengan
    # `categories` milik modul lain di kemudian hari.
    name = "help-categories"

    model = HelpCategory

    search_fields = ["code", "name"]

    ordering = ["sort_order", "name"]

    filter_fields = ["module"]
