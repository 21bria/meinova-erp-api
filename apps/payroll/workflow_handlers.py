"""
Menyambungkan Payroll Run ke engine approval generik.

Kotak masuk approval satu untuk semua modul, jadi saat approver menekan
Approve dari sana, engine perlu tahu apa yang harus terjadi pada
dokumennya. Engine tidak menebak nama kolom status modul mana pun — di
sinilah Payroll mendaftarkan pemetaannya sendiri.

Di-import dari `PayrollConfig.ready()`. Kalau lupa, tombol Approve di
kotak masuk tetap jalan tapi status run-nya **tidak ikut berpindah**,
dan gagalnya diam.
"""

from __future__ import annotations

import logging

from apps.workflow.registry import register_completion, register_route


logger = logging.getLogger(__name__)


# Rute halaman dokumen di frontend, dipakai tombol "Buka dokumen" di
# kotak masuk dan layar monitoring. Harus cocok dengan `app/pages/` di
# repo Nuxt — rute yang salah membuat tombolnya mendarat di 404.
register_route("payroll", "payroll_run", "/payroll/runs/{id}/edit")


@register_completion("payroll", "payroll_run")
def payroll_run_completed(instance, status):
    """
    Menutup dokumen payroll run.

    **Tidak** ikut mem-finalize. Persetujuan dan penguncian adalah dua
    keputusan yang berbeda: yang pertama menyatakan angkanya benar, yang
    kedua menerbitkan slip dan mengunci periode. Finance yang menekan
    Finalize, setelah pembayarannya dijadwalkan.
    """
    from apps.payroll.models import PayrollRun
    from apps.payroll.services import PayrollRunService

    run = (
        PayrollRun.objects
        .filter(pk=instance.object_id, is_deleted=False)
        .select_related("period")
        .first()
    )

    if run is None:
        # Dokumen yang hilang setelah alurnya berjalan. Dicatat, bukan
        # dilempar: keputusan approver-nya sendiri sudah tersimpan, dan
        # menggagalkan transaksi di titik ini membatalkan persetujuan
        # yang sah gara-gara dokumen yang sudah tidak ada.
        logger.warning(
            "Workflow %s selesai tapi payroll run #%s tidak ditemukan.",
            instance.pk,
            instance.object_id,
        )

        return None

    return PayrollRunService.on_workflow_done(
        run=run,
        status=status,
        user=instance.submitted_by,
    )
