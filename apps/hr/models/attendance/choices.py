
from __future__ import annotations

from django.db import models


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    LATE = "late", "Late"
    ABSENT = "absent", "Absent"
    LEAVE = "leave", "Leave"
    SICK = "sick", "Sick"
    PERMIT = "permit", "Permit"
    BUSINESS_TRIP = "business_trip", "Business Trip"
    REMOTE = "remote", "Remote Work"
    HOLIDAY = "holiday", "Holiday"
    DAY_OFF = "day_off", "Day Off"
    INCOMPLETE = "incomplete", "Incomplete"


class AttendanceSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    DEVICE = "device", "Attendance Device"
    MOBILE = "mobile", "Mobile"
    WEB = "web", "Web"
    IMPORT = "import", "Import"
    API = "api", "API"
    SYSTEM = "system", "System"


class AttendanceApprovalStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AttendanceLogType(models.TextChoices):
    IN = "in", "Check In"
    OUT = "out", "Check Out"
    BREAK_IN = "break_in", "Break In"
    BREAK_OUT = "break_out", "Break Out"
    UNKNOWN = "unknown", "Unknown"


class AttendanceDeviceType(models.TextChoices):
    FINGERPRINT = "fingerprint", "Fingerprint"
    FACE = "face", "Face Recognition"
    CARD = "card", "RFID / Card"
    MOBILE = "mobile", "Mobile"
    WEB = "web", "Web"
    OTHER = "other", "Other"

