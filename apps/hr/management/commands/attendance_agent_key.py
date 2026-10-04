"""
Kelola kredensial agent absensi per device (SEC-ATT-SYNC-1).

Dijalankan **per tenant** lewat pembungkus django-tenants:

    python manage.py tenant_command attendance_agent_key issue  <DEVICE_CODE> --schema=<tenant>
    python manage.py tenant_command attendance_agent_key rotate <DEVICE_CODE> --schema=<tenant>
    python manage.py tenant_command attendance_agent_key revoke <DEVICE_CODE> --schema=<tenant>
    python manage.py tenant_command attendance_agent_key status <DEVICE_CODE> --schema=<tenant>

`issue`/`rotate` mencetak kunci **sekali**; tempel ke `ERP_API_KEY` di
`.env` agent. Kunci lama langsung mati. Kunci tidak bisa ditampilkan ulang
— yang tersimpan hanya hash-nya.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.hr.api.attendance_sync.credentials import (
    AttendanceAgentCredentialService,
    CredentialError,
)


class Command(BaseCommand):
    help = "Issue, rotate, revoke, or inspect an attendance agent device credential."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["issue", "rotate", "revoke", "status"])
        parser.add_argument("device_code")

    def handle(self, *args, **options):
        from apps.hr.models import AttendanceDevice

        device = AttendanceDevice.objects.filter(code=options["device_code"]).first()

        if device is None:
            raise CommandError(f"Device {options['device_code']!r} not found in this tenant.")

        action = options["action"]

        if action in ("issue", "rotate"):
            try:
                raw = AttendanceAgentCredentialService.issue(device)
            except CredentialError as exc:
                raise CommandError(str(exc)) from exc

            self.stdout.write(
                f"Agent key for device {device.code} (shown once, store it in the agent's ERP_API_KEY):"
            )
            self.stdout.write(raw)

            if not device.is_active:
                self.stdout.write(self.style.WARNING("Device is inactive; the key will not authenticate until it is activated."))

            return

        if action == "revoke":
            AttendanceAgentCredentialService.revoke(device)
            self.stdout.write(f"Agent key for device {device.code} revoked.")
            return

        state = "active" if device.agent_key_hash else "none"
        self.stdout.write(
            f"device={device.code} key={state} key_id={device.agent_key_id or '-'} "
            f"issued_at={device.agent_key_issued_at or '-'} revoked_at={device.agent_key_revoked_at or '-'} "
            f"last_sync_at={device.last_sync_at or '-'} device_active={device.is_active}"
        )
