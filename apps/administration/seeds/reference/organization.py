from apps.administration.models.references.organization import (
    BranchType,
    CompanyType,
    SiteType,
    
)

from .base import seed_reference


ORGANIZATION_REFERENCE_DATA = {
    CompanyType: [
        ("HO", "Head Office"),
        ("SITE", "Site"),
        ("SUB", "Subsidiary"),
    ],
    BranchType: [
        ("HO", "Head Office"),
        ("BR", "Branch"),
        ("REP", "Representative Office"),
    ],
    SiteType: [
        ("MINE", "Mining Site"),
        ("PORT", "Port"),
        ("OFFICE", "Office"),
    ],
    
}


def seed_organization_reference() -> None:
    for model, rows in ORGANIZATION_REFERENCE_DATA.items():
        seed_reference(
            model,
            [
                {
                    "code": code,
                    "name": name,
                }
                for code, name in rows
            ],
        ) 