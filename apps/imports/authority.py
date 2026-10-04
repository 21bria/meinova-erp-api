"""
Riwayat import siapa yang boleh dibaca siapa.

Keadaan sebelum ini: `/api/imports/jobs/` cuma `IsAuthenticated` dengan
queryset `ImportJob.objects` apa adanya. Setiap akun yang login membaca
**seluruh** riwayat import tenant — modul apa yang diimpor, nama
berkasnya, berapa baris gagal, dan pesan galatnya. Lewat itu pula
`source_file` tetap terbaca luas, karena lampiran mewarisi otoritas
induknya (Stage 3B.1) dan induk yang terbuka mewariskan keterbukaan.

Dari mana otoritasnya
---------------------
**WHAT — dari sasaran importnya.** `ImportJob.module` menyimpan
`framework_module` resource yang diimpor
(`hr/leave-opening-balances`, `administration/calendar/work-calendar`,
…), dan kunci itu sudah menjadi penghubung resmi antara layar, endpoint,
dan izinnya. Jadi: **boleh membaca riwayat import sebuah resource kalau
boleh membaca resource itu.** Itu yang mencegah pengimpor HR membaca
riwayat import Finance — tanpa menciptakan satu izin lebar baru yang
kebetulan mencakup keduanya.

Aturannya sengaja **mencerminkan** sasarannya, bukan lebih ketat: modul
yang bacanya memang terbuka tetap terbuka riwayatnya. Catatan tentang
sebuah tabel tidak boleh lebih rahasia daripada isi tabelnya.

**WHERE — tidak ada, dan itu temuan, bukan kelalaian.** `ImportJob`
tidak menyimpan satu pun kolom organisasi: tidak ada company, branch,
maupun location. Satu-satunya atribusi per baris `imported_by`. Tidak
ada relasi lain yang bisa dipakai — `profile_code` disimpan sebagai
teks, bukan FK ke `ImportProfile`, jadi ia tidak bisa diandalkan
sebagai jalur otoritas. Cakupan organisasi untuk riwayat import karena
itu **TERBLOKIR** sampai ada keputusan; menambah kolom berarti
migration, dan itu bukan wewenang stage ini.

Yang berlaku sementara: **milik sendiri, atau modul yang boleh
dibaca.** Keduanya terbukti dari skema yang ada.
"""

from __future__ import annotations

from django.db.models import Q


def readable_jobs(queryset, user):
    """
    Menyaring queryset `ImportJob` ke yang boleh dibaca `user`.

    Satu jalur untuk daftar, detail, galat, dan unduhan laporannya —
    kalau ditulis terpisah, salah satunya akan menyimpang, dan yang
    menyimpang tidak akan berbunyi.
    """
    from apps.framework.authority import may_read_model, model_for_module

    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()

    if getattr(user, "is_superuser", False):
        return queryset

    # Modul dinilai sekali per modul yang benar-benar ada barisnya,
    # bukan sekali per baris.
    modules = set(
        queryset.values_list("module", flat=True).distinct()
    )

    allowed = {
        module
        for module in modules
        if may_read_model(model_for_module(module), user)
    }

    # Job sendiri tetap terlihat. Bukan pintu belakang: yang dilihat
    # pemiliknya adalah catatan pekerjaannya sendiri, dan tanpa ini
    # operator kehilangan jejak import yang baru saja ia jalankan
    # begitu izin modulnya berpindah tangan.
    return queryset.filter(
        Q(module__in=allowed) | Q(imported_by_id=user.pk),
    )
