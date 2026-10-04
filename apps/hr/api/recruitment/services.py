from __future__ import annotations

from apps.core.services.master import BaseMasterService

from apps.hr.models import Candidate, CandidateInterview, JobVacancy
from apps.uploads.services import AttachmentLifecycleService


class JobVacancyService(BaseMasterService):
    model = JobVacancy


class CandidateService(
    AttachmentLifecycleService,
    BaseMasterService,
):
    model = Candidate

    attachment_fields = ("resume_file",)


class CandidateInterviewService(BaseMasterService):
    model = CandidateInterview
