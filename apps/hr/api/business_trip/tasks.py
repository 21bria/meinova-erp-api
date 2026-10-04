"""
Tugas harian Business Trip: APPROVED yang tanggal berangkatnya tiba →
ON_TRIP.

Pola pengingat kepegawaian (`apps/hr/reminders/tasks.py`): penjadwal di
public schema tidak tahu tenant, jadi satu task pembagi mengantre satu
task per schema, dan tiap task bekerja di dalam `schema_context`.

Kosmetik untuk layar daftar — cakupan presensi (BT-3) tidak menunggu
status ini. `advance_departed` satu UPDATE bersyarat per baris, jadi
aman diulang.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django_tenants.utils import get_tenant_model, schema_context


logger = logging.getLogger(__name__)


@shared_task(name="hr.dispatch_business_trip_departures")
def dispatch_business_trip_departures():
    Tenant = get_tenant_model()

    schemas = list(
        Tenant.objects
        .exclude(schema_name="public")
        .values_list("schema_name", flat=True)
    )

    for schema_name in schemas:
        advance_business_trip_departures.delay(schema_name)

    return {"tenants": len(schemas)}


@shared_task(name="hr.advance_business_trip_departures")
def advance_business_trip_departures(schema_name: str):
    from apps.hr.api.business_trip.services import BusinessTripService

    try:
        with schema_context(schema_name):
            advanced = BusinessTripService.advance_departed()
    except Exception:
        logger.exception(
            "Keberangkatan Business Trip gagal diperbarui untuk tenant %s.",
            schema_name,
        )

        return {"schema": schema_name, "error": True}

    return {"schema": schema_name, "advanced": advanced}
