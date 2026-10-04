"""
Service master BPJS.

Yang dijaga di sini tiga hal yang tidak bisa dijaga model sendirian:
aturan yang sudah dipakai payroll terkunci tidak boleh dihapus, komposisi
dasar yang sudah dirujuk tidak boleh berubah isinya, dan penghapusan
komponen dasar adalah perubahan isi juga — bukan pengecualian.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    BpjsBaseComponent,
    BpjsBaseDefinition,
    BpjsEnrollment,
    BpjsProgram,
    BpjsRiskClass,
    BpjsRule,
)
from apps.payroll.services.bpjs import BPJS_REFERENCE_TYPE


class BpjsProgramService(BaseMasterService):
    model = BpjsProgram

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        if instance.rules.exists():
            raise ValidationError(
                {
                    "code": (
                        "Program ini masih punya aturan BPJS. "
                        "Nonaktifkan saja (Active = off) supaya "
                        "riwayat perhitungannya tetap bisa ditelusuri."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)


class BpjsBaseDefinitionService(BaseMasterService):
    model = BpjsBaseDefinition

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        if instance.is_referenced:
            raise ValidationError(
                {
                    "code": (
                        "Komposisi ini sudah dipakai aturan BPJS dan "
                        "tidak bisa dihapus. Terbitkan versi baru "
                        "untuk perubahan berikutnya."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)


class BpjsBaseComponentService(BaseMasterService):
    model = BpjsBaseComponent

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("definition")

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        # Menghapus komponen **mengubah isi komposisi**, sama seperti
        # menyuntingnya. Kalau yang dijaga cuma penyuntingan, komposisi
        # historis tetap bisa dikosongkan satu per satu.
        if instance.definition.is_referenced:
            raise ValidationError(
                {
                    "allowance_code": (
                        "Komposisi ini sudah dipakai aturan BPJS dan "
                        "tidak bisa diubah. Terbitkan versi baru dari "
                        "definisinya."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)


class BpjsRiskClassService(BaseMasterService):
    model = BpjsRiskClass

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        if instance.bpjs_rules.exists() or instance.bpjs_enrollments.exists():
            raise ValidationError(
                {
                    "code": (
                        "Kelas risiko ini masih dipakai aturan atau "
                        "kepesertaan BPJS. Nonaktifkan saja supaya "
                        "riwayat klasifikasinya tetap bisa dibaca."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)


class BpjsRuleService(BaseMasterService):
    model = BpjsRule

    @classmethod
    def get_queryset(cls):
        return (
            super().get_queryset()
            .select_related("program", "company", "base_definition", "risk_class")
        )

    # ------------------------------------------------------------------
    # Sejarah aturan
    # ------------------------------------------------------------------

    @staticmethod
    def has_produced_components(instance) -> bool:
        """
        Aturan ini sudah pernah melahirkan komponen payroll?

        **Termasuk run yang belum difinalisasi**, dan itu perluasan yang
        disengaja. Run terbuka dihitung ulang, dan penghitungan ulang
        membaca aturan yang berlaku pada tanggal jangkarnya. Aturan yang
        dinonaktifkan atau dihapus karena itu mengubah angka periode
        yang sudah pernah dihitung — tanpa satu baris aturan pun terlihat
        berubah, karena memang tidak ada yang berubah: yang berubah
        keberadaannya.
        """
        from apps.payroll.models import PayrollRunComponent

        return (
            PayrollRunComponent.objects
            .filter(
                reference_type=BPJS_REFERENCE_TYPE,
                reference_id=str(instance.pk),
                is_deleted=False,
            )
            .exists()
        )

    @classmethod
    @transaction.atomic
    def close_and_publish(cls, *, rule, data, user=None):
        """
        Menutup aturan berjalan dan menerbitkan penggantinya, sekaligus.

        Ini **satu-satunya** cara yang benar mengganti tarif regulasi.
        Menonaktifkan aturan lama lalu membuat yang baru terlihat setara
        padahal tidak: `is_active` tidak bertanggal, jadi mematikannya
        menghapus aturan itu dari **seluruh** penghitungan ulang,
        termasuk periode yang aturan lamanya memang berlaku. Yang
        bertanggal cuma `effective_to`.

        Dijadikan satu transaksi karena validasi tumpang tindih menolak
        aturan baru selama yang lama masih terbuka: dua langkah terpisah
        selalu melewati keadaan yang ditolak, dan operator yang
        menemuinya akan tergoda melebarkan tanggal dengan tangan.
        """
        effective_from = data.get("effective_from")

        if not effective_from:
            raise ValidationError(
                {"effective_from": "Tanggal berlaku aturan baru wajib diisi."},
            )

        if effective_from <= rule.effective_from:
            raise ValidationError(
                {
                    "effective_from": (
                        "Aturan baru harus mulai berlaku setelah aturan "
                        "yang digantikannya."
                    ),
                },
            )

        closed_at = effective_from - timedelta(days=1)

        if rule.effective_to is not None and rule.effective_to < closed_at:
            # Sudah tertutup lebih awal. Melebarkannya diam-diam berarti
            # menghidupkan kembali rentang yang sengaja dikosongkan.
            raise ValidationError(
                {
                    "effective_from": (
                        f"Aturan yang digantikan sudah berakhir "
                        f"{rule.effective_to}. Terbitkan aturan baru "
                        f"tersendiri, bukan lewat penggantian."
                    ),
                },
            )

        rule.effective_to = closed_at
        rule.full_clean()
        rule.save(update_fields=["effective_to", "updated_at"])

        payload = {
            "program": rule.program,
            "company": rule.company,
            "risk_class": rule.risk_class,
            "base_definition": rule.base_definition,
        }
        payload.update(data)

        return cls.create(data=payload, user=user)

    @classmethod
    def before_update(cls, *, instance, data, user=None, **kwargs):
        # Menonaktifkan aturan yang sudah melahirkan angka adalah
        # penghapusan sejarah yang menyamar jadi penyuntingan.
        turning_off = (
            "is_active" in data
            and not data["is_active"]
            and instance.is_active
        )

        if turning_off and cls.has_produced_components(instance):
            raise ValidationError(
                {
                    "is_active": (
                        "Aturan ini sudah dipakai perhitungan payroll. "
                        "Tutup masa berlakunya lewat tanggal berakhir "
                        "(Close & Publish New Version) — menonaktifkannya "
                        "akan mengubah juga periode yang aturan ini "
                        "memang berlaku."
                    ),
                },
            )

        return super().before_update(
            instance=instance, data=data, user=user, **kwargs,
        )

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        if cls.has_produced_components(instance):
            raise ValidationError(
                {
                    "effective_from": (
                        "Aturan ini sudah dipakai perhitungan payroll. "
                        "Tutup masa berlakunya dengan mengisi tanggal "
                        "berakhir, jangan dihapus."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)


class BpjsEnrollmentService(BaseMasterService):
    model = BpjsEnrollment

    @classmethod
    def get_queryset(cls):
        return (
            super().get_queryset()
            .select_related("employee", "program", "risk_class")
        )
