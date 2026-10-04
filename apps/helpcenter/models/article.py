"""
Satu artikel panduan.

Isinya HTML keluaran editor (TipTap), bukan Markdown: editornya sudah
ada di framework FE dan sudah dipakai modul lain, sementara Markdown
berarti menambah parser di sisi pembaca hanya untuk satu layar. Yang
disimpan **selalu** hasil `sanitize_html()` — artikel ini dibaca semua
pengguna tenant, jadi HTML mentah dari satu penulis adalah stored XSS
untuk semua orang yang membukanya.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class HelpArticleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class HelpArticle(BaseModel):
    category = models.ForeignKey(
        "helpcenter.HelpCategory",
        on_delete=models.PROTECT,
        related_name="articles",
    )

    # Dipakai seed supaya bisa diulang tanpa menduplikasi baris.
    # Bukan `slug`: slug boleh diganti penulisnya kapan saja, dan
    # kalau seed berpegang padanya, artikel yang di-rename akan
    # ditulis ulang sebagai baris baru.
    code = models.CharField(
        max_length=50,
        help_text="Kode tetap untuk seed. Tidak tampil ke pembaca.",
    )

    slug = models.SlugField(
        max_length=160,
        blank=True,
        help_text=(
            "Bagian URL artikel. Dikosongkan = diturunkan dari judul."
        ),
    )

    title = models.CharField(
        max_length=200,
    )

    summary = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text=(
            "Satu kalimat yang tampil di kartu daftar. Ini yang dibaca "
            "orang sebelum memutuskan membuka artikelnya."
        ),
    )

    content = models.TextField(
        blank=True,
        default="",
        help_text="Isi panduan.",
    )

    icon = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Mis. `i-lucide-calendar-check`. Kosong = ikut kategori.",
    )

    keywords = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text=(
            "Kata kunci tambahan untuk pencarian, dipisah koma. Untuk "
            "istilah yang dipakai pengguna tapi tidak ada di isi "
            "artikel — mis. 'ijin' untuk artikel berjudul 'Cuti'."
        ),
    )

    # Menyambungkan artikel ke layar yang menjelaskannya. Dipakai
    # tombol Help kontekstual: yang sedang membuka /hr/leave langsung
    # ditawari panduan cuti, bukan daftar seluruh artikel.
    route_prefix = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text=(
            "Rute layar yang dijelaskan, mis. `/hr/leave`. Dipakai "
            "tombol Help di layar itu. Dikosongkan = tidak menempel "
            "ke layar mana pun."
        ),
    )

    video_url = models.URLField(
        max_length=300,
        blank=True,
        default="",
        help_text="Tautan video tutorial, kalau ada.",
    )

    # Kosong = terbaca semua orang. Bukan M2M: form schema-driven
    # belum bisa menyunting M2M (`MMultiLookupField` baru dirender di
    # dialog action), jadi M2M di sini berarti kolom yang tidak bisa
    # diisi dari layar mana pun. Batasan yang sama disadari di
    # `EmployeeDataPolicy`.
    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="help_articles",
        help_text=(
            "Dikosongkan = terbaca semua pengguna. Diisi kalau "
            "panduannya memang hanya untuk pemegang role tertentu "
            "(mis. panduan admin). Ini penyaring tampilan, bukan "
            "penjagaan rahasia."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=HelpArticleStatus.choices,
        default=HelpArticleStatus.DRAFT,
        help_text="Hanya yang Published yang muncul di Help Center.",
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Diisi otomatis saat status berubah jadi Published.",
    )

    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Urutan dalam kategorinya. Angka kecil di atas.",
    )

    # Tiga penghitung di bawah ini yang menjawab "panduan mana yang
    # sebenarnya dibaca orang" — pertanyaan yang tidak bisa dijawab
    # kalau help center cuma kumpulan halaman statis.
    view_count = models.PositiveIntegerField(
        default=0,
    )

    helpful_count = models.PositiveIntegerField(
        default=0,
    )

    not_helpful_count = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = [
            "category__sort_order",
            "sort_order",
            "title",
        ]

        verbose_name = "Help Article"
        verbose_name_plural = "Help Articles"

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_help_article_code",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=Q(is_deleted=False),
                name="uniq_active_help_article_slug",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class HelpArticleFeedback(BaseModel):
    """
    "Apakah panduan ini membantu?" — satu baris per pengguna per
    artikel.

    Penghitungnya disimpan di `HelpArticle` (bukan dihitung dari sini
    tiap kali dibaca) supaya bisa disortir di tabel admin; angkanya
    dijumlahkan ulang dari baris-baris ini tiap kali ada yang memilih,
    bukan ditambah inkremental — penjumlahan ulang tidak bisa hanyut.
    Pola yang sama dengan `LeaveBalance.used`.
    """

    article = models.ForeignKey(
        "helpcenter.HelpArticle",
        on_delete=models.CASCADE,
        related_name="feedbacks",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="help_article_feedbacks",
    )

    is_helpful = models.BooleanField()

    comment = models.TextField(
        blank=True,
        default="",
        help_text="Diisi pembaca yang menjawab 'tidak membantu'.",
    )

    class Meta:
        ordering = ["-created_at"]

        verbose_name = "Help Article Feedback"
        verbose_name_plural = "Help Article Feedback"

        constraints = [
            models.UniqueConstraint(
                fields=["article", "user"],
                condition=Q(is_deleted=False),
                name="uniq_active_help_feedback_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.article_id} — {'ya' if self.is_helpful else 'tidak'}"
