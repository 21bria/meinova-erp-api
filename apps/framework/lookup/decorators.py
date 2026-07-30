from .registry import registry


def register_lookup(cls):
    registry.register(cls)
    return cls