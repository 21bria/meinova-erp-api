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


class ShiftService(BaseMasterService):
    model = Shift


class WorkScheduleService(BaseMasterService):
    model = WorkSchedule


class WorkScheduleDayService(BaseMasterService):
    model = WorkScheduleDay