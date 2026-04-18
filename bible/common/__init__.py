def _get_version() -> str:
    from bible._version import version
    return version


__all__ = ["_get_version"]