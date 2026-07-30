from apps.framework.lookup import BaseLookupService

from .registry import LOOKUP_REGISTRY


class AccountLookupService(BaseLookupService):
    registry = LOOKUP_REGISTRY