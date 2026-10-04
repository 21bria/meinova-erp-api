from apps.administration.models import Bank

from .base import seed_reference


BANKS = [
    # ==========================
    # Himbara / BUMN
    # ==========================
    ("MANDIRI", "Bank Mandiri"),
    ("BRI", "Bank Rakyat Indonesia"),
    ("BNI", "Bank Negara Indonesia"),
    ("BTN", "Bank Tabungan Negara"),

    # ==========================
    # Swasta Nasional
    # ==========================
    ("BCA", "Bank Central Asia"),
    ("CIMB", "CIMB Niaga"),
    ("PERMATA", "Bank Permata"),
    ("OCBC", "OCBC Indonesia"),
    ("DANAMON", "Bank Danamon"),
    ("PANIN", "Panin Bank"),
    ("MAYBANK", "Maybank Indonesia"),
    ("MEGA", "Bank Mega"),
    ("BUKOPIN", "Bank KB Bukopin"),
    ("UOB", "UOB Indonesia"),
    ("DBS", "DBS Indonesia"),
    ("HSBC", "HSBC Indonesia"),
    ("CITIBANK", "Citibank Indonesia"),
    ("MUFG", "MUFG Bank Indonesia"),
    ("MIZUHO", "Mizuho Bank Indonesia"),
    ("SMBC", "SMBC Indonesia"),
    ("COMMONWEALTH", "Commonwealth Bank Indonesia"),

    # ==========================
    # Digital Bank
    # ==========================
    ("BCA_DIGITAL", "BCA Digital (blu)"),
    ("SUPERBANK", "Superbank"),
    ("KROM", "Krom Bank Indonesia"),
    ("JAGO", "Bank Jago"),
    ("NEO", "Bank Neo Commerce"),
    ("SEABANK", "SeaBank Indonesia"),
    ("ALLO", "Allo Bank"),
    ("LINE", "Line Bank"),
    ("INA", "Bank INA"),
    ("AMAR", "Amar Bank"),

    # ==========================
    # Syariah
    # ==========================
    ("BSI", "Bank Syariah Indonesia"),
    ("MEGA_SYARIAH", "Bank Mega Syariah"),
    ("MUAMALAT", "Bank Muamalat Indonesia"),
    ("BTN_SYARIAH", "BTN Syariah"),
    ("BCA_SYARIAH", "BCA Syariah"),
    ("ALADIN", "Bank Aladin Syariah"),

    # ==========================
    # Lainnya
    # ==========================
    ("SINARMAS", "Bank Sinarmas"),
    ("MASPION", "Bank Maspion"),
    ("QNB", "Bank QNB Indonesia"),
    ("WOORI", "Bank Woori Saudara"),
    ("ARTHA", "Bank Artha Graha Internasional"),
    ("BTPN", "Bank BTPN"),
    ("NOBU", "Bank Nationalnobu"),
    ("MNC", "MNC Bank"),
    ("CAPITAL", "Bank Capital Indonesia"),
    ("VICTORIA", "Bank Victoria International"),
    ("GANESHA", "Bank Ganesha"),
    ("SAHIBA", "Bank Sahabat Sampoerna"),
    ("CTBC", "Bank CTBC Indonesia"),
    ("BNC", "Bank Neo Commerce"),
]

def seed_bank() -> None:
    seed_reference(
        Bank,
        [
            {
                "code": code,
                "name": name,
            }
            for code, name in BANKS
        ],
    )