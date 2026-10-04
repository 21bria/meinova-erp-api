"""
Mengosongkan data **transaksi** roster supaya bisa dicoba entry ulang.

Bedanya dengan `demo_reset`: yang itu membongkar seluruh tenant uji —
pegawai, akun, dokumen semua modul. Yang ini hanya membuang hasil kerja
alur roster, dan meninggalkan segala yang dibutuhkan untuk mengulanginya:
pegawai, Roster Policy beserta rotasi shift-nya, master Shift, definisi
alur, template notifikasi, dan presensi.

Hard delete, bukan soft. Baris bertanda terhapus tetap memegang kunci
uniknya — `uniq_workflow_open_instance` yang paling cepat menggigit —
sehingga percobaan berikutnya ditolak oleh bangkai percobaan sebelumnya.

Tiga hal yang tidak akan terhapus sendiri kalau tidak disebut di sini,
dan ketiganya sudah pernah salah:

* **`EmployeeShiftAssignment` tidak punya FK ke roster.** Barisnya cuma
  menunjuk pegawai dan shift, jadi menghapus `SiteRotation` meninggalkan
  rencana shift utuh — dan Shift Calendar tetap menampilkan shift di
  tanggal yang rosternya sudah tidak ada.
* **`WorkflowInstance` menunjuk dokumennya lewat `object_id` bertipe
  string.** Tidak ada cascade; membuang dokumennya saja meninggalkan
  pengajuan yang menggantung di inbox approver.
* **Notifikasi ada di dua tabel.** `administration.Notification` yang
  mengisi bel dan dashboard, dan `notifications.NotificationLog` yang
  mencatat pengirimannya. Membersihkan satu saja membuat notifikasi
  tetap terlihat di layar padahal log-nya sudah kosong.

Dokumen yang **masih berjalan** di alur ikut dikembalikan ke `draft`.
Kalau tidak, statusnya tinggal `submitted` sementara jalur
persetujuannya sudah hilang: tidak bisa disetujui, tidak bisa
diteruskan, dan tidak ada layar yang menjelaskan kenapa.
"""

from __future__ import annotations

from django.db import transaction


# Dokumen yang dilepas dari alur ikut dipulangkan ke status ini.
DRAFT = "draft"

# Alur milik roster. Dipakai saat `scope="roster"` supaya pengajuan
# modul lain — cuti, employee action — tidak ikut terbawa.
ROSTER_DOCUMENT_TYPE = "roster_setup"
ROSTER_OBJECT_TYPE = "hr-roster_setup"

# Dokumen yang **tetap ada** sesudah pengajuannya dibuang, jadi harus
# dipulangkan ke `draft`.
#
# `roster_setup` sengaja tidak ada di sini: dokumennya ikut terhapus
# beberapa langkah kemudian, jadi memulangkannya ke draft hanya
# menyentuh baris yang sebentar lagi hilang. Yang benar-benar
# menggantung justru dokumen modul lain saat `scope="all"` — pernah
# terjadi pada satu Employee Action yang berakhir `submitted` tanpa
# jalur persetujuan, tidak bisa disetujui dan tidak bisa diteruskan.
REOPENABLE = {
    "employee_action": ("apps.hr.models", "EmployeeAction"),
    "leave_request": ("apps.hr.models", "EmployeeLeave"),
}


def _reopen_stranded(instances, *, log) -> int:
    """
    Kembalikan dokumen yang alurnya belum selesai ke `draft`.

    Dipanggil **sebelum** instance-nya dibuang, selagi masih bisa
    ditelusuri dokumen mana yang menggantung.
    """
    from importlib import import_module

    reopened = 0

    for instance in instances:
        if instance.status in {"approved", "rejected", "cancelled"}:
            continue

        target = REOPENABLE.get(instance.document_type)

        if target is None:
            continue

        module_path, model_name = target
        model = getattr(import_module(module_path), model_name)

        document = model.objects.filter(pk=instance.object_id).first()

        if document is None or document.status == DRAFT:
            continue

        document.status = DRAFT
        document.save(update_fields=["status"])

        reopened += 1

        log(
            f"    {getattr(document, 'document_number', document.pk)} "
            f"dikembalikan ke draft (alurnya belum selesai)",
        )

    return reopened


