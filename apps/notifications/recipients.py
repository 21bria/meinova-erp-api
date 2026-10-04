"""
Siapa yang menerima sebuah pemberitahuan.

Penerima adalah **User**, bukan Employee — sama seperti approver di
engine workflow, dan alasannya sama: notifikasi mendarat di bel sebuah
akun dan email dikirim ke alamat sebuah akun. Pegawai tanpa akun tidak
pernah jadi penerima, dan itu dilaporkan sebagai alasan yang terbaca,
bukan dilewati diam-diam.

**Cakupan data ikut menyaring penerima bertipe role.** Kalau tidak,
`HR-ADMIN` yang dicakup ke satu site menerima pemberitahuan kontrak
pegawai seluruh tenant — dan itu kebocoran yang tidak berbunyi, karena
emailnya memang sampai dan isinya memang benar. Penyaringnya
`DataScopeService` yang sama dengan yang dipakai tabel Employee, bukan
salinan semantik AND/OR-nya: dua salinan aturan cakupan cepat atau
lambat berbeda, dan yang satu akan membuka apa yang ditutup satunya.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService

from .constants import RecipientType

logger = logging.getLogger(__name__)


# Peta cakupan untuk Employee. Disamakan **persis** dengan
# `EmployeeViewSet.data_scope` dan `EMPLOYEE_SCOPE` di dashboard HR —
# kalau salah satu diubah, yang lain harus ikut, kalau tidak orang yang
# tidak boleh melihat sebuah baris di tabel tetap diberi tahu tentangnya
# lewat email.
EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}


@dataclass
class Recipient:
    """Satu penerima beserta alasan ia masuk daftar."""

    user: object
    reason: str = ""
    # Kanal yang boleh dipakai untuk orang ini, ditentukan baris aturan
    # yang menghasilkannya. Aturan berbeda boleh memberi kanal berbeda
    # untuk orang yang sama — lihat `merge()`.
    channels: set[str] = field(default_factory=set)

    @property
    def pk(self):
        return getattr(self.user, "pk", None)


@dataclass
class ResolvedRecipients:
    recipients: list[Recipient] = field(default_factory=list)
    # Kenapa seseorang/sekelompok orang **tidak** masuk. Ikut dilaporkan
    # ke log pengiriman: "tidak ada yang menerima" tanpa menyebut
    # sebabnya adalah keluhan yang tidak bisa ditindaklanjuti siapa pun.
    skipped: list[str] = field(default_factory=list)


def _user_of(employee):
    """
    Akun milik seorang pegawai.

    Accessor-nya `user`, dan arah sebaliknya `user.employee_profile`.
    Yang kedua sudah pernah salah tulis di codebase ini (`user.employee`
    mengembalikan None lewat `getattr` tanpa error), jadi disebut di
    sini supaya tidak terulang.
    """
    if employee is None:
        return None

    user = getattr(employee, "user", None)

    return user if user is not None and user.is_active else None


def _employee_of(user):
    if user is None:
        return None

    return getattr(user, "employee_profile", None)


def _visible_to(user, employee) -> bool:
    """
    Apakah `employee` masuk cakupan data `user`.

    Memakai mesin penyaringan yang sama dengan tabel Employee, dijalankan
    pada queryset berisi satu baris — pola yang sama dengan
    `RosterSetupService.assert_within_scope`. Satu query per calon
    penerima; jumlah pemegang role di sebuah tenant lazimnya belasan,
    jadi ini bukan jalur yang perlu dioptimalkan lebih dulu.

    Tanpa pegawai subjek (pemberitahuan yang tidak menyangkut orang
    tertentu — mis. job berkala yang selesai), cakupan tidak bisa dinilai
    dan penerimanya **diloloskan**. Menolak akan membuat pemberitahuan
    sistem tidak sampai ke siapa pun.
    """
    if employee is None:
        return True

    from apps.hr.models import Employee

    queryset = Employee.objects.filter(pk=employee.pk)

    # Identitas eksekusi: **otoritas penerimanya**, bukan otoritas
    # sistem. Job-nya memang berjalan sebagai sistem, tapi yang
    # diputuskan di sini "boleh tidak orang ini menerima pemberitahuan
    # tentang pegawai itu" — dan itu pertanyaan yang sama persis dengan
    # "boleh tidak ia membuka kartu pegawainya".
    #
    # Karena itu izinnya ikut disebut: cakupan role yang tidak memberi
    # `hr.view_employee` tidak boleh melebarkan siapa yang menerima
    # pemberitahuan tentang seseorang.
    return DataScopeService.filter(
        queryset,
        EMPLOYEE_SCOPE,
        user,
        required_permission=view_permission_for(Employee),
    ).exists()


def _role_holders(role, *, subject_employee):
    """
    Pemegang sebuah role yang berhak melihat pegawai subjeknya.

    Superuser **tidak** ikut otomatis, alasan yang sama dengan
    `EmployeeReminderNotifier.hr_recipients`: akun superuser dipakai
    bergantian developer dan implementor, dan mengisi belnya dengan
    seluruh pemberitahuan tenant membuat bel itu tidak bisa dipakai
    untuk apa pun. Yang mau menerima, beri role-nya.
    """
    if role is None:
        return []

    User = get_user_model()

    holders = (
        User.objects
        .filter(is_active=True, roles=role)
        .distinct()
    )

    return [user for user in holders if _visible_to(user, subject_employee)]


def resolve(
    rule,
    *,
    subject_employee=None,
    submitter=None,
    pending_approvers=None,
    preparers=None,
) -> tuple[list[object], list[str]]:
    """
    Menerjemahkan satu baris aturan jadi daftar User.

    Mengembalikan `(users, alasan_kosong)`. Daftar kosong bukan
    kesalahan — kepala departemen yang belum diisi memang berarti tidak
    ada yang menerima lewat jalur itu — tapi **selalu** disertai alasan,
    karena "kenapa saya tidak dapat pemberitahuannya" harus punya
    jawaban di layar log.
    """
    kind = rule.recipient_type
    skipped: list[str] = []

    if kind == RecipientType.SUBJECT:
        user = _user_of(subject_employee)

        if user is None:
            if subject_employee is None:
                skipped.append(
                    "Pemberitahuan ini tidak menyangkut pegawai tertentu, "
                    "jadi penerima 'Pegawai Bersangkutan' dilewati.",
                )
            else:
                skipped.append(
                    f"Pegawai {subject_employee} belum punya akun aktif, "
                    "jadi tidak bisa menerima pemberitahuan.",
                )

            return [], skipped

        return [user], skipped

    if kind == RecipientType.SUBMITTER:
        if submitter is None:
            skipped.append("Dokumen ini tidak punya pengaju.")

            return [], skipped

        return [submitter], skipped

    if kind == RecipientType.PENDING_APPROVER:
        rows = list(pending_approvers or [])

        if not rows:
            skipped.append(
                "Tidak ada approver yang sedang ditagih pada tahap ini.",
            )

        return rows, skipped

    if kind == RecipientType.PREPARER:
        rows = list(preparers or [])

        if not rows:
            # Bukan kesalahan: alur yang meja pertamanya atasan langsung
            # memang tidak punya "penyiap" yang berbeda dari pengaju.
            skipped.append(
                "Alur ini tidak punya penyiap dokumen yang terpisah dari "
                "pengajunya.",
            )

        return rows, skipped

    if kind == RecipientType.MANAGER:
        from apps.workflow.resolver import manager_of

        if subject_employee is None:
            skipped.append(
                "Pemberitahuan ini tidak menyangkut pegawai tertentu, "
                "jadi atasan langsungnya tidak bisa dicari.",
            )

            return [], skipped

        manager = manager_of(subject_employee, level=rule.manager_level or 1)
        user = _user_of(manager)

        if user is None:
            skipped.append(
                f"Atasan tingkat {rule.manager_level or 1} dari "
                f"{subject_employee} tidak ditemukan atau belum punya "
                "akun. Periksa Reports To pada penempatan organisasinya.",
            )

            return [], skipped

        return [user], skipped

    if kind == RecipientType.DEPARTMENT_HEAD:
        from apps.workflow.resolver import department_head_of

        if subject_employee is None:
            skipped.append(
                "Pemberitahuan ini tidak menyangkut pegawai tertentu, "
                "jadi kepala departemennya tidak bisa dicari.",
            )

            return [], skipped

        head = department_head_of(subject_employee)
        user = _user_of(head)

        if user is None:
            skipped.append(
                f"Department milik {subject_employee} belum punya "
                "pemegang jabatan bertanda Is Manager yang punya akun.",
            )

            return [], skipped

        return [user], skipped

    if kind == RecipientType.ROLE:
        holders = _role_holders(
            rule.role,
            subject_employee=subject_employee,
        )

        if not holders:
            code = getattr(rule.role, "code", "(tanpa role)")

            skipped.append(
                f"Role {code} tidak punya pemegang aktif yang berhak "
                "melihat data pegawai ini. Periksa penugasan role dan "
                "cakupan datanya.",
            )

        return holders, skipped

    if kind == RecipientType.USER:
        user = rule.user

        if user is None or not user.is_active:
            skipped.append("Pengguna yang ditunjuk aturan tidak aktif.")

            return [], skipped

        return [user], skipped

    skipped.append(f"Tipe penerima '{kind}' belum dikenal resolver.")

    return [], skipped


def merge(pairs: list[tuple[object, set[str], str]]) -> list[Recipient]:
    """
    Menggabungkan hasil beberapa aturan jadi satu daftar tanpa duplikat.

    Kanalnya **digabung**, bukan ditimpa: kalau satu aturan memberi
    seseorang email dan aturan lain memberinya bel, ia mendapat
    keduanya. Menimpa berarti hasil akhirnya bergantung urutan baris
    aturan — dan urutan itu tidak terlihat di layar mana pun.

    Alasannya ikut digabung supaya baris log bisa menjelaskan orang itu
    masuk lewat jalur mana; di struktur ramping satu orang lazim jadi
    atasan langsung sekaligus pemegang role HR.
    """
    by_user: dict[object, Recipient] = {}

    for user, channels, reason in pairs:
        key = getattr(user, "pk", None)

        if key is None:
            continue

        existing = by_user.get(key)

        if existing is None:
            by_user[key] = Recipient(
                user=user,
                reason=reason,
                channels=set(channels),
            )

            continue

        existing.channels |= set(channels)

        if reason and reason not in existing.reason:
            existing.reason = f"{existing.reason}; {reason}".strip("; ")

    return list(by_user.values())
