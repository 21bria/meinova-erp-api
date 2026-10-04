from apps.framework import list_period


class ServiceWriteMixin:
    """
    Mengarahkan create/update ke `service_class`.

    `BaseMasterViewSet` sendiri hanya memakai `service_class` untuk
    `get_queryset()` dan `soft_delete()`; jalur tulisnya masih
    `serializer.save()` bawaan DRF. Akibatnya logika yang ditaruh di
    `Service.create()` / `Service.update()` tidak pernah jalan lewat API
    — mis. denormalisasi company/branch/location pada
    `EmployeeAttendanceService`.

    Mixin ini menutup celah itu untuk viewset yang memakainya, tanpa
    mengubah perilaku viewset lama yang sudah telanjur bergantung pada
    `serializer.save()`.

    Dipasang di depan `BaseMasterViewSet`:

        class EmployeeLeaveViewSet(ServiceWriteMixin, BaseMasterViewSet):
            service_class = EmployeeLeaveService
    """

    def _service_user(self):
        user = getattr(self.request, "user", None)

        if user is not None and user.is_authenticated:
            return user

        return None

    def perform_create(self, serializer):
        service = self.service_class

        if service is None or not hasattr(service, "create"):
            serializer.save()

            return

        serializer.instance = service.create(
            data=dict(serializer.validated_data),
            user=self._service_user(),
        )

    def perform_update(self, serializer):
        service = self.service_class

        if service is None or not hasattr(service, "update"):
            serializer.save()

            return

        serializer.instance = service.update(
            instance=serializer.instance,
            data=dict(serializer.validated_data),
            user=self._service_user(),
        )


class PeriodScopedListMixin:
    """
    Rentang tanggal **wajib** untuk daftar transaksional.

    Dipasang di depan base-nya, sama seperti `ServiceWriteMixin`:

        class EmployeeAttendanceViewSet(
            PeriodScopedListMixin,
            BaseMasterViewSet,
        ):
            period_field = "work_date"

    Tanpa `date_from`/`date_to`, daftarnya jatuh ke **bulan berjalan
    sampai hari ini** — bukan seluruh histori. Itu bagian yang paling
    menentukan: layar yang bawaannya "semua waktu" tetap membayar
    `COUNT(*)` atas seluruh tabel walau yang dikirim cuma 25 baris, dan
    tidak ada satu pun filter di layar yang bisa disalahkan untuk itu.

    **Hanya untuk aksi daftar** (`period_actions`), dan itu bukan
    kelalaian. `filter_queryset()` juga yang dipakai `get_object()`,
    jadi rentang yang berlaku di sana akan membuat setiap record di luar
    bulan berjalan balas 404 — dokumen yang ada, terbaca sebagai
    dokumen yang hilang, persis saat orang mengklik barisnya dari hasil
    pencarian.

    Rentangnya dipasang **sebelum** `super().filter_queryset()`, jadi
    urutannya: tenant -> rentang -> filter/search/sort -> cakupan data
    -> pagination. Semuanya tetap satu query SQL; yang berubah cuma
    seberapa banyak baris yang pernah dipertimbangkan.

    Yang **tidak** disentuh: izin model, cakupan data, pelebaran
    peserta alur, dan seluruh aturan bisnis. Rentang membatasi baris
    mana yang ditanyakan, bukan siapa yang boleh melihatnya.
    """

    # Kolom tanggal yang dibatasi. `None` = mixin-nya diam sepenuhnya.
    period_field = None

    # Aksi yang dibatasi. `export` ikut: ia memakai `filter_queryset()`
    # yang sama dan mengiterasi **seluruh** hasilnya, jadi justru di
    # sanalah rentang tanpa batas paling mahal.
    period_actions = ("list", "export")

    # `None` = pakai `MAX_RANGE_DAYS` milik framework.
    period_max_days = None

    def get_list_period(self):
        """
        Rentang yang sedang berlaku, atau `None` kalau aksinya bukan
        aksi daftar. Dihitung sekali per request.
        """
        if not self.period_field:
            return None

        if (getattr(self, "action", None) or "") not in self.period_actions:
            return None

        cached = getattr(self, "_list_period", None)

        if cached is not None:
            return cached

        request = getattr(self, "request", None)

        params = (
            getattr(request, "query_params", None)
            if request is not None
            else None
        )

        period = list_period.resolve_period(
            params if params is not None else {},
            max_days=self.period_max_days,
        )

        self._list_period = period

        return period

    def filter_queryset(self, queryset):
        period = self.get_list_period()

        if period is not None:
            queryset = queryset.filter(
                **{
                    f"{self.period_field}__gte": period.start,
                    f"{self.period_field}__lte": period.end,
                }
            )

        return super().filter_queryset(queryset)
