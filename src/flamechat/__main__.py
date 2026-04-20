"""Entry point usable both as an installed console script and as a
PyInstaller-bundled app.

We use an *absolute* import of ``flamechat.app`` rather than the
relative ``from .app import run`` you might reach for by reflex.
Reason: PyInstaller runs this file as a plain top-level script (not
as ``flamechat.__main__``), which breaks relative imports with
``ImportError: attempted relative import with no known parent
package``. Absolute imports work both when the module is invoked via
``python -m flamechat`` during development and when PyInstaller calls
it as ``__main__``.
"""

from flamechat.app import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
