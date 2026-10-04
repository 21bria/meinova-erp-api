from __future__ import annotations

from typing import Type

from .base import BaseImporter


class ImporterRegistry:
    def __init__(self) -> None:
        self._importers: dict[str, Type[BaseImporter]] = {}

    @staticmethod
    def normalize_module(module: str) -> str:
        return str(module or "").strip().strip("/").lower()

    def register(
        self,
        importer_class: Type[BaseImporter],
    ) -> Type[BaseImporter]:
        module = self.normalize_module(
            getattr(importer_class, "module", ""),
        )

        if not module:
            raise ValueError(
                f"{importer_class.__name__} harus menentukan "
                f"atribut 'module'."
            )

        existing = self._importers.get(module)

        if existing is not None and existing is not importer_class:
            raise ValueError(
                f"Importer untuk module '{module}' sudah terdaftar "
                f"oleh {existing.__name__}."
            )

        self._importers[module] = importer_class

        return importer_class

    def get(
        self,
        module: str,
    ) -> Type[BaseImporter] | None:
        return self._importers.get(
            self.normalize_module(module),
        )

    def all(self) -> dict[str, Type[BaseImporter]]:
        return dict(self._importers)


registry = ImporterRegistry()


def register_importer(
    importer_class: Type[BaseImporter],
) -> Type[BaseImporter]:
    return registry.register(importer_class)


def get_importer(
    module: str,
) -> Type[BaseImporter] | None:
    return registry.get(module)


def get_importer_or_raise(
    module: str,
) -> Type[BaseImporter]:
    importer = registry.get(module)

    if importer is None:
        raise ValueError(
            f"No importer registered for module '{module}'."
        )

    return importer
