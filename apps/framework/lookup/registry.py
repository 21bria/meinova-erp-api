# framework/lookup/registry.py

from typing import Type

from .base import BaseLookup

class LookupRegistry:

    def __init__(self):

        self._lookups: dict[str, Type[BaseLookup]] = {}

    def register(

        self,

        lookup_class: Type[BaseLookup],

    ) -> Type[BaseLookup]:

        lookup_name = lookup_class.get_key()

        if lookup_name in self._lookups:

            raise ValueError(

                f"Lookup '{lookup_name}' sudah terdaftar."

            )

        self._lookups[lookup_name] = lookup_class

        return lookup_class

    def get(

        self,

        lookup_name: str,

    ) -> Type[BaseLookup] | None:

        return self._lookups.get(lookup_name)

    def all(self) -> dict[str, Type[BaseLookup]]:

        return self._lookups.copy()

registry = LookupRegistry()