"""
Mencari siapa yang berhak menyetujui satu step.

Dipisah dari service karena inilah bagian yang paling bergantung pada
kelengkapan data tenant, dan yang paling sering harus dijelaskan ke
pengguna saat hasilnya kosong. Fungsinya murni: masukkan pegawai +
step, keluar daftar approver — tidak menyentuh status dokumen apa pun.

Kenapa ada lima tipe, bukan satu
--------------------------------
Garis pelaporan (`OrganizationAssignment.reports_to`) adalah jawaban
paling akurat, tapi di tenant yang datanya belum lengkap kolom itu
kosong seluruhnya — dan approval yang tidak bisa menemukan siapa pun
berarti tidak ada satu dokumen pun yang bisa diajukan. Karena itu tiap
step boleh menyebut `fallback_role`.

Yang **tidak** dilakukan di sini: menebak. Kalau rantainya putus dan
tidak ada fallback, hasilnya kosong dan step-nya gagal dengan pesan
yang menyebut persis kolom mana yang kosong. Approval yang diam-diam
melompat ke orang lain jauh lebih berbahaya daripada pengajuan yang
ditolak dengan alasan jelas.

Approver di sini adalah **User**, bukan Employee: yang menekan tombol
adalah akun, dan kotak masuk disusun per akun. Pegawainya ikut dibawa
untuk dicetak di kotak tanda tangan.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from apps.workflow.models import ApproverScope, ApproverType, AssignmentType


# Pagar terhadap struktur organisasi yang menunjuk dirinya sendiri —
# A melapor ke B, B melapor ke A. Datanya tidak dijaga di level model,
# jadi penelusurannya yang harus berhenti sendiri.
MAX_CHAIN_DEPTH = 10


@dataclass(frozen=True)
class Candidate:
    """Satu calon approver, plus dari mana namanya datang."""

    user: object
    employee: object | None
    assignment_type: str
    reason: str

    # Jejak resolusi, dibekukan ke `WorkflowApproval.metadata` saat
    # kotak tanda tangannya dibuat.
    #
    # `reason` sudah menjelaskannya dalam kalimat, dan itu yang dibaca
    # orang — tapi kalimat tidak bisa disaring, dihitung, atau
    # dibandingkan antar dokumen. "Berapa banyak pengajuan site yang
    # jatuh ke Admin Department karena section-nya belum punya admin"
    # adalah pertanyaan yang menentukan baris master mana yang harus
    # diisi lebih dulu, dan menjawabnya dari teks bebas berarti
    # mencocokkan kalimat yang boleh berubah kapan saja.
    resolution_source: str = ""
    resolved_role: str = ""
    resolved_scope: str = ""
    resolved_scope_object: str = ""
    resolved_scope_object_id: object = None


@dataclass
class ResolvedApprovers:
    """
    Hasil penelusuran satu step.

    `reason` selalu terisi, termasuk saat berhasil — dipakai untuk
    menjelaskan ke pengguna dari mana nama itu datang, dan (saat gagal)
    kolom mana yang perlu diisi.
    """

    candidates: list[Candidate] = dataclass_field(default_factory=list)
    reason: str = ""

    @property
    def found(self) -> bool:
        return bool(self.candidates)


# ----------------------------------------------------------------------
# Penelusuran
# ----------------------------------------------------------------------


def _organization_of(employee):
    return getattr(employee, "organization", None)


def _walk_reports_to(employee, level: int):
    """Naik `level` tingkat lewat garis pelaporan antarorang."""
    current = employee

    for _ in range(min(level, MAX_CHAIN_DEPTH)):
        organization = _organization_of(current)

        if organization is None or not organization.reports_to_id:
            return None, current

        current = organization.reports_to

        # Rantai yang berputar. Berhenti dan laporkan sebagai tidak
        # ketemu, bukan berputar sampai batas kedalaman — hasilnya
        # sama-sama gagal, tapi ini menyebut sebabnya.
        if current.pk == employee.pk:
            return None, current

    return current, current


def _walk_position(employee, step):
    """
    Naik `level` tingkat lewat hierarki jabatan, lalu ambil pemegang
    jabatan itu.

    Satu jabatan bisa dipegang beberapa orang (headcount > 1). Yang
    diambil yang penempatannya paling baru — bukan yang pertama
    ditemukan, karena urutan tanpa aturan berarti approver bisa
    berpindah orang antar pengajuan tanpa ada yang mengubah apa pun.
    """
    from apps.hr.models import OrganizationAssignment

    if step.approver_position_id:
        position = step.approver_position
    else:
        organization = _organization_of(employee)

        if organization is None or not organization.position_id:
            return None

        position = organization.position

        for _ in range(min(step.level, MAX_CHAIN_DEPTH)):
            if not position.reports_to_id:
                return None

            position = position.reports_to

    holder = (
        OrganizationAssignment.objects
        .filter(
            position=position,
            is_active=True,
            is_deleted=False,
        )
        .exclude(employee=employee)
        .select_related("employee")
        .order_by("-organization_effective_date", "-id")
        .first()
    )

    return holder.employee if holder else None


def _department_manager(employee):
    """Pemegang jabatan bertanda `is_manager` di department pegawai."""
    from apps.hr.models import OrganizationAssignment

    organization = _organization_of(employee)

    if organization is None or not organization.department_id:
        return None

    holder = (
        OrganizationAssignment.objects
        .filter(
            department=organization.department,
            position__is_manager=True,
            is_active=True,
            is_deleted=False,
        )
        .exclude(employee=employee)
        .select_related("employee")
        .order_by("-organization_effective_date", "-id")
        .first()
    )

    return holder.employee if holder else None


def _scope_value(organization, scope: str):
    """
    Nilai penempatan yang dipakai menyaring, diambil dari pegawai subjek.

    `None` berarti tidak ada yang bisa dibandingkan — pemanggilnya yang
    memutuskan itu jadi "tanpa saringan" atau "gagal dengan alasan".
    """
    if organization is None:
        return None

    return getattr(organization, f"{scope}_id", None)


def _scope_label(scope: str, organization) -> str:
    """
    Potongan kalimat yang menjelaskan sejauh mana pencariannya.

    Ikut dicetak saat **berhasil**, bukan hanya saat gagal: "kenapa yang
    tanda tangan orang ini" adalah pertanyaan yang muncul jauh lebih
    sering daripada "kenapa kosong", dan jawabannya harus ada di jejak
    dokumennya sendiri.
    """
    from apps.workflow.models import ApproverScope

    if not scope or scope == ApproverScope.COMPANY:
        return "di company yang sama"

    if scope == ApproverScope.TENANT:
        return "di seluruh tenant"

    label = ApproverScope(scope).label

    if organization is None:
        return f"di {label} yang sama — pegawainya belum punya penempatan"

    value = getattr(organization, scope, None)

    if value is None:
        return f"di {label} yang sama — kolom {label} pegawai masih kosong"

    return f"di {label} {value}"


def _source_token(value: str) -> str:
    """
    Kode role jadi penanda sumber yang bisa disaring.

    `ADMIN-SECTION` → `ADMIN_SECTION`. Diturunkan, bukan didaftar per
    alur: daftar penanda yang ditulis tangan akan ketinggalan begitu ada
    tenant yang menamai role-nya sendiri, dan penanda yang tidak pernah
    muncul tidak bisa dibedakan dari keadaan yang memang tidak pernah
    terjadi.
    """
    return (
        str(value or "")
        .strip()
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _scope_object(scope: str, organization, company):
    """
    Unit organisasi yang jadi batas pencarian, sebagai `(label, id)`.

    Dipisah dari `_scope_label` yang merakit kalimat: yang ini dibekukan
    ke jejak dokumen dan dibaca mesin, jadi isinya harus nilai — bukan
    potongan kalimat yang ikut berubah setiap kali pesannya diperbaiki.
    """
    from apps.workflow.models import ApproverScope

    # Kosong = cakupan memang tidak dikonsultasi sama sekali — tipe
    # Manager dan Position menelusuri relasi, bukan menyaring unit
    # organisasi. Mengisinya dengan company akan terbaca di jejak
    # dokumen seolah pencariannya dibatasi ke perusahaan itu, dan itu
    # keterangan yang salah tentang cara approver-nya ditemukan.
    if not scope or scope == ApproverScope.TENANT:
        return "", None

    if scope == ApproverScope.COMPANY:
        value = company or getattr(organization, "company", None)
    else:
        value = getattr(organization, scope, None)

    if value is None:
        return "", None

    return str(value), getattr(value, "pk", None)


def _role_holders(
    role,
    *,
    company=None,
    exclude_employee=None,
    scope=None,
    organization=None,
):
    """
    Semua pegawai yang akun penggunanya memegang role ini.

    Disaring ke **satu tingkat organisasi** milik pegawai subjek, bukan
    selalu company. Berhenti di company terlalu longgar begitu satu
    perusahaan punya beberapa site: "KTT Site" akan menarik KTT seluruh
    site dan pengajuan Gebe mendarat di kotak masuk orang Halmahera —
    kebocoran yang tidak berbunyi, karena dokumennya memang tampil, cuma
    di meja yang salah.

    Tingkatnya ditentukan `WorkflowStep.approver_scope`, jadi satu
    definisi alur bisa mencampur meja per-site (Location) dengan meja
    lintas-site (Company) — HRGA duduk di kantor pusat tapi membelikan
    tiket untuk semua orang.

    Dikembalikan sebagai daftar, bukan satu orang: step bertipe Role
    Holder memang bisa punya beberapa approver, dan `approval_mode`
    yang menentukan apakah cukup satu yang menyetujui.
    """
    from apps.hr.models import Employee
    from apps.workflow.models import ApproverScope

    if role is None:
        return []

    queryset = (
        Employee.objects
        .filter(
            user__isnull=False,
            user__roles=role,
            is_deleted=False,
        )
        .select_related("user", "organization")
    )

    scope = scope or ApproverScope.COMPANY

    if scope == ApproverScope.COMPANY:
        # Dipertahankan apa adanya: company boleh datang dari pemanggil
        # (dokumen sudah menyimpannya) walau penempatan pegawainya
        # belum terbaca.
        if company is not None:
            queryset = queryset.filter(organization__company=company)

    elif scope != ApproverScope.TENANT:
        value = _scope_value(organization, scope)

        # Pegawai subjek yang tingkat itu belum diisi. Dikembalikan
        # kosong, **bukan** dilonggarkan jadi se-company: melonggarkan
        # diam-diam persis kebocoran yang mau dicegah, dan resolver ini
        # memang dirancang gagal berisik dengan menyebut kolomnya.
        # Jalan keluarnya `fallback_role` atau `is_required=False`.
        if value is None:
            return []

        queryset = queryset.filter(**{f"organization__{scope}_id": value})

    if exclude_employee is not None:
        queryset = queryset.exclude(pk=exclude_employee.pk)

    return list(queryset.order_by("employee_number").distinct())


def _employee_of(user):
    """
    Pegawai di balik satu akun, kalau ada.

    `getattr` dengan default tidak cukup: relasi balik OneToOne yang
    kosong melempar `RelatedObjectDoesNotExist`, bukan mengembalikan
    None — dan akun tanpa pegawai (superuser, akun sistem) adalah
    keadaan yang sah di sini.
    """
    from apps.hr.models import Employee

    try:
        return user.employee_profile
    except Employee.DoesNotExist:
        return None
    except AttributeError:
        return None


def _as_candidates(
    employees,
    *,
    assignment_type: str,
    reason: str,
    provenance: dict | None = None,
):
    """
    Menyaring pegawai yang belum punya akun pengguna.

    Approval dijalankan lewat akun; pegawai tanpa akun tidak akan pernah
    bisa menekan tombolnya, dan mencantumkannya sebagai approver berarti
    dokumen mengendap tanpa ada yang bisa memprosesnya.
    """
    candidates = []
    skipped = []
    provenance = provenance or {}

    for employee in employees:
        if employee is None:
            continue

        if employee.user_id is None:
            skipped.append(employee.employee_number)

            continue

        candidates.append(
            Candidate(
                user=employee.user,
                employee=employee,
                assignment_type=assignment_type,
                reason=reason,
                **provenance,
            ),
        )

    return candidates, skipped


# ----------------------------------------------------------------------
# Titik masuk
# ----------------------------------------------------------------------


def resolve_approvers(*, employee, step, company=None) -> ResolvedApprovers:
    """
    Menentukan approver satu step untuk satu pegawai.

    Urutannya: tipe utama dulu, `fallback_role` kalau kosong.
    """
    organization = _organization_of(employee) if employee else None

    if company is None:
        company = getattr(organization, "company", None)

    employees: list = []
    single_user = None
    assignment_type = ""
    reason = ""
    skipped: list[str] = []

    # Jejak resolusi. Diisi tiap cabang di bawah, lalu dibekukan ke
    # `WorkflowApproval.metadata`.
    source = ""
    resolved_role = ""
    resolved_scope = ""

    if step.approver_type == ApproverType.USER:
        assignment_type = AssignmentType.USER
        source = "CONFIGURED_USER"

        if step.approver_user_id:
            single_user = step.approver_user
            reason = "Ditunjuk langsung di konfigurasi step."
        else:
            reason = (
                "Step bertipe Specific User tapi penggunanya belum "
                "dipilih di konfigurasi alur."
            )

    elif step.approver_type == ApproverType.MANAGER:
        assignment_type = AssignmentType.MANAGER

        # Garis pelaporan antarorang pada penempatan kepegawaian —
        # **bukan** "siapa pun yang jabatannya supervisor", dan bukan
        # kepala departemen. Penandanya menyebut kolomnya supaya jejak
        # dokumen tidak perlu ditafsirkan.
        source = "EMPLOYMENT_REPORT_TO"

        if employee is None:
            reason = (
                "Dokumen ini tidak menunjuk pegawai, jadi garis "
                "pelaporannya tidak bisa ditelusuri."
            )
        else:
            found, stopped_at = _walk_reports_to(employee, step.level)

            if found is None:
                reason = (
                    f"Garis pelaporan {employee.employee_number} putus "
                    f"di {stopped_at.employee_number} — kolom "
                    "'Reports To' pada penempatan organisasinya masih "
                    "kosong."
                )
            else:
                employees = [found]
                reason = (
                    f"Atasan langsung tingkat {step.level} dari "
                    f"{employee.employee_number}."
                )

    elif step.approver_type == ApproverType.POSITION:
        assignment_type = AssignmentType.POSITION
        source = "POSITION_HIERARCHY"

        found = _walk_position(employee, step) if employee else None

        if found is None:
            reason = (
                "Hierarki jabatan tidak sampai ke pemegang mana pun — "
                "'Reports To' pada master Position masih kosong, atau "
                "jabatan atasannya belum ada yang menempati."
            )
        else:
            employees = [found]
            reason = f"Pemegang jabatan atasan tingkat {step.level}."

    elif step.approver_type == ApproverType.DEPARTMENT_HEAD:
        assignment_type = AssignmentType.DEPARTMENT_HEAD
        source = "DEPARTMENT_HEAD"

        # Tipe ini tidak membaca `approver_scope` dan tidak bisa
        # diberi: yang dicarinya kepala **department pegawainya**, dan
        # department itulah cakupannya.
        resolved_scope = ApproverScope.DEPARTMENT

        found = _department_manager(employee) if employee else None

        if found is None:
            reason = (
                "Tidak ada pemegang jabatan bertanda Manager di "
                "department pegawai ini."
            )
        else:
            employees = [found]
            reason = "Manajer departemen pegawai."

    elif step.approver_type == ApproverType.ROLE:
        assignment_type = AssignmentType.ROLE

        employees = _role_holders(
            step.approver_role,
            company=company,
            exclude_employee=employee,
            scope=step.approver_scope,
            organization=organization,
        )

        code = step.approver_role.code if step.approver_role_id else "?"

        source = _source_token(code)
        resolved_role = code if step.approver_role_id else ""
        resolved_scope = step.approver_scope or ApproverScope.COMPANY

        if employees:
            reason = (
                f"Pemegang role {code} "
                f"{_scope_label(step.approver_scope, organization)}."
            )
        else:
            reason = (
                "Tidak ada pegawai yang akun penggunanya memegang role "
                f"{code} {_scope_label(step.approver_scope, organization)}."
            )

    # Tipe Specific User tidak lewat master pegawai sama sekali —
    # akunnya memang yang ditunjuk, pegawainya cuma pelengkap cetak.
    scope_label, scope_id = _scope_object(resolved_scope, organization, company)

    provenance = {
        "resolution_source": source,
        "resolved_role": resolved_role,
        "resolved_scope": resolved_scope,
        "resolved_scope_object": scope_label,
        "resolved_scope_object_id": scope_id,
    }

    if single_user is not None:
        return ResolvedApprovers(
            candidates=[
                Candidate(
                    user=single_user,
                    employee=_employee_of(single_user),
                    assignment_type=assignment_type,
                    reason=reason,
                    **provenance,
                ),
            ],
            reason=reason,
        )

    candidates, skipped = _as_candidates(
        employees,
        assignment_type=assignment_type,
        reason=reason,
        provenance=provenance,
    )

    if candidates:
        return ResolvedApprovers(candidates=candidates, reason=reason)

    if skipped:
        reason = (
            f"{reason} Ditemukan {', '.join(skipped)}, tapi pegawai itu "
            "belum punya akun pengguna sehingga tidak bisa menyetujui."
        )

    # Jalur cadangan. Sengaja dicoba setelah tipe utamanya gagal, bukan
    # digabung: alasan kegagalan yang pertama tetap ikut dilaporkan,
    # supaya yang memperbaiki data tahu kolom mana yang sebenarnya
    # kosong.
    # Cadangannya boleh berjenjang: Admin Section → Admin Department →
    # HR. Yang pertama menemukan orang yang menang; sisanya tidak
    # dicoba, karena satu meja yang berisi orang dari tiga tingkat
    # sekaligus bukan cadangan, itu rapat.
    #
    # Cakupan tiap tingkat ditentukan barisnya sendiri, dan yang tanpa
    # baris `WorkflowStepFallback` tetap memakai `fallback_role` lama
    # **se-company**. Melebar ke company terdengar longgar, tapi itu
    # justru gunanya: step "Admin HR Site" yang dipersempit ke satu
    # lokasi lalu jatuh ke HR Manager tidak akan pernah menemukan siapa
    # pun kalau cadangannya ikut dipersempit — HR Manager memang duduk
    # di kantor pusat, dan keadaan "di site ini tidak ada orangnya"
    # itulah yang mau ditangani cadangan.
    #
    # Melebar tanpa terlihat bukan risikonya: barisnya tercatat sebagai
    # `FALLBACK_ROLE` dengan alasannya sendiri di jejak dokumen. Yang
    # tidak boleh dilewati tetap company — approver dari perusahaan lain
    # adalah kebocoran, bukan eskalasi.
    for fallback_role, fallback_scope in step.fallback_chain():
        fallback_employees = _role_holders(
            fallback_role,
            company=company,
            exclude_employee=employee,
            scope=fallback_scope,
            organization=organization,
        )

        fallback_label, fallback_id = _scope_object(
            fallback_scope,
            organization,
            company,
        )

        fallback_candidates, fallback_skipped = _as_candidates(
            fallback_employees,
            assignment_type=AssignmentType.FALLBACK_ROLE,
            # Cakupannya disebut, bukan diam: yang membaca jejak harus
            # tahu baris ini melebar dari cakupan step-nya, dan sejauh
            # apa.
            reason=(
                f"{reason} Dialihkan ke pemegang role cadangan "
                f"{fallback_role.code} "
                f"{_scope_label(fallback_scope, organization)}."
            ),
            # Akhiran `_FALLBACK` yang membedakan meja yang terisi
            # sebagaimana dikonfigurasi dari meja yang terisi karena
            # tingkat utamanya kosong. Tanpa pembeda itu, alur yang
            # separuh dokumennya jatuh ke cadangan terbaca persis
            # seperti alur yang berjalan sebagaimana mestinya.
            provenance={
                "resolution_source": (
                    f"{_source_token(fallback_role.code)}_FALLBACK"
                ),
                "resolved_role": fallback_role.code,
                "resolved_scope": fallback_scope,
                "resolved_scope_object": fallback_label,
                "resolved_scope_object_id": fallback_id,
            },
        )

        if fallback_candidates:
            return ResolvedApprovers(
                candidates=fallback_candidates,
                reason=fallback_candidates[0].reason,
            )

        reason = (
            f"{reason} Role cadangan {fallback_role.code} juga "
            "tidak ada pemegangnya "
            f"{_scope_label(fallback_scope, organization)}"
            + (
                f" yang punya akun ({', '.join(fallback_skipped)})."
                if fallback_skipped
                else "."
            )
        )

    return ResolvedApprovers(candidates=[], reason=reason)


# ----------------------------------------------------------------------
# Garis pelaporan sebagai API publik
# ----------------------------------------------------------------------
#
# Dua pertanyaan di bawah — "siapa atasan langsungnya" dan "siapa kepala
# departemennya" — bukan konsep milik engine approval; itu pertanyaan
# tentang bagan organisasi yang kebetulan pertama kali dibutuhkan di
# sini. Modul notifikasi menanyakan hal yang persis sama saat menentukan
# penerima.
#
# Dibuka sebagai alias, bukan disalin ke sana: dua salinan aturan yang
# harus tetap sama adalah cara paling pasti membuat approver sebuah
# dokumen berbeda dari orang yang diberi tahu tentang dokumen itu — dan
# selisih seperti itu tidak berbunyi, ia cuma membuat satu orang tidak
# pernah tahu.


def manager_of(employee, *, level: int = 1):
    """
    Atasan `level` tingkat di atas pegawai, lewat `reports_to`.

    None kalau garis pelaporannya putus di tengah jalan.
    """
    found, _stopped_at = _walk_reports_to(employee, max(1, int(level or 1)))

    return found


def department_head_of(employee):
    """Pemegang jabatan bertanda `is_manager` di department pegawai."""
    return _department_manager(employee)
