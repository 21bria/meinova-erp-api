"""
Garis pelaporan sebagai cakupan baca — turunan, bukan pengganti.

`DataScopeService` menjawab "baris milik unit organisasi mana yang boleh
dilihat". Ia **tidak** mengenal garis pelaporan sama sekali, dan itu
disengaja: jabatan dan `reports_to` dipakai engine workflow untuk
mencari approver, bukan untuk membuka data. Aturan itu tetap berlaku.

Yang ditambahkan di sini satu hal yang tidak bisa dijawab cakupan unit:
**seorang supervisor harus bisa memantau jadwal orang yang jadwalnya ia
setujui.** Ia menandatangani meja "Atasan Langsung" pada dokumen Roster
Setup, lalu tidak bisa membuka kalender shift bawahannya sendiri —
cakupannya `own`, dan `own` berarti satu baris: dirinya.

Tiga sifat yang membuat ini bukan lubang:

* **Hanya menambah, tidak pernah mengurangi.** Hasilnya di-OR di atas
  cakupan `DataScopeService`, persis pola `_widen_for_workflow_
  participants` di `BaseMasterViewSet`. Tidak ada jalur yang jadi lebih
  sempit karena berkas ini.
* **Opt-in per layar, bukan global.** Employee Master, Org Chart, dan
  seluruh dropdown lain tidak berubah satu baris pun. Yang memakainya
  cuma layar yang memang butuh — hari ini Shift Calendar.
* **Turunannya dari akun yang meminta**, jadi tidak ada parameter yang
  bisa dipakai membuka data orang lain: yang paling jauh bisa didapat
  seseorang adalah bawahannya sendiri.

Berjenjang, bukan satu tingkat. Manajer site membawahi supervisor yang
membawahi crew, dan "tim saya" bagi manajer itu memang mencakup
keduanya. Dibatasi `MAX_REPORTING_DEPTH` dan dijaga terhadap rantai yang
berputar — data organisasi nyata pernah punya A→B→A, dan penelusuran
tanpa pagar akan berputar sampai kehabisan memori alih-alih melaporkan
datanya yang salah.
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


# Sedalam apa "tim saya" ditelusuri. Enam tingkat sudah melewati struktur
# terdalam yang masuk akal (Direktur → GM → Manager → Superintendent →
# Supervisor → Foreman → crew); di atas itu yang ditemukan lebih mungkin
# data yang salah daripada organisasi yang memang sedalam itu.
MAX_REPORTING_DEPTH = 6


def employee_of(user):
    """Pegawai di balik satu akun, atau `None`."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    return getattr(user, "employee_profile", None)


def subordinate_ids(user, *, max_depth: int = MAX_REPORTING_DEPTH) -> set[int]:
    """
    Id pegawai yang berada **di bawah** `user` menurut
    `OrganizationAssignment.reports_to`, berjenjang.

    Dirinya sendiri **tidak** ikut: itu urusan cakupan `own`, dan
    mencampurnya di sini membuat dua sumber untuk satu baris yang sama.

    Ditelusuri per tingkat (BFS) supaya jumlah query-nya sedalam
    strukturnya, bukan sebanyak orangnya — satu query per tingkat, enam
    tingkat paling banyak.
    """
    employee = employee_of(user)

    if employee is None:
        return set()

    from apps.hr.models import OrganizationAssignment

    seen: set[int] = {employee.pk}
    frontier: set[int] = {employee.pk}
    collected: set[int] = set()

    for _ in range(max_depth):
        if not frontier:
            break

        children = set(
            OrganizationAssignment.objects
            .filter(
                reports_to_id__in=frontier,
                is_deleted=False,
                employee__is_deleted=False,
            )
            .values_list("employee_id", flat=True)
        )

        # Rantai yang berputar berhenti di sini: yang sudah pernah
        # dilihat tidak ditelusuri lagi. Hasilnya tetap benar untuk
        # bagian yang tidak berputar, alih-alih gagal seluruhnya.
        frontier = children - seen

        seen |= children
        collected |= frontier

    collected.discard(employee.pk)

    return collected


def widen(scoped, *, base, user, path: str = "pk"):
    """
    Menambahkan bawahan `user` ke queryset yang sudah tersaring cakupan.

    `base` **wajib** dan harus queryset yang sama sebelum disaring
    cakupan. Meng-OR dengan `Model.objects.filter(...)` yang telanjang
    akan menghidupkan kembali baris yang sudah dibuang penyaring dasar —
    `is_deleted=True`, pegawai nonaktif — karena `|` menggabungkan
    kondisinya dengan OR, bukan menumpuknya. Bocornya kecil dan diam,
    dan justru lewat jalur yang ditambahkan untuk memperluas akses.

    `path` menyebut jalur ke `Employee` dari model queryset-nya —
    `"pk"` untuk `Employee` sendiri, `"employee_id"` untuk tabel anak.

    Tidak melakukan apa-apa kalau orangnya memang tidak membawahi
    siapa-siapa; `scoped` dikembalikan apa adanya supaya jalur yang
    tidak terpengaruh tetap menghasilkan SQL yang sama persis.
    """
    ids = subordinate_ids(user)

    if not ids:
        return scoped

    return (scoped | base.filter(**{f"{path}__in": ids})).distinct()
