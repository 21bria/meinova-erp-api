"""
Pengingat keberangkatan Travel Request.

Ambang harinya diambil dari `RosterPolicy.notify_lead_days` — kolom yang
sudah lama tersimpan dan **belum pernah ada yang membacanya**. Ini
pemakai pertamanya.

Kenapa dari policy, bukan dari settings: berapa hari sebelumnya orang
perlu diingatkan bergantung jarak. Pegawai ber-POH Makassar yang
menempuh dua etape butuh persiapan berbeda dari yang tinggal satu jam
dari bandara, dan policy sudah berjenjang per (company, location).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db.models import Prefetch
from django.utils import timezone

logger = logging.getLogger(__name__)


# Jatuhan kalau policy-nya belum diisi. Tujuh hari: cukup untuk mengurus
# izin dan mengemas, belum terlalu jauh sampai terlupakan lagi.
DEFAULT_LEAD_DAYS = 7


def _lead_days_for(request) -> int:
    """
    Ambang pengingat yang berlaku untuk satu dokumen.

    Kegagalan resolusi jatuh ke bawaan, bukan melewatkan dokumennya:
    policy yang belum diisi adalah keadaan yang lazim di tenant baru,
    dan pengingat yang tidak pernah dikirim tidak memberi tahu siapa pun
    bahwa masternya kurang.
    """
    try:
        from apps.hr.api.site_rotation.policy import RosterPolicyResolver

        # `policy_for` mengembalikan pembungkus ber-`source`, bukan
        # policy-nya langsung. Sumbernya **tidak** diperiksa di sini:
        # bawaan site pun sah untuk keperluan ini — `can_generate` cuma
        # relevan buat generator jadwal, sementara ambang pengingat
        # berlaku untuk siapa pun yang punya tanggal berangkat.
        resolved = RosterPolicyResolver.policy_for(request.employee)

        policy = getattr(resolved, "policy", None)

        value = getattr(policy, "notify_lead_days", None) if policy else None

        return int(value) if value else DEFAULT_LEAD_DAYS
    except Exception:  # noqa: BLE001
        logger.debug(
            "Roster policy untuk TR %s tidak bisa di-resolve, "
            "memakai ambang bawaan.",
            getattr(request, "pk", None),
        )

        return DEFAULT_LEAD_DAYS


def run(*, today: date | None = None, dry_run: bool = False) -> dict:
    """
    Jalankan untuk satu tenant. Wajib sudah di dalam `schema_context()`.

    Hanya dokumen **yang sudah disetujui** yang diingatkan. Yang masih
    menunggu tanda tangan belum punya jadwal yang pasti, dan mengirim
    "berangkat 7 hari lagi" untuk perjalanan yang bisa saja ditolak
    membuat pengingatnya tidak bisa dipercaya.
    """
    from apps.hr.api.travel_request import notifications as travel_notifications
    from apps.hr.models import TravelArrangement, TravelRequest, TravelRequestStatus

    # `timezone.localdate()`, bukan `date.today()`: yang kedua memakai
    # zona waktu proses. Worker Celery yang jalan UTC akan menganggap
    # hari baru dimulai jam tujuh pagi WIT, jadi pengingat H-7
    # terkirim sehari meleset untuk sebagian dokumen dan tepat untuk
    # sebagian lain — selisih yang tidak pernah terbaca sebagai bug.
    today = today or timezone.localdate()

    stats = {"checked": 0, "notified": 0}

    # Jendela pencarian dibatasi supaya query-nya tidak menyapu seluruh
    # riwayat. Ambang terbesar yang masuk akal jauh di bawah 60 hari.
    horizon = today + timedelta(days=60)

    # Batas bawahnya `start_date`, bukan tanggal berangkat: berangkatnya
    # mendahului blok off, jadi dokumen yang blok off-nya belum lewat
    # pasti masih tercakup. Menyaring lebih ketat dari itu berarti
    # menyaring lewat kolom yang tidak ada di tabel.
    candidates = (
        TravelRequest.objects
        .filter(
            is_deleted=False,
            status=TravelRequestStatus.APPROVED,
            start_date__gte=today,
            start_date__lte=horizon,
        )
        .select_related("employee", "company")
        .prefetch_related(
            # `departure_date` menyaring di Python, jadi prefetch ini
            # yang membuatnya tidak menembak satu query per dokumen.
            Prefetch(
                "travels",
                queryset=TravelArrangement.objects.filter(is_deleted=False),
            ),
        )
    )

    for request in candidates:
        stats["checked"] += 1

        # Etape pertama arah keluar, bukan awal blok off. Selisihnya
        # sepanjang perjalanan site → POH, dan untuk POH yang jauh itu
        # tiga hari — pengingat H-7 yang dihitung dari blok off
        # terkirim saat orangnya sudah berangkat.
        departure = request.departure_date

        if departure is None:
            continue

        days_left = (departure - today).days

        if days_left != _lead_days_for(request):
            continue

        if dry_run:
            stats["notified"] += 1

            continue

        travel_notifications.notify_departure(request, days_left=days_left)

        stats["notified"] += 1

    logger.info("Pengingat keberangkatan: %s", stats)

    return stats
