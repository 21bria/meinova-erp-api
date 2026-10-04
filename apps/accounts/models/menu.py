from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class Menu(BaseModel):
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    code = models.CharField(max_length=100)
    title = models.CharField(max_length=150)

    route = models.CharField(max_length=255, blank=True)
    icon = models.CharField(max_length=100, blank=True)
    module = models.CharField(max_length=100, blank=True)

    sort_order = models.PositiveIntegerField(default=0)
    is_group = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_menu"
        ordering = ["sort_order", "title"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_accounts_menu_code",
            ),
        ]

    def __str__(self):
        return self.title


class MenuVisibilityRule(models.TextChoices):
    """
    Syarat tambahan di atas centang `can_view`.

    Ada menu yang benar untuk sebuah role tapi **tidak untuk semua
    pemegangnya**. Travel Request adalah dokumen kepulangan dari site:
    role `EMPLOYEE` memang boleh mengajukannya, tapi pegawai kantor
    pusat tidak punya kepulangan untuk diajukan. Kebalikannya akan
    berlaku untuk Site Visit nanti — kunjungan dinas justru milik orang
    kantor.

    Dua keluarga syarat, dan **arti setiap nilai tidak bergantung pada
    rutenya** (POLICY-1A):

    * pola kerja — `roster_only` / `non_roster_only`: keanggotaan roster
      pegawai (`roster_crew` atau `roster_policy` pada penempatannya);
    * Feature Applicability — `field_break` / `business_trip`: penanda
      Employee Group pegawai (`apps/hr/applicability.py`), sumber yang
      sama dengan yang ditegakkan API Travel Request / Business Trip.
      Nilainya sama dengan anggota `HRFeature`-nya.

    Travel Request memakai `field_break`, Business Trip `business_trip`,
    Roster Schedule `roster_only` (`seed_menus.MENU_RULES`).

    Disimpan di baris `RoleMenuPermission`, **bukan di settings**:
    settings berarti tetap perlu rilis untuk mengubahnya, sementara
    seluruh pengaturan menu di sistem ini sudah per tenant dan bisa
    disunting dari layar Menu Permissions.
    """

    ALWAYS = "always", "Always"
    ROSTER_ONLY = "roster_only", "Roster Employees Only"
    NON_ROSTER_ONLY = "non_roster_only", "Non-Roster Employees Only"
    FIELD_BREAK = "field_break", "Field Break Applicable (Employee Group)"
    BUSINESS_TRIP = (
        "business_trip",
        "Business Trip Applicable (Employee Group)",
    )


class RoleMenuPermission(BaseModel):
    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.CASCADE,
        related_name="menu_permissions",
    )

    menu = models.ForeignKey(
        Menu,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )

    can_view = models.BooleanField(default=True)

    visibility_rule = models.CharField(
        max_length=20,
        choices=MenuVisibilityRule.choices,
        default=MenuVisibilityRule.ALWAYS,
        help_text=(
            "Syarat tambahan di atas centang ini. Roster/Non-Roster "
            "dibaca dari Roster Crew atau Roster Policy pada "
            "penempatannya; Field Break/Business Trip dari Employee "
            "Group pegawainya."
        ),
    )

    class Meta:
        db_table = "accounts_role_menu_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "menu"],
                name="uniq_accounts_role_menu_permission",
            ),
        ]

    def __str__(self):
        return f"{self.role} - {self.menu}"