from __future__ import annotations

from typing import Any, Mapping

from django.db import models
from django.db.models import QuerySet


class BaseLookup:
    """
    Base definition for every lookup.
    """

    name: str | None = None

    model: type[models.Model] | None = None
    queryset: QuerySet | None = None

    value_field = "id"
    label_field = "name"

    search_fields: list[str] = []
    filter_fields: list[str] = []
    ordering: list[str] = []

    # Peta `{jenis cakupan: jalur ORM}` untuk `DataScopeService.filter`.
    # `None` = dropdown ini tidak disaring cakupan data sama sekali —
    # bawaan, supaya lookup yang sudah ada tidak berubah perilakunya.
    #
    # Dropdown adalah jalur bocor yang paling gampang terlewat: ia
    # dipakai sebagai **pilihan filter** di dashboard dan laporan, jadi
    # tanpa peta ini orang yang cuma bercakupan satu company tetap
    # melihat nama seluruh perusahaan di tenant — dan bisa memilihnya.
    data_scope: dict | None = None

    # `allow_null` untuk `DataScopeService.filter`. `None` = ikut
    # `DATA_SCOPE_INCLUDE_NULL` di settings.
    data_scope_allow_null: bool | None = None

    # Cakupan dropdown ini dihitung **per izin**, bukan dari gabungan
    # cakupan seluruh role pemegang akun.
    #
    # Opt-in, dan bawaannya mati, karena kebanyakan dropdown memang
    # data referensi yang dipakai lintas modul oleh orang yang tidak
    # berkepentingan mengubahnya — memberi mereka izin `view_*` hanya
    # supaya dropdown negara muncul adalah menukar satu masalah dengan
    # masalah yang lebih besar.
    #
    # Dinyalakan untuk dropdown yang mewakili **resource bisnis
    # terjaga**: begitu tabelnya menuntut `view_<model>`, dropdown-nya
    # harus menuntut izin yang sama. Kalau tidak, yang tidak muncul di
    # tabel tetap bisa dipilih dari dropdown — dan bedanya tidak
    # terlihat siapa pun.
    require_view_permission: bool = False

    page_size = 20
    max_page_size = 100

    @classmethod
    def get_key(cls) -> str:
        if not cls.name:
            raise ValueError(
                f"{cls.__name__}.name is required."
            )

        return cls.name

    @classmethod
    def has_field(cls, field_name: str) -> bool:
        if cls.model is None:
            return False

        return any(
            field.name == field_name
            for field in cls.model._meta.get_fields()
        )

    @classmethod
    def get_queryset(cls) -> QuerySet:
        if cls.queryset is not None:
            queryset = cls.queryset.all()
        elif cls.model is None:
            raise ValueError(
                f"{cls.__name__}.model is required."
            )
        else:
            queryset = cls.model.objects.all()

        # Lookup dipakai untuk *memilih* nilai, jadi record yang sudah
        # dihapus atau dinonaktifkan tidak boleh ikut muncul.
        if cls.has_field("is_deleted"):
            queryset = queryset.filter(is_deleted=False)

        if cls.has_field("is_active"):
            queryset = queryset.filter(is_active=True)

        return queryset

    @classmethod
    def apply_filters(
        cls,
        queryset: QuerySet,
        params: Mapping[str, Any],
    ) -> QuerySet:
        """
        Apply only explicitly allowed query parameters.

        Example:
            ?company_id=1
            ?branch_id=2
        """

        for field_name in cls.filter_fields:
            values = cls.filter_values(params, field_name)

            if not values:
                continue

            if len(values) == 1:
                queryset = queryset.filter(**{field_name: values[0]})
            else:
                queryset = queryset.filter(**{f"{field_name}__in": values})

        return queryset

    @staticmethod
    def filter_values(params: Mapping[str, Any], field_name: str) -> list[str]:
        """
        Nilai satu parameter induk, selalu sebagai daftar.

        Dua bentuk diterima: `?company_id=1&company_id=2` dan
        `?company_id=1,2` — dialek yang sama dengan filter bercentang
        banyak di dashboard (`BaseDashboardAPIView._multi_values`).
        Yang kedua yang benar-benar dipakai: `useApi.buildUrl` di
        frontend meng-`String()` seluruh nilai query, jadi array Vue
        mendarat sebagai "1,2".

        Tanpa ini, filter Company yang bercentang banyak mengirim
        `company_id=1,2` dan dropdown turunannya membalas 500 —
        `filter(company_id="1,2")` bukan angka.
        """
        raw_values: list[Any] = []

        getlist = getattr(params, "getlist", None)

        if callable(getlist):
            raw_values = list(getlist(field_name))
        else:
            value = params.get(field_name)

            if value is not None:
                raw_values = value if isinstance(value, (list, tuple)) else [value]

        values: list[str] = []

        for raw in raw_values:
            for piece in str(raw).split(","):
                piece = piece.strip()

                if piece and piece not in values:
                    values.append(piece)

        return values

    @classmethod
    def apply_scope(cls, queryset: QuerySet, request) -> QuerySet:
        """
        Cakupan data (kewenangan `RoleAssignment`) untuk dropdown ini.

        Tanpa `data_scope` tidak melakukan apa pun — itu keadaan
        seluruh lookup sebelum ini ada, dan yang membuat penambahan ini
        tidak mengubah satu pun dropdown yang belum dipetakan.

        `distinct()` hanya dipasang kalau petanya menyeberang relasi
        (`locations__id`): jalur balik seperti itu menggandakan baris
        induk, dan dropdown yang menyebut "Meinova Mineral Resources"
        tiga kali terbaca seperti data master yang rusak.
        """
        return cls.scoped(queryset, getattr(request, "user", None))

    @classmethod
    def scoped(cls, queryset: QuerySet, user) -> QuerySet:
        """
        Bagian cakupan `apply_scope`, tanpa `request`.

        Terpisah karena ada pemanggil yang cuma memegang usernya —
        `/auth/me` menyusun isi tombol "Lokasi Saya" dari sini, dan
        turunan yang menambahkan pengelompokan di `apply_scope` tetap
        butuh daftar yang **belum** dikelompokkan. Menyalin empat baris
        di bawah ke tiap pemanggil adalah cara paling pasti membuat
        salah satunya menyimpang dari yang ditegakkan lookup-nya.
        """
        if not cls.data_scope:
            return queryset

        from apps.accounts.permissions import view_permission_for
        from apps.accounts.scoping import DataScopeService

        scoped = DataScopeService.filter(
            queryset,
            cls.data_scope,
            user,
            allow_null=cls.data_scope_allow_null,
            required_permission=(
                view_permission_for(queryset.model)
                if cls.require_view_permission
                else None
            ),
        )

        if any("__" in path for path in cls.data_scope.values()):
            scoped = scoped.distinct()

        return scoped

    @classmethod
    def apply_ordering(
        cls,
        queryset: QuerySet,
    ) -> QuerySet:
        if cls.ordering:
            return queryset.order_by(*cls.ordering)

        return queryset

    @classmethod
    def serialize(
        cls,
        instance: models.Model,
    ) -> dict[str, Any]:
        return {
            "value": getattr(
                instance,
                cls.value_field,
            ),
            "label": getattr(
                instance,
                cls.label_field,
            ),
        }