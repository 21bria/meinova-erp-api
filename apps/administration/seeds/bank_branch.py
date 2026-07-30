from apps.administration.models import Bank,BankBranch


BANK_BRANCHES = [

    {
        "bank_code": "BCA",
        "code": "BCA-001",
        "name": "BCA KCU Sudirman",
        "branch_code": "001",
        "address": "Jakarta",
        "phone": "1500888",
        "email": "halo@bca.co.id",
        "contact_person": "Customer Service",
        "is_head_office": True,
    },

    {
        "bank_code": "BCA",
        "code": "BCA-002",
        "name": "BCA KCU Kelapa Gading",
        "branch_code": "002",
        "address": "Jakarta Utara",
        "phone": "1500888",
        "email": "halo@bca.co.id",
        "contact_person": "Customer Service",
        "is_head_office": False,
    },

    {

        "bank_code": "MANDIRI",
        "code": "MANDIRI-001",
        "name": "Bank Mandiri KC Thamrin",
        "branch_code": "001",
        "address": "Jakarta Pusat",
        "phone": "14000",
        "email": "mandiricare@bankmandiri.co.id",
        "contact_person": "Customer Service",
        "is_head_office": True,

    },

    {

        "bank_code": "BNI",
        "code": "BNI-001",
        "name": "BNI KCU Harmoni",
        "branch_code": "001",
        "address": "Jakarta Pusat",
        "phone": "1500046",
        "email": "bnicall@bni.co.id",
        "contact_person": "Customer Service",
        "is_head_office": True,

    },

    {

        "bank_code": "BRI",
        "code": "BRI-001",
        "name": "BRI KC Gatot Subroto",
        "branch_code": "001",
        "address": "Jakarta Selatan",
        "phone": "1500017",
        "email": "callbri@bri.co.id",
        "contact_person": "Customer Service",
        "is_head_office": True,

    },

]

def seed_bank_branch() -> None:

    for row in BANK_BRANCHES:

        bank = Bank.objects.get(code=row["bank_code"])

        BankBranch.objects.update_or_create(

            bank=bank,

            code=row["code"],

            defaults={
                "name": row["name"],
                "branch_code": row["branch_code"],
                "address": row["address"],
                "phone": row["phone"],
                "email": row["email"],
                "contact_person": row["contact_person"],
                "is_head_office": row["is_head_office"],
                "city": None,
            },

        )