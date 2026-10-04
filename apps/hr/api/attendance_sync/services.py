from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.hr.imports.attendance import workdate
from apps.hr.imports.attendance.config import (
    DEFAULT_GRACE_AFTER_MINUTES,
    DEFAULT_GRACE_BEFORE_MINUTES,
)
from apps.hr.imports.services.attendance import (
    AttendanceImportWriter,
)
from apps.hr.imports.services.matcher import (
    AttendanceEmployeeMatcher,
)


logger = logging.getLogger(
    __name__,
)


# `AttendanceLog.external_id` untuk tap dari agent (ATT-SYNC-CORR-1).
# Identitasnya device + `source_key`: agent menghitung `source_key`
# dari `rid|serno|nomor pegawai|jam tap`, jadi stabil per tap fisik.
# Unique `(source, external_id)` di tabel log yang menjadikan kiriman
# ulang idempoten di tingkat database.
EXTERNAL_PREFIX = "agent:"

# Pesan per record yang gagal diproses. Sebab aslinya hanya di log
# server: isi exception bisa menyebut data pegawai.
GENERIC_RECORD_FAILURE = "Record could not be processed."


class _Conflict(Exception):
    """`source_key` yang sama sudah dipakai tap lain di device ini."""


class AttendanceSyncService:
    @classmethod
    def build_normalized_record(
        cls,
        *,
        record: dict[str, Any],
        request_device_code: str = "",
    ) -> dict[str, Any]:
        source_key = str(
            record.get(
                "source_key",
            )
            or "",
        ).strip()

        external_id = str(
            record.get(
                "external_id",
            )
            or source_key,
        ).strip()

        device_code = str(
            record.get(
                "device_code",
            )
            or request_device_code
            or "",
        ).strip()

        raw_payload = record.get(
            "raw_payload",
        )

        if not isinstance(
            raw_payload,
            dict,
        ):
            raw_payload = {}

        # Agent versi lama belum mengirim employee_name,
        # tapi nama mesinnya ikut terbawa di raw_payload.
        employee_name = str(
            record.get(
                "employee_name",
            )
            or raw_payload.get("name")
            or raw_payload.get("ename")
            or "",
        ).strip()

        return {
            "employee_code":
                str(
                    record.get(
                        "employee_code",
                    )
                    or "",
                ).strip(),

            "employee_name":
                employee_name,

            "log_time":
                record[
                    "log_time"
                ],

            "log_type":
                str(
                    record.get(
                        "log_type",
                    )
                    or "unknown",
                ).strip().lower(),

            "device_code":
                device_code,

            # Source key lebih aman untuk
            # identitas unik lintas device.
            "external_id":
                source_key
                or external_id,

            "source_key":
                source_key,

            "raw_payload":
                record.get(
                    "raw_payload",
                    {},
                ),
        }

    @staticmethod
    def in_device_scope(employee, device) -> bool:
        """
        Pegawai ini boleh ditulis oleh device ini?

        * Feature Applicability: presensi harus berlaku baginya.
        * Company penempatan aktifnya = company device; kalau device punya
          lokasi, lokasinya juga harus sama.
        * Pengecualian **eksplisit**: pemetaan `AttendanceDeviceEmployee`
          yang aktif untuk pasangan device–pegawai ini (mis. pegawai site
          lain yang memang tap di mesin ini).
        """
        from apps.hr.applicability import HRFeature, is_applicable
        from apps.hr.models import AttendanceDeviceEmployee

        if not is_applicable(employee, HRFeature.ATTENDANCE):
            return False

        mapped = AttendanceDeviceEmployee.objects.filter(
            device=device,
            employee=employee,
            is_active=True,
            is_deleted=False,
        ).exists()

        if mapped:
            return True

        assignment = AttendanceImportWriter.get_assignment(employee)

        if assignment is None or assignment.company_id != device.company_id:
            return False

        if device.location_id and assignment.location_id != device.location_id:
            return False

        return True

    @classmethod
    @transaction.atomic
    def process_record(
        cls,
        *,
        record: dict[str, Any],
        device,
        agent_code: str = "",
    ) -> dict[str, Any]:
        normalized = (
            cls.build_normalized_record(
                record=record,
                request_device_code=device.code,
            )
        )

        employee = (
            AttendanceEmployeeMatcher
            .find_employee(
                normalized[
                    "employee_code"
                ]
            )
        )

        # Di luar cakupan device dibalas persis seperti nomor yang tidak
        # ada: device tidak boleh belajar apa pun tentang pegawai yang
        # bukan urusannya. Sebabnya dicatat di log server saja.
        if employee is not None and not cls.in_device_scope(employee, device):
            logger.info(
                "Attendance agent sync: employee %s outside scope of device %s",
                employee.pk,
                device.pk,
            )

            employee = None

        if employee is None:
            return {
                "source_key":
                    normalized[
                        "source_key"
                    ],

                "employee_code":
                    normalized[
                        "employee_code"
                    ],

                "success":
                    False,

                "status":
                    "unmatched",

                "message":
                    "Employee not found.",
            }

        # Pencocokan karyawan murni lewat nomor. Nama
        # dari mesin hanya dibandingkan sebagai alarm:
        # nomor yang salah enroll akan menempel ke
        # karyawan lain tanpa suara kalau tidak dicatat.
        # Record tetap ditulis — jangan blokir absensi
        # gara-gara ejaan nama.
        name_warning = ""

        if not AttendanceEmployeeMatcher.names_match(
            normalized["employee_name"],
            employee,
        ):
            master_name = (
                AttendanceEmployeeMatcher
                .employee_name(
                    employee,
                )
            )

            name_warning = (
                f"Employee number "
                f"{employee.employee_number} "
                f"belongs to {master_name} in the "
                f"master data, but the device "
                f"registered it as "
                f"{normalized['employee_name']}."
            )

            logger.warning(
                (
                    "Attendance agent sync name "
                    "mismatch: %s"
                ),
                name_warning,
            )

        log, attendance, created, replayed = cls.apply_tap(
            employee=employee,
            device=device,
            normalized=normalized,
            agent_code=agent_code,
        )

        if replayed:
            status_value = "duplicate"
        elif created:
            status_value = "created"
        else:
            status_value = "updated"

        return {
            "source_key":
                normalized[
                    "source_key"
                ],

            "employee_code":
                normalized[
                    "employee_code"
                ],

            "employee_id":
                employee.id,

            "attendance_id":
                attendance.id if attendance else None,

            "work_date":
                (
                    attendance.work_date.isoformat()
                    if attendance
                    else None
                ),

            "success":
                True,

            "status":
                status_value,

            "created":
                created,

            # Kosong kalau namanya wajar. Diisi hanya
            # untuk menandai nomor yang patut dicek.
            "name_warning":
                name_warning,
        }

    @staticmethod
    def external_id_for(device, source_key: str) -> str:
        return f"{EXTERNAL_PREFIX}{device.pk}:{source_key}"[:200]

    @classmethod
    def apply_tap(
        cls,
        *,
        employee,
        device,
        normalized: dict[str, Any],
        agent_code: str = "",
    ):
        """
        Satu tap mesin yang sudah lolos kredensial dan cakupan device.

            kunci pegawai → (kiriman ulang? kembalikan hasil lama)
            → AttendanceLog mentah → workdate.resolve()
            → AttendanceImportWriter.upsert() → efek izin
            → log ditautkan ke baris harian, is_processed

        Seluruhnya di dalam transaksi `process_record`: respons sukses
        tidak pernah meninggalkan baris harian tanpa log mentahnya, dan
        kegagalan di tengah menggulung keduanya.

        Kembalian: `(log, attendance, created, replayed)`.
        """
        from apps.hr.api.attendance.permission_effect import (
            AttendancePermissionEffectService,
        )
        from apps.hr.models import (
            AttendanceLog,
            AttendanceLogType,
            AttendanceSource,
            Employee,
        )

        log_time = normalized["log_time"]
        source_key = normalized["source_key"]
        external_id = cls.external_id_for(device, source_key)

        # Satu pegawai, satu tap pada satu waktu — pola yang sama dengan
        # tap Self Service. Tanpa kunci ini dua batch yang bertumpuk bisa
        # sama-sama tidak melihat log-nya lalu sama-sama menulis.
        Employee.objects.select_for_update().only("pk").get(pk=employee.pk)

        existing = (
            AttendanceLog.objects
            .select_related("attendance")
            .filter(
                source=AttendanceSource.DEVICE,
                external_id=external_id,
            )
            .first()
        )

        if existing is not None:
            # Kiriman ulang tap yang sama: hasil lama, tanpa menulis apa
            # pun. `source_key` sama untuk pegawai/jam lain bukan kiriman
            # ulang.
            if (
                existing.employee_id != employee.pk
                or existing.occurred_at != log_time
            ):
                raise _Conflict()

            return existing, existing.attendance, False, True

        # Arah dari mesin disimpan apa adanya sebagai bukti. Tombol
        # IN/OUT di keypad mesin dipilih pegawai sendiri dan sering
        # dibiarkan di nilai bawaannya, jadi baris harian tetap disusun
        # dari tap mentah — masuk paling awal, pulang paling akhir —
        # persis seperti importer file dan perilaku agent sebelumnya.
        reported = normalized.get("log_type")

        log_type = (
            reported
            if reported in (AttendanceLogType.IN, AttendanceLogType.OUT)
            else AttendanceLogType.UNKNOWN
        )

        assignment = AttendanceImportWriter.get_assignment(employee)

        log = AttendanceLog.objects.create(
            employee=employee,
            device=device,
            company=(
                assignment.company
                if assignment is not None and assignment.company_id
                else device.company
            ),
            branch=assignment.branch if assignment is not None else None,
            location=(
                assignment.location
                if assignment is not None
                else device.location
            ),
            occurred_at=log_time,
            log_type=log_type,
            source=AttendanceSource.DEVICE,
            employee_identifier=(normalized.get("employee_code") or "")[:150],
            external_id=external_id,
            raw_payload={
                "agent_code": agent_code,
                "source_key": source_key,
                "device_code": normalized.get("device_code") or "",
                "employee_name": normalized.get("employee_name") or "",
                "machine": normalized.get("raw_payload") or {},
            },
            is_processed=False,
        )

        # Hari kerja kanonik — resolver yang sama dengan importer file dan
        # tap Self Service. Tidak pernah `log_time.date()`: tap pulang
        # 02:00 dari shift 20:00–05:00 milik hari kerja kemarin.
        resolution = workdate.resolve(
            employee=employee,
            moment=log_time,
            grace_before_minutes=DEFAULT_GRACE_BEFORE_MINUTES,
            grace_after_minutes=DEFAULT_GRACE_AFTER_MINUTES,
        )

        scheduled = None

        if resolution.has_schedule:
            scheduled = (
                resolution.scheduled_check_in,
                resolution.scheduled_check_out,
            )

        attendance, created = AttendanceImportWriter.upsert(
            employee=employee,
            normalized=normalized,
            work_date=resolution.work_date,
            scheduled=scheduled,
            source=AttendanceSource.DEVICE,
        )

        # Writer tidak menerapkan izin. Tanpa ini izin yang disetujui
        # sebelum tap pertama tidak pernah memaafkan telatnya.
        AttendancePermissionEffectService.recalculate(
            employee=employee,
            work_date=resolution.work_date,
        )

        attendance.refresh_from_db()

        log.attendance = attendance
        log.is_processed = True
        log.processed_at = timezone.now()
        log.processing_error = ""
        log.save(
            update_fields=[
                "attendance",
                "is_processed",
                "processed_at",
                "processing_error",
            ],
        )

        return log, attendance, created, False

    @classmethod
    def sync(
        cls,
        *,
        agent_code: str,
        device,
        records: list[
            dict[str, Any]
        ],
    ) -> dict[str, Any]:
        created_count = 0
        updated_count = 0
        duplicate_count = 0
        unmatched_count = 0
        mismatched_count = 0
        failed_count = 0

        results: list[
            dict[str, Any]
        ] = []

        for record in records:
            source_key = str(
                record.get(
                    "source_key",
                )
                or "",
            ).strip()

            employee_code = str(
                record.get(
                    "employee_code",
                )
                or "",
            ).strip()

            try:
                item = cls.process_record(
                    record=record,
                    device=device,
                    agent_code=agent_code,
                )

            except _Conflict:
                logger.warning(
                    "Attendance agent sync: source key %s on device %s "
                    "reused for a different tap",
                    source_key,
                    device.pk,
                )

                failed_count += 1

                results.append({
                    "source_key": source_key,
                    "employee_code": employee_code,
                    "success": False,
                    "status": "conflict",
                    "message": (
                        "Source key was already used for a different tap."
                    ),
                })

                continue

            except Exception:
                logger.exception(
                    (
                        "Attendance agent sync "
                        "failed for source key %s"
                    ),
                    source_key,
                )

                failed_count += 1

                results.append({
                    "source_key":
                        source_key,

                    "employee_code":
                        employee_code,

                    "success":
                        False,

                    "status":
                        "failed",

                    "message":
                        GENERIC_RECORD_FAILURE,
                })

                continue

            results.append(
                item,
            )

            status_value = item.get(
                "status",
            )

            if status_value == "created":
                created_count += 1

            elif status_value == "updated":
                updated_count += 1

            elif status_value == "duplicate":
                duplicate_count += 1

            elif status_value == "unmatched":
                unmatched_count += 1

            if item.get("name_warning"):
                mismatched_count += 1

        # Kiriman ulang ikut terhitung diterima: tap-nya memang sudah
        # tersimpan, dan agent menandainya tersinkron.
        accepted_count = (
            created_count
            + updated_count
            + duplicate_count
        )

        return {
            "agent_code":
                agent_code,

            "device_code":
                device.code,

            "total_records":
                len(
                    records,
                ),

            "accepted_records":
                accepted_count,

            "created_records":
                created_count,

            "updated_records":
                updated_count,

            "duplicate_records":
                duplicate_count,

            "unmatched_records":
                unmatched_count,

            "name_warning_records":
                mismatched_count,

            "failed_records":
                failed_count,

            "results":
                results,
        }