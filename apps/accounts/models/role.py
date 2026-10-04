from django.contrib.auth.models import Permission
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


# `DataScopeMode` **dihapus di gelombang C.**
#
# Ia menyatakan dari mana cakupan seorang pemegang role dihitung, dan
# arti `explicit`-nya yang paling menentukan bentuk penggantinya: pada
# `Role`, "ditentukan sendiri, tanpa satu pun baris" berarti **tanpa
# batasan** — dua keadaan berlawanan dinyatakan sama, dan yang salah di
# antara keduanya membuka seluruh tenant.
#
# Penggantinya `AuthorityMode` di `role_assignment.py`, dan ia sengaja
# **bukan** salinan: `PLACEMENT` menggantikan `own` (kata "own" sudah
# dipakai untuk arti lain), `UNRESTRICTED` menggantikan `all`, dan
# `EXPLICIT` tanpa baris berarti **tanpa kewenangan**. Arah kegagalannya
# dibalik dengan sadar.
#
# `DataScopeLevel` di bawah **tetap ada**: ia tidak pernah jadi milik
# aturan lama, dan `RoleAssignment.authority_level` memakainya.


class DataScopeLevel(models.TextChoices):
    """Tingkat organisasi yang dipakai mode `OWN`."""

    COMPANY = "company", "Company"
    BRANCH = "branch", "Branch"
    LOCATION = "location", "Location"
    DIVISION = "division", "Division"
    DEPARTMENT = "department", "Department"
    SECTION = "section", "Section"
    COST_CENTER = "cost_center", "Cost Center"


class Role(BaseModel):
    code = models.CharField(max_length=50)

    name = models.CharField(max_length=150)

    description = models.TextField(blank=True)

    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="roles",
    )

    # **Tidak ada kolom cakupan di sini, dan itu inti arsitekturnya.**
    #
    # `Role` menjawab WHAT — izin apa yang dipegang. WHERE milik
    # pasangan (orang, role), disimpan di `RoleAssignment`. Selama
    # keduanya tinggal di sini, menyunting satu role menggeser akses
    # setiap pemegangnya sekaligus, dan "Hesti mengurus JKT-HO, Eko
    # mengurus SAGEA-MINE, keduanya HR-ADMIN" memaksa dua role.

    class Meta:
        db_table = "accounts_role"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_accounts_role_code",
            ),
        ]

    # `clean()` tidak lagi memeriksa cakupan.
    #
    # Yang dulu diperiksanya — mode "ikut penempatan" tanpa tingkat
    # organisasi — masih keadaan yang berbahaya: cakupannya kosong dan
    # pemegangnya kehilangan seluruh data tanpa satu pun pesan.
    # Pemeriksaannya **tidak hilang**, ia pindah ke tempat keadaannya
    # sekarang tinggal: validasi penugasan di
    # `apps.accounts.api.user_roles`, dan `audit_authority_hygiene`
    # untuk baris yang telanjur ada.

    def __str__(self):
        return self.name