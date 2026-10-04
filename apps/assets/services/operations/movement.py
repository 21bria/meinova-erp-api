"""
Penolong bersama dokumen pergerakan aset (Assignment, Return, kelak
Transfer).

Hanya fungsi tanpa keadaan. Dokumen tidak saling mengimpor service —
yang dibagi ada di sini (dan pemesanan di `reservation.py`).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError

from apps.assets.models import Asset


def key(value):
    """Nilai pembanding untuk kolom biasa maupun FK."""
    return getattr(value, "pk", value)


def reject_system_fields(
    data: dict[str, Any],
    system_fields,
    *,
    instance=None,
) -> None:
    """
    Kolom yang diisi sistem tidak boleh dikirim — juga lewat jalur
    non-HTTP yang memanggil service langsung. Nilai sama dengan yang
    tersimpan (serializer mengirim ulang kolom read-only) bukan pelanggaran.
    """
    sent = [
        name for name in system_fields
        if name in data
        and data[name] not in (None, "")
        and (
            instance is None
            or key(data[name]) != key(getattr(instance, name))
        )
    ]

    if sent:
        raise ValidationError({
            name: "Diisi sistem, tidak bisa dikirim." for name in sent
        })


def assert_may(user, permission: str, action: str) -> None:
    """
    Izin aksi alur dicek di service, bukan hanya di viewset. `user=None`
    = pemanggil sistem (seed/import/integrasi), sama seperti service lain
    di repo ini.
    """
    if user is None:
        return

    if not user.has_perm(permission):
        raise PermissionDenied(f"Anda tidak punya hak {action}.")


def lock_asset(asset_id) -> Asset:
    """
    Kunci baris aset (`of=("self",)` — `select_related` ke FK nullable
    membuat LEFT JOIN, dan FOR UPDATE tidak boleh mengenai sisinya).
    """
    asset = (
        Asset.objects
        .select_for_update(of=("self",))
        .select_related("category", "current_custody")
        .filter(pk=asset_id, is_deleted=False)
        .first()
    )

    if asset is None:
        raise ValidationError({"asset": "Aset tidak ditemukan atau sudah dihapus."})

    return asset


# ----------------------------------------------------------------------
# Tujuan pemakaian (EMPLOYEE / ORGANIZATION)
# ----------------------------------------------------------------------

# Nama kolom error bawaan — kolom dokumen Assignment. Dokumen lain
# (Transfer) mengirim petanya sendiri supaya pesan menempel di kolomnya.
HOLDER_KEYS = {
    "custody_type": "target_custody_type",
    "employee": "employee",
    "department": "department",
    "pic": "pic_employee",
    "location": "location",
    "facility": "facility",
    "reason": "cross_company_reason",
}


def resolve_holder(
    *,
    asset,
    custody_type,
    employee,
    department,
    pic,
    location,
    facility,
    reason,
    on,
    keys=None,
) -> dict:
    """
    Validasi tujuan **pemakaian** dan turunkan jejak organisasi penerima —
    aturan yang sama untuk Assignment dan Transfer (§9, §10):

    * jenis tujuan diizinkan kapabilitas kategori;
    * lokasi/fasilitas milik company pemilik (juga untuk penerima lintas
      company — O-8);
    * EMPLOYEE: pegawai aktif berpenempatan aktif pada `on`, tanpa
      department/PIC; lintas company wajib beralasan;
    * ORGANIZATION: department milik pemilik, tanpa pegawai; PIC opsional,
      aktif, dan berpenempatan di company pemilik.

    Mengembalikan `employee_company/location/department`,
    `is_cross_company`, `cross_company_reason` (dinormalisasi). Penempatan
    dibaca dari `OrganizationAssignment`, tidak pernah ditulis.
    """
    from apps.assets.models import CustodyType

    keys = {**HOLDER_KEYS, **(keys or {})}
    errors: dict[str, str] = {}
    reason = (reason or "").strip()

    category = asset.category

    if custody_type == CustodyType.EMPLOYEE:
        if not category.allow_employee_custody:
            errors[keys["custody_type"]] = (
                "Kategori aset ini tidak boleh dipegang pegawai."
            )
    elif custody_type == CustodyType.ORGANIZATION:
        if not category.allow_organization_custody:
            errors[keys["custody_type"]] = (
                "Kategori aset ini tidak boleh dipegang unit organisasi."
            )
    else:
        errors[keys["custody_type"]] = "Pilih EMPLOYEE atau ORGANIZATION."

    if location is None:
        errors[keys["location"]] = "Lokasi tujuan wajib diisi."
    elif location.company_id != asset.company_id:
        errors[keys["location"]] = (
            "Lokasi tujuan harus milik company pemilik aset — juga untuk "
            "penerima dari company lain."
        )

    if facility is not None and location is not None:
        if facility.company_id != asset.company_id:
            errors[keys["facility"]] = "Fasilitas bukan milik company pemilik aset."
        elif facility.location_id != location.pk:
            errors[keys["facility"]] = "Fasilitas tidak berada di lokasi tujuan."

    derived = {
        "employee_company": None,
        "employee_location": None,
        "employee_department": None,
        "is_cross_company": False,
        "cross_company_reason": "",
    }

    if custody_type == CustodyType.EMPLOYEE:
        if department is not None:
            errors[keys["department"]] = "Custody pegawai tidak memakai department."
        if pic is not None:
            errors[keys["pic"]] = "Custody pegawai tidak memakai PIC."

        if employee is None:
            errors[keys["employee"]] = "Pegawai penerima wajib dipilih."
        else:
            organization, problem = active_placement(employee, on)

            if problem:
                errors[keys["employee"]] = problem
            else:
                cross = organization.company_id != asset.company_id

                derived.update({
                    "employee_company": organization.company,
                    "employee_location": organization.location,
                    "employee_department": organization.department,
                    "is_cross_company": cross,
                    "cross_company_reason": reason if cross else "",
                })

                # O-8: lintas company boleh, tapi tidak pernah diam-diam.
                if cross and not reason:
                    errors[keys["reason"]] = (
                        "Penerima berpenempatan di company lain. Isi "
                        "alasan penyerahan lintas company."
                    )

    elif custody_type == CustodyType.ORGANIZATION:
        if employee is not None:
            errors[keys["employee"]] = (
                "Custody organisasi tidak punya pegawai pemegang — "
                "gunakan PIC."
            )

        if department is None:
            errors[keys["department"]] = "Department tujuan wajib dipilih."
        elif department.company_id != asset.company_id:
            errors[keys["department"]] = "Department bukan milik company pemilik aset."

        if pic is not None:
            organization, problem = active_placement(pic, on)

            if problem:
                errors[keys["pic"]] = problem
            elif organization.company_id != asset.company_id:
                # O-8 hanya untuk pegawai pemegang. PIC adalah penanggung
                # jawab resmi unit pemilik — harus orang company itu.
                errors[keys["pic"]] = (
                    "PIC harus berpenempatan di company pemilik aset."
                )

    if errors:
        raise ValidationError(errors)

    return derived


def active_placement(employee, on):
    """
    `(OrganizationAssignment, None)` untuk pegawai yang aktif pada
    tanggal `on`, atau `(None, alasan)`.

    Aturan "masih bekerja" sama dengan dashboard HR: tanpa
    `termination_date`, atau terminasinya sesudah tanggal itu.
    """
    from django.core.exceptions import ObjectDoesNotExist

    if employee.is_deleted or not employee.is_active:
        return None, "Pegawai tidak aktif."

    try:
        employment = employee.employment
    except ObjectDoesNotExist:
        employment = None

    if (
        employment is not None
        and employment.termination_date is not None
        and employment.termination_date <= on
    ):
        return None, "Pegawai sudah tidak bekerja pada tanggal itu."

    try:
        organization = employee.organization
    except ObjectDoesNotExist:
        organization = None

    if (
        organization is None
        or organization.is_deleted
        or not organization.is_active
        or organization.company_id is None
        or organization.organization_effective_date > on
    ):
        return None, "Pegawai belum punya penempatan organisasi yang aktif."

    return organization, None
