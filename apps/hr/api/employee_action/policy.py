"""
Membaca `EmployeeActionPolicy`: siapa yang boleh mengusulkan apa.

Dipisah dari service karena dijawab di tiga tempat — saat dokumennya
dibuat, saat diajukan, dan saat form menentukan apakah kolom
"Requested By" wajib diisi.

Fungsinya murni: masukkan pegawai + jenis action + calon pengusul,
keluar boleh/tidak **plus alasannya**. Alasan selalu ikut karena
penolakan "Anda tidak boleh mengajukan ini" tanpa menyebut siapa yang
boleh membuat orangnya menebak, lalu menghubungi IT.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.administration.models import (
    ActionInitiator,
    EmployeeActionPolicy,
)


@dataclass(frozen=True)
class InitiatorVerdict:
    allowed: bool
    reason: str

    # Diisi kalau yang mengetik bukan pengusul yang sah, tapi boleh
    # mengetikkan atas nama orang lain. Form memakainya untuk
    # mewajibkan kolom Requested By.
    requires_requested_by: bool = False


class EmployeeActionPolicyResolver:
    @staticmethod
    def match(*, employee, action_type: str) -> EmployeeActionPolicy | None:
        """
        Aturan paling khusus yang cocok untuk pegawai ini.

        Dipilih lewat skor `specificity`, bukan urutan baris — siapa
        yang boleh mengusulkan kenaikan gaji seseorang tidak boleh
        bergantung pada nomor id di database.
        """
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        company_id = getattr(organization, "company_id", None)
        location_id = getattr(organization, "location_id", None)
        group_id = getattr(employment, "employee_group_id", None)

        candidates = (
            EmployeeActionPolicy.objects
            .filter(
                action_type=action_type,
                is_deleted=False,
                is_active=True,
            )
            .select_related("initiator_role", "on_behalf_role")
        )

        matched = [
            policy
            for policy in candidates
            # Aturan yang menyebut sasaran tertentu hanya berlaku untuk
            # sasaran itu; yang mengosongkannya berlaku untuk semua.
            if (not policy.company_id or policy.company_id == company_id)
            and (not policy.location_id or policy.location_id == location_id)
            and (
                not policy.employee_group_id
                or policy.employee_group_id == group_id
            )
        ]

        if not matched:
            return None

        return max(matched, key=lambda policy: policy.specificity)

    # ------------------------------------------------------------------
    # Kelayakan pengusul
    # ------------------------------------------------------------------

    @classmethod
    def qualifies(cls, *, employee, policy, candidate) -> bool:
        """
        Apakah `candidate` (Employee) sah sebagai pengusul.

        Dinilai terhadap **pegawai yang datanya diubah**, bukan
        terhadap yang mengetik — atasan yang dimaksud adalah atasannya,
        bukan atasan orang HR yang membuka form.
        """
        if candidate is None:
            return False

        kind = policy.initiator_type

        if kind == ActionInitiator.ANY:
            return True

        if kind == ActionInitiator.EMPLOYEE:
            return candidate.pk == employee.pk

        if kind == ActionInitiator.MANAGER:
            organization = getattr(employee, "organization", None)

            return (
                getattr(organization, "reports_to_id", None)
                == candidate.pk
            )

        if kind == ActionInitiator.DEPARTMENT_HEAD:
            return cls._is_department_head(
                employee=employee,
                candidate=candidate,
            )

        if kind == ActionInitiator.ROLE:
            user = getattr(candidate, "user", None)

            if user is None:
                return False

            return user.roles.filter(
                pk=policy.initiator_role_id,
                is_deleted=False,
            ).exists()

        return False

    @staticmethod
    def _is_department_head(*, employee, candidate) -> bool:
        """
        Pemegang jabatan bertanda Manager di department pegawainya.

        Aturannya sama persis dengan `ApproverType.DEPARTMENT_HEAD` di
        engine workflow — kalau berbeda, orang yang boleh mengusulkan
        dan orang yang menandatangani meja pertama bisa dua orang yang
        berlainan tanpa ada yang menyadarinya.
        """
        organization = getattr(employee, "organization", None)
        department_id = getattr(organization, "department_id", None)

        if department_id is None:
            return False

        candidate_org = getattr(candidate, "organization", None)

        if candidate_org is None:
            return False

        if candidate_org.department_id != department_id:
            return False

        position = getattr(candidate_org, "position", None)

        return bool(getattr(position, "is_manager", False))

    # ------------------------------------------------------------------
    # Putusan
    # ------------------------------------------------------------------

    @classmethod
    def check(
        cls,
        *,
        employee,
        action_type: str,
        actor_employee,
        requested_by=None,
        actor_user=None,
    ) -> InitiatorVerdict:
        """
        Boleh atau tidak, dan kenapa.

        `actor_employee` = pegawai milik akun yang sedang mengetik
        (boleh None untuk akun yang bukan pegawai, mis. admin sistem).
        `requested_by` = pengusul yang disebut di dokumennya.
        """
        policy = cls.match(employee=employee, action_type=action_type)

        # Tidak ada aturan sama sekali = perilaku lama: yang punya izin
        # model boleh mengajukan. Master yang belum diseed tidak boleh
        # mengunci seluruh modul.
        if policy is None:
            return InitiatorVerdict(
                allowed=True,
                reason="Belum ada aturan pengusul untuk jenis ini.",
            )

        if policy.initiator_type == ActionInitiator.ANY:
            return InitiatorVerdict(
                allowed=True,
                reason=f"{policy.code}: siapa pun yang punya izin.",
            )

        expected = policy.get_initiator_type_display()

        # Pengusul yang disebut dokumen menang atas siapa yang mengetik
        # — itu memang gunanya kolom itu.
        proposer = requested_by or actor_employee

        if cls.qualifies(
            employee=employee,
            policy=policy,
            candidate=proposer,
        ):
            # Yang mengetik memang pengusulnya: tidak perlu menyebut
            # siapa-siapa lagi.
            if (
                actor_employee is not None
                and proposer.pk == actor_employee.pk
            ):
                return InitiatorVerdict(
                    allowed=True,
                    reason=f"{policy.code}: pengusul sah ({expected}).",
                )

            # Diketik orang lain atas nama pengusul yang sah.
            if not policy.allow_on_behalf:
                return InitiatorVerdict(
                    allowed=False,
                    reason=(
                        f"{policy.code}: usulan {expected} harus dibuat "
                        f"sendiri oleh yang bersangkutan, tidak boleh "
                        f"diwakilkan."
                    ),
                )

            if not cls._may_type_on_behalf(policy=policy, user=actor_user):
                return InitiatorVerdict(
                    allowed=False,
                    reason=(
                        f"{policy.code}: yang boleh mengetikkan atas "
                        f"nama orang lain hanya pemegang role "
                        f"{policy.on_behalf_role.code}."
                    ),
                )

            return InitiatorVerdict(
                allowed=True,
                reason=(
                    f"{policy.code}: diketik atas nama "
                    f"{proposer.full_name} ({expected})."
                ),
            )

        # Pengusulnya tidak sah. Dua kemungkinan, dan pesannya harus
        # membedakannya: kolomnya belum diisi, atau diisi orang yang
        # bukan pengusul yang dimaksud.
        if requested_by is None:
            return InitiatorVerdict(
                allowed=False,
                requires_requested_by=policy.allow_on_behalf,
                reason=(
                    f"{policy.code}: usulan {expected}. Isi Requested "
                    f"By dengan orang yang mengusulkannya."
                    if policy.allow_on_behalf
                    else
                    f"{policy.code}: hanya {expected} yang boleh "
                    f"mengajukan jenis ini."
                ),
            )

        return InitiatorVerdict(
            allowed=False,
            reason=(
                f"{policy.code}: {requested_by.full_name} bukan "
                f"{expected} dari {employee.full_name}."
            ),
        )

    @staticmethod
    def _may_type_on_behalf(*, policy, user) -> bool:
        # Tidak dibatasi role tertentu = siapa pun yang sudah lolos
        # izin model `hr.add_employeeaction`.
        if policy.on_behalf_role_id is None:
            return True

        if user is None:
            return False

        if getattr(user, "is_superuser", False):
            return True

        return user.roles.filter(
            pk=policy.on_behalf_role_id,
            is_deleted=False,
        ).exists()
