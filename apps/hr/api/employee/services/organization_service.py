from __future__ import annotations

from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.scoping import DataScopeService
from apps.hr.models import (
    Employee,
    OrganizationAssignment,
)


# Kolom penempatan yang tidak boleh berubah lewat form Employee begitu
# pegawainya sudah ada. Alasannya sama persis dengan `PROTECTED_FIELDS`
# di `EmploymentService` sebelah, dan sengaja ditulis dengan pola yang
# sama supaya keduanya dibaca sebagai satu aturan: `OrganizationAssignment`
# cuma menyimpan **keadaan sekarang**, satu baris per pegawai. Menimpanya
# lewat form berarti penempatan lama hilang tanpa satu baris pun yang
# bisa ditunjuk — dan mutasi jadi peristiwa yang tidak pernah terjadi
# menurut database.
#
# Itu bukan kekhawatiran teoretis: sebelum penjagaan ini ada, satu PATCH
# ke form Employee sudah cukup memindahkan orang antarperusahaan tanpa
# dokumen, tanpa persetujuan, dan tanpa jejak audit sama sekali —
# `EmployeeService` bukan turunan `BaseService`, jadi `_audit()` pun
# tidak pernah menulis apa-apa untuk jalur ini.
#
# Saat **create** kolom ini bebas diisi: itu penempatan awal, belum ada
# sejarah yang bisa hilang. Yang dikunci hanya perubahan sesudahnya, dan
# jalurnya `EmployeeAction`.
#
# Sengaja **tidak** memuat:
#
# * `reports_to` — garis pelaporan adalah koreksi data, bukan mutasi.
#   Employee Reporting Audit memang ada untuk memunculkan yang kosong
#   supaya HR membetulkannya langsung, dan satu atasan yang resign
#   berarti seluruh bawahannya harus dialihkan; memaksanya lewat dua
#   puluh dokumen persetujuan bukan penjagaan, itu kemacetan.
# * `cost_center` — dimensi biaya, bukan penempatan orang. Tidak ada
#   satu pun suku Manpower Movement yang membacanya.
# * `organization_effective_date` dan `organization_notes` — keduanya
#   keterangan atas penempatan, bukan penempatannya.
PROTECTED_FIELDS = {
    "company": "Company",
    "branch": "Branch",
    "location": "Location",
    "division": "Division",
    "department": "Department",
    "section": "Section",
    "position": "Position",
    "job_level": "Job Level",
    "job_grade": "Job Grade",
}


# Jenis Employee Action yang menerbitkan tiap kolom terkunci — dipakai
# menyusun pesan penolakan, pola yang sama dengan
# `PROTECTED_FIELD_ACTIONS` milik `EmploymentService`.
PROTECTED_FIELD_ACTIONS = {
    "company": "Transfer",
    "branch": "Transfer",
    "location": "Transfer",
    "division": "Transfer",
    "department": "Transfer / Promotion",
    "section": "Transfer / Promotion",
    "position": "Promotion / Demotion / Position Change / Transfer",
    "job_level": "Promotion / Demotion / Position Change",
    "job_grade": "Promotion / Demotion / Position Change",
}


