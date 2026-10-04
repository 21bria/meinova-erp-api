"""
Cakupan dokumen pergerakan yang punya dua sisi (asal dan tujuan).

`DataScopeService.filter` hanya menerima satu jalur per jenis scope, jadi
dokumen lintas lokasi (Return, Transfer) di-scope dengan menggabungkan
beberapa pemanggilan — **tanpa mengubah `DataScopeService`** (pola O-3,
`docs/claude/assets.md` §17).

Viewset menyatakan:

* `scope_sides` — `{nama sisi: peta data_scope}`;
* `visible_sides` — sisi yang memberi hak **lihat** (list, detail, export,
  dan aksi yang tidak disebut di `action_sides`);
* `action_sides` — `{aksi: sisi}` untuk aksi yang wewenangnya lebih
  sempit daripada lihat (mis. `complete` hanya sisi tujuan).

Lihat ≠ wewenang aksi: pengguna yang bisa melihat dokumen dari sisi tujuan
tidak otomatis boleh mengajukannya.
"""

from apps.accounts.permissions import required_scope_permission
from apps.accounts.scoping import DataScopeService
from apps.framework.views.master import BaseMasterViewSet


class SideScopedViewSetMixin:
    scope_sides: dict[str, dict] = {}
    visible_sides: tuple[str, ...] = ()
    action_sides: dict[str, tuple[str, ...]] = {}

    def sides_for_action(self) -> tuple[str, ...]:
        return self.action_sides.get(
            getattr(self, "action", None) or "",
            self.visible_sides,
        )

    def filter_queryset(self, queryset):
        # Persis yang dipanggil `BaseMasterViewSet.filter_queryset` sebelum
        # menerapkan cakupannya sendiri — filter backend DRF saja.
        queryset = super(BaseMasterViewSet, self).filter_queryset(queryset)

        request = getattr(self, "request", None)

        if request is None:
            return queryset

        permission = required_scope_permission(self)
        user = getattr(request, "user", None)

        scoped = None

        for side in self.sides_for_action():
            part = DataScopeService.filter(
                queryset,
                self.scope_sides[side],
                user,
                required_permission=permission,
            )

            if part is queryset:
                # Tanpa batasan di sisi mana pun = tanpa batasan.
                scoped = queryset
                break

            scoped = part if scoped is None else (scoped | part)

        if scoped is None:
            scoped = queryset.none()
        elif scoped is not queryset:
            scoped = scoped.distinct()

        return self._widen_for_workflow_participants(
            base=queryset,
            scoped=scoped,
            request=request,
        )