@transaction.atomic
def run(
    *,
    log=print,
    scope: str = "roster",
    keep_notifications: bool = False,
) -> dict:
    """
    `scope="roster"` membuang alur & notifikasi milik roster saja.
    `scope="all"` membuang seluruh pengajuan dan notifikasi tenant —
    dipakai saat menyiapkan tenant peragaan untuk demo bersih.
    """
    from apps.administration.models import Notification
    from apps.hr.models import (
        EmployeeShiftAssignment,
        RosterAdjustment,
        RosterPlanVersion,
        RosterSetupLine,
        RosterSetupRequest,
        RotationCreditBalance,
        RotationCreditTransaction,
        RotationPeriod,
        SiteRotation,
    )
    from apps.notifications.models import NotificationLog
    from apps.workflow.models import WorkflowInstance

    counts: dict[str, int] = {}

    def drop(label, queryset):
        removed = queryset.count()

        queryset.delete()

        counts[label] = removed

        if removed:
            log(f"    {label:26} {removed}")

    log("  Mengosongkan data roster:")

    # ------------------------------------------------------------------
    # Alur dulu, selagi dokumennya masih ada untuk ditelusuri
    # ------------------------------------------------------------------
    instances = (
        WorkflowInstance.objects.all()
        if scope == "all"
        else WorkflowInstance.objects.filter(
            document_type=ROSTER_DOCUMENT_TYPE,
        )
    )

    counts["dokumen dikembalikan"] = _reopen_stranded(instances, log=log)

    # `WorkflowApproval` ikut lewat cascade.
    drop("WorkflowInstance", instances)

    # ------------------------------------------------------------------
    # Notifikasi — dua tabel, keduanya harus disebut
    # ------------------------------------------------------------------
    if not keep_notifications:
        if scope == "all":
            drop("Notification (bel)", Notification.objects.all())
            drop("NotificationLog", NotificationLog.objects.all())
        else:
            drop(
                "Notification (bel)",
                Notification.objects.filter(
                    object_type=ROSTER_OBJECT_TYPE,
                ),
            )
            drop(
                "NotificationLog",
                NotificationLog.objects.filter(
                    object_type=ROSTER_OBJECT_TYPE,
                ),
            )

    # ------------------------------------------------------------------
    # Kredit rotasi
    # ------------------------------------------------------------------
    #
    # Baris pembalik menunjuk baris yang dibalikkannya dengan `PROTECT`,
    # jadi harus lebih dulu — sekali hapus semuanya akan ditolak.
    drop(
        "RotationCreditTransaction (pembalik)",
        RotationCreditTransaction.objects.filter(reverses__isnull=False),
    )
    drop(
        "RotationCreditTransaction",
        RotationCreditTransaction.objects.all(),
    )
    drop("RotationCreditBalance", RotationCreditBalance.objects.all())

    # ------------------------------------------------------------------
    # Roster. `RotationPeriod`, `RosterPlanVersion`, dan
    # `RosterAdjustment` ikut lewat cascade — dihitung dulu supaya
    # laporannya menyebut yang sebenarnya hilang.
    # ------------------------------------------------------------------
    counts["RotationPeriod"] = RotationPeriod.objects.count()
    counts["RosterPlanVersion"] = RosterPlanVersion.objects.count()
    counts["RosterAdjustment"] = RosterAdjustment.objects.count()

    for label in ("RotationPeriod", "RosterPlanVersion", "RosterAdjustment"):
        if counts[label]:
            log(f"    {label:26} {counts[label]} (cascade)")

    drop("SiteRotation", SiteRotation.objects.all())

    # Tidak ikut cascade: tidak ada FK ke roster sama sekali.
    drop("EmployeeShiftAssignment", EmployeeShiftAssignment.objects.all())

    # ------------------------------------------------------------------
    # Dokumen setup
    # ------------------------------------------------------------------
    drop("RosterSetupLine", RosterSetupLine.objects.all())
    drop("RosterSetupRequest", RosterSetupRequest.objects.all())

    return counts
