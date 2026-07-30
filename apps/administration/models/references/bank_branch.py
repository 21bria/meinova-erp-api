from django.db import models

from apps.core.models import BaseModel


class BankBranch(BaseModel):
    code = models.CharField(max_length=30,)
    name = models.CharField(max_length=150)
    
    branch_code = models.CharField(max_length=30)
    address = models.TextField()
    phone = models.CharField( max_length=50, )
    email = models.CharField( max_length=254)
    contact_person = models.CharField(max_length=150)

    is_head_office = models.BooleanField()

    bank = models.ForeignKey(
        "administration.Bank",
        on_delete=models.DO_NOTHING,
        related_name="branches",
    )

    city = models.ForeignKey(
        "administration.City",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="bank_branches",
    )

    class Meta:
        db_table = "master_bank_branch"
        ordering = ["bank", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["bank", "code"],
                name="uniq_master_bank_branch_bank_code",
            ),
        ]

    def __str__(self):
        return f"{self.bank.name} - {self.name}"