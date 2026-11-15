"""Windows integration for the direct-download edition: right-click menu, Send To, shortcuts.

Per-user (HKEY_CURRENT_USER / %APPDATA%), no admin rights needed. No-ops in the Store edition,
which declares its integration in AppxManifest.xml instead.
"""
import os
import subprocess
import sys
import winreg

import core
from core import APP_NAME

START_MENU = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
SENDTO = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\SendTo")
NO_WINDOW = 0x08000000
MENU_KEY = r"Software\Classes\SystemFileAssociations\.pdf\shell\PDFDrop"


def launch_parts():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return [pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(sys.argv[0])]


def icon_path():
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    return ico if os.path.exists(ico) else launch_parts()[0]


def set_explorer_menu(enabled):
    if core.PACKAGED:
        return
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Edit with PDFDrop")
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon_path())
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, subprocess.list2cmdline(launch_parts()) + ' "%1"')
    else:
        for sub in (MENU_KEY + r"\command", MENU_KEY):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
    lnk = os.path.join(SENDTO, f"{APP_NAME} (edit or merge).lnk")
    if enabled:
        make_shortcut(lnk)
    else:
        try:
            os.remove(lnk)
        except OSError:
            pass


def make_shortcut(lnk_path, extra_args=()):
    parts = launch_parts()
    target, args = parts[0], subprocess.list2cmdline(parts[1:] + list(extra_args))

    def ps(s):
        return "'" + s.replace("'", "''") + "'"

    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + ps(lnk_path) + ");"
        "$s.TargetPath=" + ps(target) + ";$s.Arguments=" + ps(args) + ";"
        "$s.IconLocation=" + ps(icon_path() + ",0") + ";$s.WorkingDirectory=" + ps(os.path.dirname(parts[-1]))
        + ";$s.Description=" + ps(APP_NAME + " - PDF toolkit and editor") + ";$s.Save()"
    )
    os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   creationflags=NO_WINDOW, check=False, timeout=30)


def desktop_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])
    except OSError:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def install_shortcuts():
    make_shortcut(os.path.join(START_MENU, f"{APP_NAME}.lnk"))
    make_shortcut(os.path.join(desktop_dir(), f"{APP_NAME}.lnk"))


def uninstall():
    set_explorer_menu(False)
    for lnk in (os.path.join(START_MENU, f"{APP_NAME}.lnk"), os.path.join(desktop_dir(), f"{APP_NAME}.lnk")):
        try:
            os.remove(lnk)
        except OSError:
            pass
