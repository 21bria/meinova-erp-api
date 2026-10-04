"""
Siapa boleh **menerbitkan dokumen atas nama** seorang pegawai.

Lubang yang ditutup berkas ini sama dengan yang sudah ditutup di Shift
Assignment (2 Sep 2026): `BaseMasterViewSet.filter_queryset()` menjaga
baca, ubah, dan hapus, tapi **`create` tidak pernah melewatinya**.
`employee` di body boleh berisi id siapa pun, jadi pegawai bercakupan
`own` bisa mencatat cuti atas nama HR Manager lewat satu request.
Terbukti di tenant demo 17 Sep 2026.

Aturannya
---------

    menerbitkan untuk X  =  izin tulis model  ∧  X ∈ DataScope(izin tulis itu)

* **Cakupan dihitung dari izin yang sedang dipakai** (`hr.add_employeeleave`,
  `hr.change_attendancepermission`, …), bukan dari `hr.view_employee`.
  Satu konteks otorisasi, sama dengan `BaseMasterViewSet.filter_queryset`:
  role yang memberi hak *membaca* daftar pegawai (Finance Manager,
  Executive) tidak otomatis memberi hak *menulis* dokumen HR untuk
  mereka. Di tenant demo, memakai `view_employee` akan membuat Farah
  (EMPLOYEE + FINANCE-MANAGER) boleh mencatat cuti untuk 46 orang;
  memakai izin tulisnya, hanya untuk dirinya.
* **Garis pelaporan tidak ikut.** Sama dengan Adjust Shift: memantau
  tim pekerjaan atasan, menerbitkan dokumen atas nama bawahan bukan —
  kecuali cakupan data role-nya memang memberinya. Aturan "atasan boleh
  mengajukan untuk bawahan langsung" belum ada di sistem ini dan tidak
  dikarang di sini.
* **Dipasang di batas API** (`perform_create`/`perform_update` viewset),
  bukan di service. Service juga dipanggil jalur turunan yang punya
  otorisasinya sendiri — Travel Request menerbitkan cuti RECORDED atas
  nama pemohon dengan `user` = approver terakhir, dan konversi presensi
  menerbitkan cuti DRAFT atas nama pegawai dengan `user` = reviewer.
  Keduanya bukan "pemakai memilih subjek", dan menjaganya di service
  akan memutus keduanya diam-diam.
* **Self Service tidak lewat sini.** `/api/me/*` memanggil service
  langsung dengan subjek dari `CurrentEmployeeService`; subjek itu tidak
  dipilih siapa pun, jadi tidak ada yang perlu dicocokkan dengan cakupan.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.accounts.scoping import DataScopeService

from .scope import EMPLOYEE_SCOPE


def _is_authenticated(user) -> bool:
    return user is not None and bool(getattr(user, "is_authenticated", False))


def writable_employees(user, *, permission: str, queryset=None):
    """Pegawai yang boleh jadi subjek dokumen yang ditulis `user`."""
    if queryset is None:
        from apps.hr.models import Employee

        queryset = Employee.objects.filter(is_deleted=False)

    return DataScopeService.filter(
        queryset,
        EMPLOYEE_SCOPE,
        user,
        required_permission=permission,
    )


def assert_employee_writable(
    *,
    employee,
    user,
    permission: str,
) -> None:
    """
    Menolak dokumen untuk pegawai di luar cakupan tulis penulisnya.

    Pesannya menempel di kolom `employee`, sama dengan `assert_adjustable`.
    `user` kosong/anonim dilewati — jalur sistem, bukan seseorang.
    """
    if employee is None:
        return

    if not _is_authenticated(user):
        return

    if getattr(user, "is_superuser", False):
        return

    # Serializer mengoper instance, pemanggil internal kadang pk.
    employee_id = getattr(employee, "pk", employee)

    allowed = (
        writable_employees(user, permission=permission)
        .filter(pk=employee_id)
        .exists()
    )

    if allowed:
        return

    label = getattr(employee, "employee_number", None) or f"#{employee_id}"

    raise ValidationError(
        {
            "employee": (
                f"Pegawai {label} berada di luar cakupan data Anda, "
                "jadi dokumen atas namanya tidak bisa dibuat dari sini."
            ),
        },
    )


def assert_employee_change_writable(
    *,
    instance,
    data: dict,
    user,
    permission: str,
) -> None:
    """
    Update yang **memindahkan** dokumen ke pegawai lain adalah penerbitan
    yang menyamar jadi penyuntingan — pegawai penggantinya diperiksa
    seperti create. Baris lamanya sudah dijaga `filter_queryset()`.
    """
    if "employee" not in data:
        return

    new = data.get("employee")

    new_id = getattr(new, "pk", new)

    if new_id is None or new_id == instance.employee_id:
        return

    assert_employee_writable(employee=new, user=user, permission=permission)


class EmployeeSubjectWriteGuardMixin:
    """
    Menjaga `employee` di body pada create/update viewset HR.

    Dipasang **di depan** `ServiceWriteMixin`:

        class EmployeeLeaveViewSet(
            EmployeeSubjectWriteGuardMixin,
            ServiceWriteMixin,
            BaseMasterViewSet,
        ):
            ...

    Izin yang dipakai menghitung cakupan diturunkan dari model viewset
    (`<app>.add_<model>` / `<app>.change_<model>`) — nama yang sama
    dengan yang barusan diloloskan `ModelPermission`.
    """

    def _subject_permission(self, action: str) -> str:
        model = self.get_queryset().model
        meta = model._meta

        return f"{meta.app_label}.{action}_{meta.model_name}"

    def _subject_user(self):
        user = getattr(self.request, "user", None)

        return user if _is_authenticated(user) else None

    def perform_create(self, serializer):
        assert_employee_writable(
            employee=serializer.validated_data.get("employee"),
            user=self._subject_user(),
            permission=self._subject_permission("add"),
        )

        super().perform_create(serializer)

    def perform_update(self, serializer):
        assert_employee_change_writable(
            instance=serializer.instance,
            data=serializer.validated_data,
            user=self._subject_user(),
            permission=self._subject_permission("change"),
        )

        super().perform_update(serializer)
