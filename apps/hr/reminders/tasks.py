"""
Tugas harian pengingat tanggal kepegawaian.

Dua task, dan pemisahannya penting. Penjadwalnya (`django_celery_beat`)
duduk di **public schema** dan tidak tahu apa-apa soal tenant, jadi satu
task pembagi mendaftar tenant lalu mengantre satu task per schema.
Menaruh seluruh tenant dalam satu task membuat satu tenant yang datanya
rusak menghentikan pengingat tenant lain.

`schema_name` dioper sebagai argumen task — pola yang sama dengan
`run_attendance_import`. Worker tidak mewarisi schema dari pemanggilnya.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django_tenants.utils import get_tenant_model, schema_context

logger = logging.getLogger(__name__)


@shared_task(name="hr.dispatch_employee_reminders")
def dispatch_employee_reminders():
    """
    Sebar ke seluruh tenant. Ini yang dipanggil Celery Beat.
    """
    Tenant = get_tenant_model()

    schemas = list(
        Tenant.objects
        .exclude(schema_name="public")
        .values_list("schema_name", flat=True)
    )

    for schema_name in schemas:
        send_employee_reminders.delay(schema_name)

    logger.info("Pengingat kepegawaian disebar ke %s tenant.", len(schemas))

    return {"tenants": len(schemas)}


@shared_task(name="hr.send_employee_reminders")
def send_employee_reminders(schema_name: str):
    """
    Jalankan untuk satu tenant.

    Kegagalan satu tenant dicatat dan **tidak** dilempar ulang: task ini
    diantre per tenant, dan membiarkannya gagal berisik cuma memenuhi
    antrean ulangan tanpa ada yang memperbaiki datanya hari itu juga.
    """
    from apps.hr.api.dashboard.reminder_notifier import (
        EmployeeReminderNotifier,
    )

    try:
        with schema_context(schema_name):
            stats = EmployeeReminderNotifier.run()
    except Exception:
        logger.exception(
            "Pengingat kepegawaian gagal untuk tenant %s.",
            schema_name,
        )

        return {"schema": schema_name, "error": True}

    return {"schema": schema_name, **stats}


# ----------------------------------------------------------------------
# Pengingat keberangkatan Travel Request
# ----------------------------------------------------------------------
#
# Pola yang sama persis dengan pengingat kepegawaian di atas: satu task
# pembagi mendaftar tenant, satu task per schema. Ditulis ulang alih-alih
# digeneralisasi jadi satu pembagi berparameter — nama task ikut masuk
# jadwal Celery Beat yang tersimpan di tabel, dan task berparameter
# membuat satu baris jadwal yang salah ketik argumennya gagal dengan
# pesan yang tidak menyebut pengingat mana yang mati.


@shared_task(name="hr.dispatch_travel_reminders")
def dispatch_travel_reminders():
    Tenant = get_tenant_model()

    schemas = list(
        Tenant.objects
        .exclude(schema_name="public")
        .values_list("schema_name", flat=True)
    )

    for schema_name in schemas:
        send_travel_reminders.delay(schema_name)

    logger.info("Pengingat keberangkatan disebar ke %s tenant.", len(schemas))

    return {"tenants": len(schemas)}


@shared_task(name="hr.send_travel_reminders")
def send_travel_reminders(schema_name: str):
    from apps.hr.reminders.travel import run

    try:
        with schema_context(schema_name):
            stats = run()
    except Exception:
        logger.exception(
            "Pengingat keberangkatan gagal untuk tenant %s.",
            schema_name,
        )

        return {"schema": schema_name, "error": True}

    return {"schema": schema_name, **stats}


# ----------------------------------------------------------------------
# Pengingat kedaluwarsa saldo cuti
# ----------------------------------------------------------------------


@shared_task(name="hr.dispatch_leave_expiry_reminders")
def dispatch_leave_expiry_reminders():
    Tenant = get_tenant_model()

    schemas = list(
        Tenant.objects
        .exclude(schema_name="public")
        .values_list("schema_name", flat=True)
    )

    for schema_name in schemas:
        send_leave_expiry_reminders.delay(schema_name)

    logger.info(
        "Pengingat kedaluwarsa cuti disebar ke %s tenant.",
        len(schemas),
    )

    return {"tenants": len(schemas)}


@shared_task(name="hr.send_leave_expiry_reminders")
def send_leave_expiry_reminders(schema_name: str):
    from apps.hr.reminders.leave_expiry import run

    try:
        with schema_context(schema_name):
            stats = run()
    except Exception:
        logger.exception(
            "Pengingat kedaluwarsa cuti gagal untuk tenant %s.",
            schema_name,
        )

        return {"schema": schema_name, "error": True}

    return {"schema": schema_name, **stats}
