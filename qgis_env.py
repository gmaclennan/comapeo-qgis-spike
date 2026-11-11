"""Reports versions and guarded import availability inside a QGIS Python."""

import importlib
import os
import sys

lines = []


def report(line):
    print(line, flush=True)
    lines.append(line)


report("Python: %s" % sys.version.replace("\n", " "))
report("executable: %s" % sys.executable)
try:
    from qgis.core import Qgis

    report("QGIS: %s (%s)" % (Qgis.QGIS_VERSION, Qgis.QGIS_VERSION_INT))
except Exception as exc:
    report("QGIS: FAIL %r" % exc)
try:
    from qgis.PyQt.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    report("Qt: %s  PyQt: %s" % (QT_VERSION_STR, PYQT_VERSION_STR))
except Exception as exc:
    report("Qt: FAIL %r" % exc)

CHECKS = [
    ("qgis.PyQt.QtNetwork", "QLocalSocket"),
    ("qgis.PyQt.QtNetwork", "QLocalServer"),
    ("qgis.PyQt.QtMultimedia", "QMediaPlayer"),
    ("qgis.PyQt.QtMultimediaWidgets", "QVideoWidget"),
    ("qgis.gui", "QgsMediaWidget"),
    ("qgis.PyQt.QtWebSockets", "QWebSocket"),
    ("qgis.PyQt.QtWebEngineWidgets", "QWebEngineView"),
    ("qgis.PyQt.QtWebKitWidgets", "QWebView"),
]
for module_name, attr in CHECKS:
    try:
        module = importlib.import_module(module_name)
        getattr(module, attr)
        report("OK   %s.%s" % (module_name, attr))
    except Exception as exc:
        report("FAIL %s.%s: %s: %s" % (module_name, attr, type(exc).__name__, exc))

summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_path:
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("```\n%s\n```\n\n" % "\n".join(lines))
