"""
Kolom ManyToMany pada alur tulis master.

`BaseService.create/update` menugaskan setiap kolom lewat
`model(**data)` dan `setattr`. Django melarang itu untuk m2m —
*"Direct assignment to the forward side of a many-to-many set is
prohibited"* — jadi **setiap** PATCH yang menyebut kolom m2m berakhir
500, bukan cuma di satu modul. Perbaikannya generik di
`apps/core/services/base.py`, dan berkas ini menjaganya dari dua sisi:
service (perilaku umumnya) dan endpoint (kasus nyata yang dilaporkan,
`RosterPolicy.urgent_purposes`).

Yang paling mudah rusak diam-diam bukan penugasannya, melainkan
**PATCH parsial**: kalau kolom m2m yang tidak dikirim ikut disentuh,
menyunting satu kolom lain akan menghapus relasi yang sudah ada tanpa
ada yang meminta.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.administration.api.reference.hr.views.roster_policy import (
    RosterPolicyService,
)
from apps.administration.api.reference.hr.views.roster_policy import (
    ROSTER_POLICY_SCHEMA,
)
from apps.administration.models import RosterPolicy, RotationPurpose

User = get_user_model()

ENDPOINT = "/api/administration/references/hr/roster-policies/"


class MasterManyToManyTestCase(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "master-m2m"
        tenant.name = "Master M2M"

    # `TenantTestCase` tidak me-rollback antar test, jadi tiap test
    # membuat barisnya sendiri dengan kode yang tidak pernah terpakai
    # lagi — kalau tidak, urutan eksekusi yang menentukan hasilnya.
    _seq = 0

    def next_tag(self):
        type(self)._seq += 1

        return f"{self.__class__.__name__[:8]}{type(self)._seq:04d}"

    def setUp(self):
        super().setUp()

        self.purposes = [
            RotationPurpose.objects.create(
                code=f"UJI-{self.next_tag()}",
                name=f"Keperluan {self.next_tag()}",
            )
            for _ in range(3)
        ]

    def make_policy(self, **extra):
        tag = self.next_tag()

        return RosterPolicy.objects.create(
            code=extra.pop("code", f"POL-{tag}"),
            name=extra.pop("name", f"Policy {tag}"),
            **extra,
        )

    def ids(self, policy):
        return sorted(
            policy.urgent_purposes.values_list("id", flat=True),
        )


class ServiceManyToManyTests(MasterManyToManyTestCase):
    """Perilaku umum di service — berlaku untuk model m2m mana pun."""

    def test_create_accepts_a_many_to_many_column(self):
        policy = RosterPolicyService.create(
            data={
                "code": f"POL-{self.next_tag()}",
                "name": f"Policy Baru {self.next_tag()}",
                "urgent_purposes": self.purposes[:2],
            },
        )

        self.assertEqual(
            self.ids(policy),
            sorted(p.pk for p in self.purposes[:2]),
        )

    def test_update_replaces_the_whole_set(self):
        policy = self.make_policy()
        policy.urgent_purposes.set(self.purposes[:2])

        RosterPolicyService.update(
            instance=policy,
            data={"urgent_purposes": [self.purposes[2]]},
        )

        self.assertEqual(self.ids(policy), [self.purposes[2].pk])

    def test_update_without_the_column_leaves_the_relation_alone(self):
        """
        Inti bugnya kalau perbaikannya setengah: menyunting kolom lain
        tidak boleh menghapus relasi yang tidak disebut.
        """
        policy = self.make_policy()
        policy.urgent_purposes.set(self.purposes)

        RosterPolicyService.update(
            instance=policy,
            data={"description": "disunting tanpa menyentuh relasi"},
        )

        policy.refresh_from_db()

        self.assertEqual(policy.description, "disunting tanpa menyentuh relasi")
        self.assertEqual(self.ids(policy), sorted(p.pk for p in self.purposes))

    def test_an_empty_list_clears_the_relation(self):
        """
        Daftar kosong **dikirim** artinya "kosongkan" — berbeda dari
        kolomnya tidak dikirim sama sekali.
        """
        policy = self.make_policy()
        policy.urgent_purposes.set(self.purposes)

        RosterPolicyService.update(
            instance=policy,
            data={"urgent_purposes": []},
        )

        self.assertEqual(self.ids(policy), [])

    def test_the_split_keeps_plain_columns_on_the_instance(self):
        """
        Pemisahan m2m tidak boleh ikut membuang kolom biasa — kalau
        keliru menyaring, kolom skalar diam-diam berhenti tersimpan.
        """
        policy = self.make_policy()

        RosterPolicyService.update(
            instance=policy,
            data={
                "name": f"Policy Tersunting {self.next_tag()}",
                "request_lead_days": 9,
                "urgent_purposes": [self.purposes[0]],
            },
        )

        policy.refresh_from_db()

        self.assertTrue(policy.name.startswith("Policy Tersunting"))
        self.assertEqual(policy.request_lead_days, 9)
        self.assertEqual(self.ids(policy), [self.purposes[0].pk])

    def test_models_without_many_to_many_are_untouched(self):
        plain, related = RosterPolicyService._split_many_to_many(
            {"name": "x", "request_lead_days": 3},
        )

        self.assertEqual(plain, {"name": "x", "request_lead_days": 3})
        self.assertEqual(related, {})


class RosterPolicyPatchEndpointTests(MasterManyToManyTestCase):
    """Kasus yang dilaporkan: PATCH lewat endpoint."""

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

        self.user = User.objects.create_user(
            username="master.m2m",
            email="master.m2m@example.test",
            password="m2m-pass-1",
            is_superuser=True,
            is_staff=True,
        )

        self.policy = self.make_policy(name=f"Policy Endpoint {self.next_tag()}")
        self.policy.urgent_purposes.set(self.purposes[:2])

    def patch(self, payload):
        return self.client.patch(
            f"{ENDPOINT}{self.policy.pk}/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(self.user).access_token}"
            ),
        )

    def get(self):
        return self.client.get(
            f"{ENDPOINT}{self.policy.pk}/",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(self.user).access_token}"
            ),
        )

    def test_patch_touching_only_another_column_succeeds(self):
        response = self.patch({"description": "tanpa menyentuh relasi"})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.ids(self.policy),
            sorted(p.pk for p in self.purposes[:2]),
        )

    def test_patch_sets_the_urgent_purposes(self):
        response = self.patch(
            {"urgent_purposes": [self.purposes[2].pk]},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.ids(self.policy), [self.purposes[2].pk])

    def test_patch_can_clear_the_urgent_purposes(self):
        response = self.patch({"urgent_purposes": []})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.ids(self.policy), [])

    def test_detail_returns_the_stored_relation(self):
        self.patch({"urgent_purposes": [p.pk for p in self.purposes]})

        response = self.get()

        self.assertEqual(response.status_code, 200, response.content)

        payload = response.json()
        payload = payload.get("data", payload)

        self.assertEqual(
            sorted(payload["urgent_purposes"]),
            sorted(p.pk for p in self.purposes),
        )

    def test_an_unknown_id_is_rejected_and_changes_nothing(self):
        response = self.patch({"urgent_purposes": [99999]})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            self.ids(self.policy),
            sorted(p.pk for p in self.purposes[:2]),
        )


class ManyToManySchemaContractTests(TenantTestCase):
    """
    Kontrak schema untuk kolom ManyToMany.

    Frontend memutuskan komponennya dari schema: `type: "lookup"` +
    `multiple: true` dirender sebagai pemilih banyak nilai, tanpa
    `multiple` jadi pemilih satu nilai. Gagalnya **tidak** melempar
    error — layar cuma menampilkan id mentah dan entry terlihat seperti
    single-select, persis bug yang dilaporkan. Jadi flag-nya dijaga di
    sini, bukan dipercayakan pada ingatan orang yang menambah kolom.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "m2m-schema"
        tenant.name = "M2M Schema"

    def test_every_many_to_many_column_is_declared_multiple(self):
        for field in RosterPolicy._meta.many_to_many:
            with self.subTest(field=field.name):
                meta = ROSTER_POLICY_SCHEMA["fields"].get(field.name)

                self.assertIsNotNone(
                    meta,
                    f"kolom m2m '{field.name}' tidak ada di schema",
                )
                self.assertEqual(meta.get("type"), "lookup")
                self.assertTrue(
                    meta.get("multiple"),
                    f"'{field.name}' m2m tapi schema tidak menyebut "
                    f"multiple=True — layar akan merendernya sebagai "
                    f"pilihan tunggal dan memperlihatkan id mentah.",
                )

    def test_the_multi_lookup_points_at_an_options_endpoint(self):
        """
        Tanpa endpoint, komponen multi tidak punya sumber label dan
        chip-nya jatuh ke id.
        """
        meta = ROSTER_POLICY_SCHEMA["fields"]["urgent_purposes"]

        self.assertTrue(
            meta.get("lookup_endpoint"),
            "urgent_purposes tidak menyebut lookup_endpoint",
        )
