"""Frozen native entry point; intentionally imports no training dependencies."""

import logging


def launch():
    try:
        from ceta_desktop.app import main
        return main()
    except Exception:
        from ceta_desktop.storage import application_directory
        directory = application_directory()
        directory.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=directory / "startup-error.log", level=logging.ERROR)
        logging.exception("CETA could not start")
        raise


if __name__ == "__main__":
    raise SystemExit(launch())