class OrganizationService:
    FIELDS = {
        "company",
        "branch",
        "location",
        "division",
        "department",
        "section",
        "position",
        "job_level",
        "job_grade",
        "reports_to",
        "cost_center",
        # "project" dibuang: tidak pernah ada kolomnya di
        # `OrganizationAssignment`, jadi kalau nilainya sempat lolos ke
        # sini `setattr` cuma menempelkannya ke atribut yang tidak
        # pernah disimpan.
        "organization_effective_date",
        "organization_notes",
    }

    @classmethod
    def extract(
        cls,
        validated_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: validated_data.pop(key)
            for key in list(validated_data.keys())
            if key in cls.FIELDS
        }

    # Kolom penempatan yang bisa disimpulkan dari cakupan pembuatnya.
    # `position`, `reports_to`, dan kawan-kawan tidak termasuk: itu
    # keputusan, bukan konsekuensi dari siapa yang mengetik.
    SCOPED_FIELDS = {
        "company",
        "branch",
        "location",
        "division",
        "department",
        "section",
        "cost_center",
    }

    @classmethod
    def apply_scope_defaults(
        cls,
        data: dict[str, Any],
        user,
        *,
        assignment: OrganizationAssignment | None = None,
    ) -> list[str]:
        """
        Isi kolom penempatan yang kosong dari cakupan pembuatnya.

        Tanpa ini, admin yang cakupannya satu lokasi bisa menyimpan
        pegawai tanpa Location — dan pegawai itu **seketika hilang dari
        layarnya sendiri**, karena baris berkolom kosong tidak terlihat
        siapa pun (`DATA_SCOPE_INCLUDE_NULL`). Tersimpan 201 lalu 404;
        tidak ada pesan yang menjelaskannya.

        Hanya yang kosong, dan hanya kalau cakupannya menunjuk **satu**
        nilai. Isian pemakai selalu menang — ini pengisian bawaan,
        bukan penguncian: admin site yang memang harus memindahkan
        seseorang tetap ditolak `OrganizationAssignment.clean()` dan
        oleh cakupannya sendiri, bukan diam-diam di sini.
        """
        implied = DataScopeService.implied_values(user)

        if not implied:
            return []

        filled = []

        for name in cls.SCOPED_FIELDS:
            if name not in implied:
                continue

            # Sudah disebut di kiriman — termasuk kalau disebut kosong
            # secara sengaja — jangan disentuh.
            if data.get(name) is not None:
                continue

            if assignment is not None and getattr(assignment, f"{name}_id", None):
                continue

            data[f"{name}_id"] = implied[name]

            filled.append(name)

        if filled:
            cls._fill_parents(data, filled)

            # `OrganizationAssignment` mewajibkannya, dan penempatan yang
            # dibuatkan di sini memang berlaku sejak hari ini. Tanpa ini
            # seluruh pengisian bawaan gagal 400 di kolom yang bukan
            # kolom yang sedang diisi.
            if not data.get("organization_effective_date"):
                data["organization_effective_date"] = date.today()

        return filled

    @classmethod
    def _fill_parents(cls, data: dict[str, Any], filled: list[str]) -> None:
        """
        Lengkapi induk dari nilai yang baru diisikan.

        Bukan tebakan: Company dan Branch sebuah Location adalah fakta
        yang tersimpan di masternya. Tanpa ini pengisian bawaan
        menghasilkan penempatan yang Location-nya terisi tapi
        Company-nya kosong — dan Company itu satu-satunya kolom yang
        wajib di seluruh struktur ini.
        """
        from apps.administration.models import (
            Department,
            Location,
            Section,
        )

        sources = [
            ("location", Location, ("company", "branch")),
            ("department", Department, ("company", "branch", "location", "division")),
            ("section", Section, ("company", "department")),
        ]

        for name, model, parents in sources:
            if name not in filled:
                continue

            node = model.objects.filter(pk=data.get(f"{name}_id")).first()

            if node is None:
                continue

            for parent in parents:
                if data.get(parent) is not None or data.get(f"{parent}_id"):
                    continue

                value = getattr(node, f"{parent}_id", None)

                if value is not None:
                    data[f"{parent}_id"] = value

    @classmethod
    def assert_not_protected(
        cls,
        *,
        assignment: OrganizationAssignment,
        payload: dict[str, Any],
    ) -> None:
        """
        Menolak perpindahan penempatan lewat form Employee.

        Diperiksa dengan **membandingkan**, bukan dengan melihat kunci
        mana yang dikirim: form mengirim seluruh isi tab Organization apa
        adanya, termasuk nilai yang barusan dibacanya dari API. Menolak
        setiap kiriman yang memuat kuncinya akan membuat menyimpan
        perubahan Organization Notes pun ditolak dengan alasan mutasi.
        """
        blocked = []

        for field_name, label in PROTECTED_FIELDS.items():
            if field_name not in payload:
                continue

            proposed = payload[field_name]

            current = getattr(assignment, field_name, None)

            # FK dibandingkan lewat pk — instance-nya berbeda objek
            # walau menunjuk baris yang sama.
            if hasattr(proposed, "pk") or hasattr(current, "pk"):
                changed = (
                    getattr(proposed, "pk", None)
                    != getattr(current, "pk", None)
                )
            else:
                changed = proposed != current

            if changed:
                blocked.append((field_name, label))

        if not blocked:
            return

        raise ValidationError(
            {
                field_name: (
                    f"{label} tidak bisa diubah langsung dari form "
                    "Employee — penempatan lamanya akan hilang tanpa "
                    "jejak. Ajukan lewat Employee Action "
                    f"({PROTECTED_FIELD_ACTIONS[field_name]})."
                )
                for field_name, label in blocked
            },
        )

    @classmethod
    @transaction.atomic
    def save(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
        via_action: bool = False,
    ) -> OrganizationAssignment | None:
        """
        `via_action=True` melewati penjagaan kolom terkunci.

        Disediakan untuk jalur yang memang sudah membekukan nilai
        sebelumnya dan sudah melewati persetujuan. `EmployeeActionService`
        sendiri tidak memakainya — ia menulis `OrganizationAssignment`
        langsung di `_apply_organization()` karena butuh semantik
        "kolom yang tidak diusulkan jangan ikut dikosongkan". Jadi
        penjagaan di sini memang hanya menutup jalur form, dan itu
        justru jalur yang mau ditutup.
        """
        assignment = (
            OrganizationAssignment.objects
            .select_for_update()
            .filter(employee=employee)
            .first()
        )

        created = assignment is None

        if created:
            assignment = OrganizationAssignment(
                employee=employee,
            )

        if created and user is not None:
            # Dipanggil di sini, bukan di serializer: jalur API langsung
            # dan importer sama-sama lewat service, dan pegawai yang
            # tidak terlihat pembuatnya adalah masalah yang sama dari
            # jalur mana pun ia datang.
            cls.apply_scope_defaults(data, user)

        if not data:
            return None

        if not created and not via_action:
            # Hanya untuk penempatan yang sudah ada. Pegawai baru boleh
            # membawa penempatan awalnya — belum ada sejarah yang bisa
            # hilang.
            cls.assert_not_protected(
                assignment=assignment,
                payload=data,
            )

        for key, value in data.items():
            setattr(assignment, key, value)

        if user is not None:
            if created:
                assignment.created_by = user

            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        return assignment