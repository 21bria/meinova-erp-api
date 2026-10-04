"""
Menerbitkan konfigurasi BPJS yang **sudah terverifikasi** (#3B.2).

    # Aturan bawaan seluruh tenant
    python manage.py tenant_command bpjs_publish_statutory \\
        --schema=demo --global \\
        --no-fixed-allowance \\
        --effective-from=2026-01-01 [--apply]

    # Komposisi khusus satu perusahaan
    python manage.py tenant_command bpjs_publish_statutory \\
        --schema=demo --company=MLS \\
        --fixed-allowance TUNJ-JABATAN \\
        --fixed-allowance HOUSING-FIXED \\
        --effective-from=2026-01-01 [--apply]

**Cakupannya wajib disebut**, `--global` atau `--company=KODE`. Tidak
ada bawaan: satu tenant berisi beberapa perusahaan yang komponen
tunjangan tetapnya berbeda, dan perintah yang menebak cakupan akan
menerapkan pemetaan satu perusahaan ke semua perusahaan — diam-diam,
dan pada angka gaji.

**Tarif statuternya sama; yang berbeda komposisi dasarnya.** Karena
override company adalah **penggantian aturan utuh** (keputusan #3A
butir 3, tanpa penggabungan per kolom), aturan company mengulang tarif
yang sama sambil menunjuk komposisi dasarnya sendiri. Konsekuensinya
harus diketahui: ketika tarif berubah, **setiap** aturan company ikut
diterbitkan ulang lewat `close_and_publish()`, bukan hanya yang global.

**Kenapa perintah, bukan seed dan bukan migration.** Angka statuter di
sini adalah **data bertanggal berlaku**, bukan konstanta program. Seed
berjalan otomatis dan diam-diam mengubah angka gaji seluruh tenant;
migration menuliskannya ke sejarah skema. Yang benar: seseorang
memutuskan menerbitkannya, pada tanggal yang ia sebut, sekali.

**Mesin hitung tidak pernah membaca berkas ini.** Ia membaca `BpjsRule`.
Tabel di bawah cuma kendaraan sekali jalan yang memindahkan angka
terverifikasi ke dalam konfigurasi.

**Dry-run bawaannya.** Tanpa `--apply` tidak satu baris pun tersimpan.

**Kepesertaan tidak dibuat otomatis.** Itu keputusan #3A butir 1:
tidak terdaftar berarti tidak ikut, dan mendaftarkan orang secara
otomatis persis kebalikan dari keputusan itu.

Yang **tidak** diterbitkan di sini, dan alasannya:

* **JKN** — hanya plafonnya yang terverifikasi; tarif 1%/4% dan
  komposisi upahnya belum dibaca dari teks primer. Program dibuat
  sebagai identitas, **tanpa aturan**. Plafonnya dicatat di keterangan
  program supaya tidak hilang, bukan sebagai angka yang dihitung.
* **JKP** — representasi penagihannya belum terjawab (0,14% ditagih
  terpisah, atau sudah termasuk di dalam JKK). Tidak dikonfigurasi
  sama sekali; dua kemungkinan itu berbeda hasilnya di atas plafon
  Rp5.000.000.
* **Prorata masuk/keluar, cuti tidak dibayar, borongan, harian JP,
  pembulatan** — belum diputuskan, jadi tidak ada yang dikarang.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.payroll.models import (
    AllowanceTemplateLine,
    BpjsBaseComponent,
    BpjsBaseDefinition,
    BpjsDailyBasicMethod,
    BpjsProgram,
    BpjsRiskClass,
    BpjsRule,
)


#: Komposisi dasar untuk program yang aturan hariannya **sudah**
#: terverifikasi: upah sehari x 25 (PP 44/2015 Pasal 19 ayat (3) untuk
#: JKK/JKM, PP 46/2015 Pasal 17 ayat (3) untuk JHT).
BASE_DAILY_25 = "UPAH-BPJS-H25"

#: Komposisi dasar untuk program yang aturan hariannya **belum**
#: terverifikasi. PP 45/2015 Pasal 29 tidak memuat ketentuan harian
#: sama sekali, jadi JP memakai komposisi yang tidak mengarang cara
#: harian: pegawai harian menghasilkan dasar nol dan peringatan
#: `bpjs_base_zero` yang kelihatan — bukan angka yang ditebak.
BASE_DAILY_NONE = "UPAH-BPJS-HNONE"

#: Kelas risiko JKK, taksonomi PP 44/2015 Pasal 16 ayat (1).
RISK_CLASSES = [
    ("RISK-1", "Tingkat Risiko Sangat Rendah", 1, Decimal("0.10")),
    ("RISK-2", "Tingkat Risiko Rendah", 2, Decimal("0.40")),
    ("RISK-3", "Tingkat Risiko Sedang", 3, Decimal("0.75")),
    ("RISK-4", "Tingkat Risiko Tinggi", 4, Decimal("1.13")),
    ("RISK-5", "Tingkat Risiko Sangat Tinggi", 5, Decimal("1.60")),
]

#: Tarif JKK di atas **sudah pasca-rekomposisi** (PP 6/2025 Pasal 11
#: ayat (5)). Tarif pra-rekomposisi 0,24%-1,74% adalah angka historis
#: dan tidak boleh dipakai bersamaan dengan komponen JKP terpisah —
#: keduanya menagih 0,14% yang sama.

#: Plafon dasar iuran JP, berlaku 1 Maret 2026 (surat edaran BPJS
#: Ketenagakerjaan B/1226/022026, dasar PP 45/2015 Pasal 29 ayat (3)).
#: Angka ini **berubah tiap tahun** mengikuti pertumbuhan PDB; ia
#: diterbitkan ulang lewat `close_and_publish()`, bukan disunting.
JP_BASE_MAXIMUM = Decimal("11086300")
JP_EFFECTIVE_FROM = date(2026, 3, 1)

#: Plafon JKN yang terverifikasi (Perpres 59/2024 Pasal 32 ayat (1)).
#: Dicatat sebagai keterangan, bukan sebagai aturan: tarifnya belum
#: terverifikasi, dan `BpjsRule` menolak aturan tanpa satu sisi pun.
JKN_BASE_MAXIMUM = Decimal("12000000")

PROGRAMS = [
    {
        "code": "JHT",
        "name": "Jaminan Hari Tua",
        "sequence": 10,
        "uses_risk_class": False,
        "employee_rate": Decimal("2"),
        "employer_rate": Decimal("3.7"),
        "base": BASE_DAILY_25,
        "authority": "PP 46/2015 Pasal 16 ayat (1)",
    },
    {
        "code": "JP",
        "name": "Jaminan Pensiun",
        "sequence": 20,
        "uses_risk_class": False,
        "employee_rate": Decimal("1"),
        "employer_rate": Decimal("2"),
        "base": BASE_DAILY_NONE,
        "base_maximum": JP_BASE_MAXIMUM,
        "effective_from": JP_EFFECTIVE_FROM,
        "authority": "PP 45/2015 Pasal 28; SE B/1226/022026",
    },
    {
        "code": "JKK",
        "name": "Jaminan Kecelakaan Kerja",
        "sequence": 30,
        "uses_risk_class": True,
        "employee_rate": None,
        "base": BASE_DAILY_25,
        "authority": "PP 44/2015 Pasal 16; PP 6/2025 Pasal 11 ayat (5)",
    },
    {
        "code": "JKM",
        "name": "Jaminan Kematian",
        "sequence": 40,
        "uses_risk_class": False,
        "employee_rate": None,
        "employer_rate": Decimal("0.30"),
        "base": BASE_DAILY_25,
        "authority": "PP 44/2015 Pasal 18 ayat (1)",
    },
]


class Command(BaseCommand):
    help = (
        "Menerbitkan konfigurasi BPJS terverifikasi (#3B.2) sebagai "
        "aturan bertanggal berlaku. Dry-run bawaannya."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixed-allowance",
            action="append",
            default=[],
            metavar="KODE",
            help=(
                "Kode komponen tunjangan tetap yang ikut jadi dasar "
                "iuran. Boleh diulang. Perintah ini tidak menebak "
                "kode mana yang tetap."
            ),
        )
        parser.add_argument(
            "--no-fixed-allowance",
            action="store_true",
            help=(
                "Nyatakan dengan sengaja bahwa dasar iuran hanya gaji "
                "pokok. Wajib kalau --fixed-allowance tidak diisi."
            ),
        )
        parser.add_argument(
            "--company",
            default="",
            metavar="KODE",
            help=(
                "Kode perusahaan yang aturannya diterbitkan. Aturan "
                "yang lahir menggantikan aturan bawaan tenant secara "
                "utuh untuk perusahaan itu."
            ),
        )
        parser.add_argument(
            "--global",
            dest="publish_global",
            action="store_true",
            help=(
                "Terbitkan aturan bawaan seluruh tenant. Wajib "
                "dinyatakan; tidak ada cakupan bawaan."
            ),
        )
        parser.add_argument(
            "--allow-unknown-allowance",
            action="store_true",
            help=(
                "Izinkan kode tunjangan yang belum ada di master. "
                "Tanpa ini, kode yang tidak dikenal menolak perintah."
            ),
        )
        parser.add_argument(
            "--effective-from",
            required=False,
            help="Tanggal berlaku aturan JHT, JKK, dan JKM (YYYY-MM-DD).",
        )
        parser.add_argument("--apply", action="store_true")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        company = self._resolve_scope(options)

        codes = [code.strip() for code in options["fixed_allowance"] if code.strip()]

        if not codes and not options["no_fixed_allowance"]:
            raise CommandError(
                "Tidak ada kode tunjangan tetap. Perintah ini tidak "
                "menebak komponen mana yang tunjangan tetap — tulis "
                "--fixed-allowance KODE, atau nyatakan dengan sengaja "
                "lewat --no-fixed-allowance kalau dasarnya memang "
                "gaji pokok saja.",
            )

        effective_from = self._parse_date(options.get("effective_from"))

        if effective_from is None:
            raise CommandError(
                "--effective-from wajib diisi. Tanggal berlakunya "
                "aturan adalah keputusan, bukan sesuatu yang boleh "
                "ditebak dari tanggal hari ini.",
            )

        apply = options["apply"]

        scope = (
            f"{company.code} - {company.name}"
            if company is not None
            else "SELURUH TENANT (global)"
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Publikasi konfigurasi BPJS terverifikasi"
                + ("" if apply else " (DRY-RUN)"),
            ),
        )
        self.stdout.write(f"  Cakupan         : {scope}")
        self.stdout.write("")

        with transaction.atomic():
            self._run(
                codes=codes,
                effective_from=effective_from,
                company=company,
                allow_unknown=options["allow_unknown_allowance"],
            )

            if not apply:
                transaction.set_rollback(True)

                self.stdout.write("")
                self.stdout.write(
                    self.style.WARNING(
                        "DRY-RUN: tidak ada yang disimpan. Tambahkan "
                        "--apply untuk menerbitkannya.",
                    ),
                )
                self.stdout.write("")
                return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Konfigurasi diterbitkan."))
        self.stdout.write("")

    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_scope(options):
        """
        Cakupan aturan yang diterbitkan — dan ia **wajib disebut**.

        Bawaan apa pun salah di sini. Bawaan global menerapkan pemetaan
        tunjangan satu perusahaan ke semua perusahaan; bawaan "company
        pertama" lebih buruk lagi. Satu tenant memang berisi beberapa
        perusahaan yang komponen tunjangan tetapnya berbeda, jadi yang
        benar adalah menolak menebak.
        """
        from apps.administration.models import Company

        code = (options["company"] or "").strip()
        publish_global = options["publish_global"]

        if code and publish_global:
            raise CommandError(
                "--company dan --global tidak bisa dipakai bersamaan. "
                "Aturan bawaan tenant dan aturan perusahaan diterbitkan "
                "terpisah.",
            )

        if not code and not publish_global:
            raise CommandError(
                "Cakupannya wajib disebut: --global untuk aturan bawaan "
                "seluruh tenant, atau --company=KODE untuk satu "
                "perusahaan. Perintah ini tidak menebak cakupan — "
                "tebakan yang salah menerapkan pemetaan tunjangan satu "
                "perusahaan ke semua perusahaan.",
            )

        if publish_global:
            return None

        company = Company.objects.filter(code=code, is_deleted=False).first()

        if company is None:
            available = ", ".join(
                Company.objects
                .filter(is_deleted=False)
                .order_by("code")
                .values_list("code", flat=True),
            )

            raise CommandError(
                f"Perusahaan dengan kode '{code}' tidak ada. "
                f"Yang tersedia: {available or '(belum ada)'}.",
            )

        return company

    def _run(self, *, codes, effective_from, company, allow_unknown):
        self._check_codes(codes, company=company, allow_unknown=allow_unknown)

        suffix = f"-{company.code}" if company is not None else ""

        label = f" {company.code}" if company is not None else ""

        definitions = {
            BASE_DAILY_25: self._ensure_base(
                code=f"{BASE_DAILY_25}{suffix}",
                name=f"Upah Pokok + Tunjangan Tetap{label} (harian x25)",
                method=BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR,
                factor=Decimal("25"),
                codes=codes,
            ),
            BASE_DAILY_NONE: self._ensure_base(
                code=f"{BASE_DAILY_NONE}{suffix}",
                name=(
                    f"Upah Pokok + Tunjangan Tetap{label} "
                    f"(harian belum diatur)"
                ),
                method=BpjsDailyBasicMethod.NONE,
                factor=None,
                codes=codes,
            ),
        }

        risk_classes = self._ensure_risk_classes()

        for spec in PROGRAMS:
            program = self._ensure_program(spec)

            starts = spec.get("effective_from") or effective_from

            if spec["code"] == "JKK":
                self._publish_jkk(
                    program=program,
                    definition=definitions[spec["base"]],
                    risk_classes=risk_classes,
                    effective_from=starts,
                    company=company,
                )
                continue

            self._publish_rule(
                program=program,
                definition=definitions[spec["base"]],
                employee_rate=spec.get("employee_rate"),
                employer_rate=spec.get("employer_rate"),
                base_maximum=spec.get("base_maximum"),
                effective_from=starts,
                risk_class=None,
                company=company,
            )

            self.stdout.write(
                f"  {spec['code']:<5} "
                f"pegawai {self._pct(spec.get('employee_rate'))}  "
                f"perusahaan {self._pct(spec.get('employer_rate'))}  "
                f"plafon {self._money(spec.get('base_maximum'))}  "
                f"berlaku {starts}",
            )

        if company is None:
            self._publish_jkn()

        self.stdout.write("")
        self.stdout.write(
            "  JKP   tidak dikonfigurasi — representasi penagihannya "
            "belum terjawab.",
        )
        self.stdout.write(
            "  Kepesertaan TIDAK dibuat otomatis. Tidak terdaftar "
            "berarti tidak ikut.",
        )

    # ------------------------------------------------------------------

    def _check_codes(self, codes, *, company, allow_unknown):
        """
        Setiap kode yang disebut harus benar-benar ada.

        Kode yang salah ketik **tidak** menghasilkan error saat payroll
        dihitung — ia cuma tidak menambah apa-apa, jadi dasar iuran
        mengecil diam-diam dan iurannya kurang bayar berbulan-bulan.
        Karena itu ditolak di sini, bukan diperingatkan.

        Basis komponen (`fixed`, `per_attendance_day`, ...) **tidak**
        dipakai untuk menyimpulkan apa pun. Tunjangan tetap menurut
        peraturan dan tunjangan berbasis tetap menurut mesin hitung
        adalah dua hal yang kebetulan sering berimpit; menyimpulkan
        yang satu dari yang lain adalah kebijakan yang tidak pernah
        diputuskan siapa pun.
        """
        if not codes:
            return

        rows = list(
            AllowanceTemplateLine.objects
            .filter(code__in=codes, is_deleted=False)
            .select_related("template")
            .order_by("code", "template__code"),
        )

        known = {row.code for row in rows}
        unknown = [code for code in codes if code not in known]

        if unknown and not allow_unknown:
            raise CommandError(
                "Kode tunjangan berikut tidak ada di master mana pun: "
                + ", ".join(unknown)
                + ". Kode yang salah ketik mengecilkan dasar iuran "
                "tanpa satu pesan pun saat payroll dihitung. Perbaiki "
                "kodenya, atau nyatakan dengan sengaja lewat "
                "--allow-unknown-allowance.",
            )

        for code in unknown:
            self.stdout.write(
                self.style.WARNING(
                    f"  PERIKSA: kode '{code}' tidak ada di master. "
                    f"Ia tidak akan menambah dasar iuran.",
                ),
            )

        # Basisnya ditampilkan supaya operator bisa melihat apa yang ia
        # sebut — bukan supaya perintah ini menilainya.
        for row in rows:
            self.stdout.write(
                f"  Komponen        : {row.code} "
                f"(template {row.template.code}, basis {row.basis})",
            )

        self._warn_unused_by_company(codes=known, company=company)

    def _warn_unused_by_company(self, *, codes, company):
        """
        Kode yang ada di tenant tapi tidak dipakai satu pegawai pun di
        perusahaan ini. Peringatan, bukan penolakan: template bisa saja
        baru dipasang sesudah konfigurasi ini terbit.
        """
        if company is None or not codes:
            return

        used = set(
            AllowanceTemplateLine.objects
            .filter(
                code__in=codes,
                is_deleted=False,
                template__employee_payroll_assignments__is_deleted=False,
                template__employee_payroll_assignments__employee__organization__company=company,
            )
            .values_list("code", flat=True),
        )

        for code in sorted(set(codes) - used):
            self.stdout.write(
                self.style.WARNING(
                    f"  PERIKSA: '{code}' ada di master tapi belum "
                    f"dipakai pegawai {company.code} mana pun.",
                ),
            )

    def _ensure_base(self, *, code, name, method, factor, codes):
        existing = (
            BpjsBaseDefinition.objects
            .filter(code=code, is_deleted=False)
            .order_by("-version")
            .first()
        )

        if existing is not None:
            if existing.is_referenced:
                raise CommandError(
                    f"Komposisi dasar {code} v{existing.version} sudah "
                    f"dipakai aturan BPJS dan tidak bisa diubah. "
                    f"Terbitkan versi baru lewat layar BPJS Base "
                    f"Definitions kalau komposisinya memang berubah.",
                )

            self.stdout.write(
                f"  Komposisi dasar : {code} v{existing.version} (sudah ada)",
            )

            return existing

        definition = BpjsBaseDefinition(
            code=code,
            version=1,
            name=name,
            include_basic=True,
            daily_basic_method=method,
            daily_basic_factor=factor,
        )
        definition.full_clean()
        definition.save()

        for index, allowance_code in enumerate(codes, start=1):
            component = BpjsBaseComponent(
                definition=definition,
                allowance_code=allowance_code,
                sequence=index * 10,
            )
            component.full_clean()
            component.save()

        listed = ", ".join(codes) if codes else "gaji pokok saja"

        self.stdout.write(f"  Komposisi dasar : {code} v1 ({listed})")

        return definition

    def _ensure_risk_classes(self):
        resolved = {}

        for code, name, sequence, rate in RISK_CLASSES:
            risk_class = BpjsRiskClass.objects.filter(
                code=code, is_deleted=False,
            ).first()

            if risk_class is None:
                risk_class = BpjsRiskClass(
                    code=code, name=name, sequence=sequence,
                )
                risk_class.full_clean()
                risk_class.save()

            resolved[code] = (risk_class, rate)

        return resolved

    def _ensure_program(self, spec):
        program = BpjsProgram.objects.filter(
            code=spec["code"], is_deleted=False,
        ).first()

        if program is not None:
            return program

        program = BpjsProgram(
            code=spec["code"],
            name=spec["name"],
            sequence=spec["sequence"],
            uses_risk_class=spec["uses_risk_class"],
            description=f"Dasar hukum: {spec['authority']}.",
        )
        program.full_clean()
        program.save()

        return program

    def _publish_jkk(
        self, *, program, definition, risk_classes, effective_from, company,
    ):
        for code, _, _, rate in RISK_CLASSES:
            risk_class, _ = risk_classes[code]

            self._publish_rule(
                program=program,
                definition=definition,
                employee_rate=None,
                employer_rate=rate,
                base_maximum=None,
                effective_from=effective_from,
                risk_class=risk_class,
                company=company,
            )

        self.stdout.write(
            f"  JKK   perusahaan per kelas risiko "
            f"({len(RISK_CLASSES)} aturan)  berlaku {effective_from}",
        )

    def _publish_rule(
        self,
        *,
        program,
        definition,
        employee_rate,
        employer_rate,
        base_maximum,
        effective_from,
        risk_class,
        company,
    ):
        existing = BpjsRule.objects.filter(
            program=program,
            company=company,
            risk_class=risk_class,
            is_deleted=False,
        ).exists()

        if existing:
            # Menimpanya di sini berarti mengubah arti periode yang
            # aturan lamanya memang berlaku. Penggantian tarif punya
            # jalannya sendiri: `close_and_publish()`.
            label = program.code + (
                f"/{risk_class.code}" if risk_class is not None else ""
            )
            scope = company.code if company is not None else "bawaan tenant"

            raise CommandError(
                f"Aturan {label} untuk {scope} sudah ada. Ganti "
                f"tarifnya lewat Close & Publish New Version, jangan "
                f"lewat perintah ini.",
            )

        rule = BpjsRule(
            program=program,
            company=company,
            risk_class=risk_class,
            base_definition=definition,
            effective_from=effective_from,
            employee_rate=employee_rate,
            employer_rate=employer_rate,
            base_maximum=base_maximum,
            # Pengurangan dasar PPh21 **tidak** diputuskan di sini:
            # metode PPh21 masih beku (#4).
            reduces_taxable=False,
        )
        rule.full_clean()
        rule.save()

        return rule

    def _publish_jkn(self):
        program = BpjsProgram.objects.filter(
            code="JKN", is_deleted=False,
        ).first()

        # Angkanya diformat tersendiri: mengganti koma jadi titik pada
        # seluruh kalimat ikut merusak tanda baca kalimatnya.
        ceiling = f"{JKN_BASE_MAXIMUM:,.0f}".replace(",", ".")

        note = (
            "Dasar hukum: Perpres 82/2018 s.t.d.t.d. Perpres 59/2024. "
            f"Plafon terverifikasi Rp{ceiling} "
            "(Pasal 32 ayat (1)); batas bawah UMP/UMK (Pasal 32 ayat "
            "(2)-(3)), dikecualikan untuk usaha mikro dan kecil "
            "(ayat (4)). Tarif dan komposisi upahnya BELUM "
            "terverifikasi, jadi belum ada aturan yang diterbitkan."
        )

        if program is None:
            program = BpjsProgram(
                code="JKN",
                name="Jaminan Kesehatan",
                sequence=50,
                uses_risk_class=False,
                description=note,
            )
            program.full_clean()
            program.save()

        self.stdout.write(
            "  JKN   program dibuat tanpa aturan — tarif dan komposisi "
            "upahnya belum terverifikasi.",
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value):
        if not value:
            return None

        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Tanggal tidak valid: {value}") from exc

    @staticmethod
    def _pct(value):
        return "-" if value is None else f"{value}%"

    @staticmethod
    def _money(value):
        return "-" if value is None else f"{value:,.2f}".replace(",", ".")
