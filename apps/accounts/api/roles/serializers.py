from rest_framework import serializers

from apps.accounts.models import Role


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role

        # **Cakupan pada Role tidak ada lagi di sini.**
        #
        # Sampai Stage 4H kolomnya masih ikut terkirim read-only supaya
        # konfigurasi lama bisa dibandingkan selama peralihan. Stage 4I
        # mencabutnya: yang menentukan WHERE adalah kewenangan per
        # penugasan, dan kolom lama yang tetap tampil di layar Roles
        # membuat orang membaca angka yang tidak menentukan apa pun
        # sebagai kebijakan yang berlaku. Perbandingan cutover tetap
        # bisa dilakukan — tempatnya `audit_assignment_cutover`, bukan
        # layar administrasi sehari-hari.
        fields = [
            "id",
            "code",
            "name",
            "description",
            "permissions",
            "is_active",
        ]
