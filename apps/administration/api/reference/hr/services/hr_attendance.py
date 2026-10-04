from apps.core.services import (
    BaseMasterService,
    BaseReferenceService,
)

from apps.administration.models.references.hr_attendance import (
    Shift,
    ShiftGroup,
    WorkSchedule,
    WorkScheduleDay,
)


class ShiftGroupService(BaseReferenceService):
    model = ShiftGroup


# `list()` wajib ditulis, dan ketiadaannya adalah **500**, bukan daftar
# kosong.
#
# `BaseMasterViewSet.get_queryset()` merakit querysetnya lewat
# `service_class.list()`; kalau service-nya tidak punya, ia jatuh ke
# atribut `queryset` viewset — dan kalau itu juga tidak ada, melempar
# `AssertionError` berbunyi "must define `queryset`…". Asimetri yang
# gampang terlewat: `BaseReferenceService` **punya** `list()`,
# `BaseMasterService` **tidak**, jadi turunan yang satu jalan dan
# turunan yang lain mati.
#
# Ketiga layar ini tidak pernah punya tab di HR References, jadi
# 500-nya tidak pernah kelihatan siapa pun — sampai ada yang mencari
# di mana jam kerja diatur.


class ShiftService(BaseMasterService):
    model = Shift

    @classmethod
    def list(cls):
        # `shift_group` ikut ditarik: kolom Shift Group di tabel membaca
        # `shift_group_name`, dan tanpa ini tiap baris menambah satu
        # query.
        return cls.get_queryset().select_related("shift_group")


class WorkScheduleService(BaseMasterService):
    model = WorkSchedule

    @classmethod
    def list(cls):
        return cls.get_queryset()


class WorkScheduleDayService(BaseMasterService):
    model = WorkScheduleDay

    @classmethod
    def list(cls):
        return cls.get_queryset().select_related(
            "work_schedule",
            "shift",
        )