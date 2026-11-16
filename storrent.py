#!/usr/bin/env python3
"""STorrent Pro — free, ad-free BitTorrent client by Smartupworld."""
import sys
import os
import re
import json
import time
import shutil
import random
import ctypes
import getpass
import tempfile
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque

import libtorrent as lt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QInputDialog, QLabel,
    QSpinBox, QDoubleSpinBox, QCheckBox, QTabWidget, QTextEdit, QPlainTextEdit,
    QMessageBox, QSplitter, QSystemTrayIcon, QMenu, QStyle, QDialog, QListWidget,
    QStackedWidget, QFormLayout, QLineEdit, QComboBox, QGroupBox, QTreeWidget,
    QTreeWidgetItem, QGridLayout, QStyledItemDelegate, QStyleOptionProgressBar,
    QAbstractItemView, QProgressBar
)
from PyQt6.QtGui import (
    QAction, QPalette, QColor, QDesktopServices, QIcon, QPainter, QPen, QKeySequence
)
from PyQt6.QtCore import QTimer, Qt, QUrl, QThread, pyqtSignal, QPointF
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


# ----------------------------------------------------------------------------
# Constants & paths
# ----------------------------------------------------------------------------
APP_NAME = "STorrent Pro"
APP_VERSION = "2.0.0"
ORG = "Smartupworld"
IS_WIN = sys.platform == "win32"
MUTEX_NAME = "STorrentProMutex"          # the installer uses the same name (AppMutex)
INCOMPLETE_EXT = ".!st"

try:
    _user = re.sub(r"[^A-Za-z0-9]", "", getpass.getuser()) or "user"
except Exception:
    _user = "user"
IPC_NAME = f"STorrentPro-{_user}"


def _data_dir():
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "STorrent")
    return os.path.join(os.path.expanduser("~"), ".storrent")


DATA_DIR = _data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
STATE_DIR = os.path.join(DATA_DIR, "state")
SESSION_FILE = os.path.join(DATA_DIR, "session.dat")
LEGACY_CONFIG = os.path.join(os.path.expanduser("~"), ".storrent_config.json")
LEGACY_STATE = os.path.join(os.path.expanduser("~"), ".storrent_state")

DEFAULT_DL = os.path.join(os.path.expanduser("~"), "Downloads")
MEDIA_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.m4v', '.wmv', '.mp3', '.flac', '.m4a',
              '.wav', '.ogg', '.webm', '.ts')
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEFAULTS = {
    # General
    "theme": "System", "start_with_windows": False, "start_minimized": True,
    "append_incomplete_ext": False, "preallocate": False, "prevent_standby": True,
    "notify_complete": True,
    # Privacy
    "anonymous_mode": False,
    # UI
    "confirm_delete_torrent": True, "confirm_delete_tracker": True, "confirm_exit": True,
    "alt_row_colors": True, "speed_in_title": False, "limits_in_status": True,
    "fine_priorities": False, "confirm_critical_seeder": True,
    "minimize_btn_to_tray": False, "always_show_tray": True, "close_btn_to_tray": True,
    "single_click_tray": False, "balloon_notifications": True, "always_activate_tray": True,
    "dont_start_auto": False, "activate_on_add": True, "ask_save_dir": False,
    "dbl_click_seeding": "Open Folder", "dbl_click_downloading": "Show Properties",
    # Directories
    "use_default_save_path": True, "save_path": DEFAULT_DL,
    "move_completed_enabled": False, "completed_path": DEFAULT_DL,
    "append_label_to_path": False, "only_move_from_default": True,
    "store_torrents_enabled": False, "store_torrents_path": "",
    "move_finished_torrents": False, "finished_torrents_path": "",
    "watch_enabled": False, "watch_path": "", "delete_loaded_torrents": False,
    # Connection
    "listen_port": 31405, "randomize_port_start": False, "enable_upnp": True,
    "enable_natpmp": True, "add_firewall_rule": True, "bind_interface": "",
    "proxy_type": "(none)", "proxy_host": "", "proxy_port": 8080, "proxy_auth": False,
    "proxy_user": "", "proxy_pass": "", "proxy_hostnames": True, "proxy_p2p": True,
    "disable_leaks": False,
    # Bandwidth
    "max_ul_kbps": 0, "max_dl_kbps": 0, "max_connections": 500,
    "max_peers_per_torrent": 100, "upload_slots": 8,
    # BitTorrent
    "enable_dht": True, "enable_lsd": True, "enable_pex": True, "enable_utp": True,
    "encryption": "Enabled", "blocklist_path": "",
    # Transfer cap
    "transfer_cap_enabled": False, "transfer_cap_gb": 500.0, "transfer_cap_period": "Monthly",
    "cap_used_bytes": 0, "cap_period_key": "",
    # Queueing
    "active_limit": 8, "active_downloads": 5, "active_seeds": 5,
    "dont_count_slow": True, "seed_ratio_limit": 0.0, "seed_time_limit_min": 0,
    # Scheduler / speed limiter
    "scheduler_enabled": False, "scheduler_start_hour": 9, "scheduler_end_hour": 18,
    "scheduler_days": [0, 1, 2, 3, 4, 5, 6], "scheduler_dl_kbps": 500, "scheduler_ul_kbps": 100,
    # Labels / RSS
    "labels": ["Movies", "Software", "Music", "Games"],
    "rss_feeds": [], "rss_filters": [], "rss_auto_download": False, "rss_refresh_min": 30,
    # Internal state
    "torrent_labels": {}, "finished_hashes": [], "goal_done": [], "stored_torrents": {},
    "rss_seen": [],
}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def app_icon():
    for n in ("storrent.ico", "storrent.png"):
        p = resource_path(n)
        if os.path.exists(p):
            return QIcon(p)
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)


def fmt_bytes(size):
    size = float(size or 0)
    for unit in ['B', 'kB', 'MB', 'GB', 'TB']:
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def fmt_speed(rate):
    return f"{fmt_bytes(rate)}/s"


def fmt_eta(remaining, rate):
    if rate <= 0 or remaining <= 0:
        return "∞" if remaining > 0 else ""
    secs = int(remaining / rate)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def ih_of(h):
    try:
        return str(h.info_hash())
    except Exception:
        return str(h.info_hashes().get_best())


def request_resume(h):
    try:
        h.save_resume_data(lt.torrent_handle.save_info_dict)
        return True
    except Exception:
        try:
            h.save_resume_data()
            return True
        except Exception:
            return False


def alert_mask():
    try:
        c = lt.alert_category
        return int(c.error) | int(c.status) | int(c.storage)
    except Exception:
        c = lt.alert.category_t
        return int(c.error_notification) | int(c.status_notification) | int(c.storage_notification)


def share_ratio(s):
    denom = max(s.all_time_download, s.total_wanted, 1)
    return s.all_time_upload / denom


def seeding_seconds(s):
    v = getattr(s, "seeding_duration", None)
    if v is not None:
        try:
            return v.total_seconds()
        except AttributeError:
            return float(v)
    return float(getattr(s, "seeding_time", 0))


def error_text(s):
    try:
        if s.errc.value():
            return s.errc.message()
    except Exception:
        pass
    return ""


def readonly_item(text=""):
    it = QTableWidgetItem(text)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return it


def set_cell(table, row, col, text, data=None):
    it = table.item(row, col)
    if it is None:
        it = readonly_item()
        table.setItem(row, col, it)
    if it.text() != text:
        it.setText(text)
    if data is not None and it.data(Qt.ItemDataRole.UserRole) != data:
        it.setData(Qt.ItemDataRole.UserRole, data)


# ----------------------------------------------------------------------------
# Windows integration (startup, file association, sleep, firewall)
# ----------------------------------------------------------------------------
def launch_command(extra=""):
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        py = sys.executable
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.exists(pyw):
            py = pyw
        cmd = f'"{py}" "{os.path.abspath(__file__)}"'
    return f"{cmd} {extra}".strip()


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_autostart():
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled, minimized=True):
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ,
                                  launch_command("--minimized" if minimized else ""))
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def register_associations():
    """Make STorrent the handler for .torrent files and magnet: links (current user)."""
    if not IS_WIN:
        return False
    import winreg
    open_cmd = launch_command('"%1"')
    icon = f'"{sys.executable}",0'

    def put(path, name, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    try:
        c = r"Software\Classes"
        put(rf"{c}\.torrent", "", "STorrent.Torrent")
        put(rf"{c}\.torrent", "Content Type", "application/x-bittorrent")
        put(rf"{c}\STorrent.Torrent", "", "BitTorrent File")
        put(rf"{c}\STorrent.Torrent\DefaultIcon", "", icon)
        put(rf"{c}\STorrent.Torrent\shell\open\command", "", open_cmd)
        put(rf"{c}\magnet", "", "URL:Magnet Link")
        put(rf"{c}\magnet", "URL Protocol", "")
        put(rf"{c}\magnet\DefaultIcon", "", icon)
        put(rf"{c}\magnet\shell\open\command", "", open_cmd)
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        return True
    except OSError:
        return False


def set_keep_awake(on):
    if IS_WIN:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def firewall_rule(add):
    """Adds/removes the inbound firewall rule. Shows one Windows admin (UAC) prompt."""
    if not IS_WIN:
        return
    if add:
        params = (f'advfirewall firewall add rule name="{APP_NAME}" dir=in action=allow '
                  f'program="{sys.executable}" enable=yes')
    else:
        params = f'advfirewall firewall delete rule name="{APP_NAME}"'
    ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", params, None, 0)


# ----------------------------------------------------------------------------
# Themes — Fusion style + explicit palettes so text is always readable
# ----------------------------------------------------------------------------
def build_palette(dark):
    p = QPalette()
    if dark:
        c = {"win": "#2d2d30", "text": "#f0f0f0", "base": "#1e1e1e", "alt": "#262629",
             "btn": "#3a3a3d", "hl": "#0a7acc", "tip": "#3a3a3d", "dis": "#808080", "link": "#4ea3ff"}
    else:
        c = {"win": "#f3f3f3", "text": "#1a1a1a", "base": "#ffffff", "alt": "#f4f7fb",
             "btn": "#ececec", "hl": "#0078d7", "tip": "#ffffe1", "dis": "#9a9a9a", "link": "#0063b1"}
    R = QPalette.ColorRole
    G = QPalette.ColorGroup
    for group in (G.Active, G.Inactive):
        p.setColor(group, R.Window, QColor(c["win"]))
        p.setColor(group, R.WindowText, QColor(c["text"]))
        p.setColor(group, R.Base, QColor(c["base"]))
        p.setColor(group, R.AlternateBase, QColor(c["alt"]))
        p.setColor(group, R.ToolTipBase, QColor(c["tip"]))
        p.setColor(group, R.ToolTipText, QColor(c["text"]))
        p.setColor(group, R.Text, QColor(c["text"]))
        p.setColor(group, R.Button, QColor(c["btn"]))
        p.setColor(group, R.ButtonText, QColor(c["text"]))
        p.setColor(group, R.BrightText, QColor("#ff4040"))
        p.setColor(group, R.Highlight, QColor(c["hl"]))
        p.setColor(group, R.HighlightedText, QColor("#ffffff"))
        p.setColor(group, R.Link, QColor(c["link"]))
        p.setColor(group, R.PlaceholderText, QColor(c["dis"]))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, QColor(c["dis"]))
    p.setColor(G.Disabled, R.Window, QColor(c["win"]))
    p.setColor(G.Disabled, R.Base, QColor(c["win"]))
    p.setColor(G.Disabled, R.Button, QColor(c["btn"]))
    return p


def system_is_dark():
    try:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        pass
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    return False


# ----------------------------------------------------------------------------
# Widgets
# ----------------------------------------------------------------------------
class ProgressDelegate(QStyledItemDelegate):
    """Draws a progress bar in cells whose UserRole holds a float 0..1."""

    def paint(self, painter, option, index):
        val = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(val, float):
            return super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        opt = QStyleOptionProgressBar()
        opt.rect = option.rect.adjusted(3, 3, -3, -3)
        opt.minimum, opt.maximum = 0, 1000
        opt.progress = int(max(0.0, min(1.0, val)) * 1000)
        opt.text = f"{val * 100:.1f}%"
        opt.textVisible = True
        opt.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Horizontal
        opt.palette = option.palette
        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, opt, painter)


class SpeedGraph(QWidget):
    POINTS = 300

    def __init__(self):
        super().__init__()
        self.dl = deque([0] * self.POINTS, maxlen=self.POINTS)
        self.ul = deque([0] * self.POINTS, maxlen=self.POINTS)
        self.info = ""
        self.setMinimumHeight(140)

    def add(self, d, u, info=""):
        self.dl.append(d)
        self.ul.append(u)
        self.info = info
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base))
        r = self.rect().adjusted(70, 12, -12, -28)
        top = max(max(self.dl), max(self.ul), 10 * 1024) * 1.15
        grid = QColor(pal.color(QPalette.ColorRole.Text))
        grid.setAlpha(40)
        p.setPen(QPen(grid, 1))
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            p.drawLine(int(r.left()), int(y), int(r.right()), int(y))
            p.setPen(pal.color(QPalette.ColorRole.Text))
            p.drawText(4, int(y) + 4, fmt_speed(top * i / 4))
            p.setPen(QPen(grid, 1))
        step = r.width() / (self.POINTS - 1)
        for series, color in ((self.dl, QColor("#2e9f4b")), (self.ul, QColor("#2f7fd6"))):
            p.setPen(QPen(color, 2))
            pts = [QPointF(r.left() + i * step, r.bottom() - r.height() * v / top) for i, v in enumerate(series)]
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
        p.setPen(QColor("#2e9f4b"))
        p.drawText(int(r.left()), self.height() - 8, f"■ Download {fmt_speed(self.dl[-1])}")
        p.setPen(QColor("#2f7fd6"))
        p.drawText(int(r.left()) + 190, self.height() - 8, f"■ Upload {fmt_speed(self.ul[-1])}")
        p.setPen(pal.color(QPalette.ColorRole.Text))
        p.drawText(int(r.left()) + 380, self.height() - 8, self.info)


# ----------------------------------------------------------------------------
# Background workers
# ----------------------------------------------------------------------------
def _local(tag):
    return tag.rsplit('}', 1)[-1]


def parse_feed(xml_data, feed_url):
    items = []
    root = ET.fromstring(xml_data)
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title, link = "Unknown", ""
        for ch in node:
            tag = _local(ch.tag)
            if tag == "title" and ch.text:
                title = ch.text.strip()
            elif tag == "link":
                link = link or (ch.text or ch.attrib.get("href", "")).strip()
            elif tag == "enclosure" and ch.attrib.get("url"):
                link = ch.attrib["url"]
            elif tag.lower() == "magneturi" and ch.text:
                link = ch.text.strip()
        items.append({"title": title, "feed": feed_url, "link": link})
    return items


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': f'{APP_NAME}/{APP_VERSION}'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class RssWorker(QThread):
    done = pyqtSignal(list)

    def __init__(self, feeds):
        super().__init__()
        self.feeds = feeds

    def run(self):
        out = []
        for url in self.feeds:
            try:
                out.extend(parse_feed(http_get(url), url))
            except Exception as e:
                out.append({"title": f"Feed error: {e}", "feed": url, "link": "", "error": True})
        self.done.emit(out)


class UrlTorrentWorker(QThread):
    done = pyqtSignal(str, str)   # (temp file path or "", error)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            data = http_get(self.url, 30)
            fd, path = tempfile.mkstemp(suffix=".torrent", dir=DATA_DIR)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self.done.emit(path, "")
        except Exception as e:
            self.done.emit("", str(e))


class CreateTorrentWorker(QThread):
    done = pyqtSignal(str, str)   # (output path, error)

    def __init__(self, src, out, trackers, comment, private, piece_size):
        super().__init__()
        self.args = (src, out, trackers, comment, private, piece_size)

    def run(self):
        src, out, trackers, comment, private, piece_size = self.args
        try:
            fs = lt.file_storage()
            lt.add_files(fs, src)
            if fs.num_files() == 0:
                raise ValueError("No files found in the selected location.")
            t = lt.create_torrent(fs, piece_size)
            for tier, url in enumerate(trackers):
                t.add_tracker(url, tier)
            t.set_creator(f"{APP_NAME} {APP_VERSION}")
            if comment:
                t.set_comment(comment)
            t.set_priv(private)
            lt.set_piece_hashes(t, os.path.dirname(os.path.abspath(src)))
            with open(out, "wb") as f:
                f.write(lt.bencode(t.generate()))
            self.done.emit(out, "")
        except Exception as e:
            self.done.emit("", str(e))


# ----------------------------------------------------------------------------
# Dialogs
# ----------------------------------------------------------------------------
class AddTorrentDialog(QDialog):
    def __init__(self, parent, ti, name, default_dir, labels, start_default):
        super().__init__(parent)
        self.setWindowTitle(f"Add Torrent — {name}")
        self.resize(680, 520)
        self.ti = ti
        lay = QVBoxLayout(self)

        form = QFormLayout()
        row = QHBoxLayout()
        self.txt_path = QLineEdit(default_dir)
        self.txt_path.textChanged.connect(self.update_summary)
        b = QPushButton("...")
        b.setFixedWidth(35)
        b.clicked.connect(self.browse)
        row.addWidget(self.txt_path)
        row.addWidget(b)
        form.addRow("Save in:", row)
        self.cmb_label = QComboBox()
        self.cmb_label.setEditable(True)
        self.cmb_label.addItems([""] + list(labels))
        form.addRow("Label:", self.cmb_label)
        self.chk_start = QCheckBox("Start torrent")
        self.chk_start.setChecked(start_default)
        self.chk_seq = QCheckBox("Sequential download (for streaming)")
        form.addRow(self.chk_start)
        form.addRow(self.chk_seq)
        lay.addLayout(form)

        self.tree = None
        if ti is not None:
            self.tree = QTreeWidget()
            self.tree.setHeaderLabels(["File", "Size"])
            self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            fs = ti.files()
            for i in range(fs.num_files()):
                it = QTreeWidgetItem([fs.file_path(i), fmt_bytes(fs.file_size(i))])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked)
                it.setData(0, Qt.ItemDataRole.UserRole, fs.file_size(i))
                self.tree.addTopLevelItem(it)
            self.tree.itemChanged.connect(self.update_summary)
            lay.addWidget(self.tree)
            sel = QHBoxLayout()
            for text, state in (("Select all", True), ("Select none", False)):
                bt = QPushButton(text)
                bt.clicked.connect(lambda _, s=state: self.set_all(s))
                sel.addWidget(bt)
            sel.addStretch()
            lay.addLayout(sel)
        else:
            lay.addWidget(QLabel("File list will be available once metadata is downloaded from peers."))
            lay.addStretch()

        self.lbl_summary = QLabel()
        lay.addWidget(self.lbl_summary)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)
        self.update_summary()

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save torrent in", self.txt_path.text())
        if d:
            self.txt_path.setText(d)

    def set_all(self, state):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.update_summary()

    def update_summary(self, *_):
        parts = []
        if self.tree:
            total = sum(self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                        for i in range(self.tree.topLevelItemCount())
                        if self.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked)
            parts.append(f"Selected: {fmt_bytes(total)}")
        path = self.txt_path.text()
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        try:
            parts.append(f"Free space on disk: {fmt_bytes(shutil.disk_usage(probe).free)}")
        except Exception:
            pass
        self.lbl_summary.setText("   |   ".join(parts))

    def values(self):
        prios = None
        if self.tree:
            prios = [4 if self.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked else 0
                     for i in range(self.tree.topLevelItemCount())]
        return {"save_path": self.txt_path.text().strip(), "label": self.cmb_label.currentText().strip(),
                "start": self.chk_start.isChecked(), "sequential": self.chk_seq.isChecked(),
                "priorities": prios}


class CreateTorrentDialog(QDialog):
    PIECES = [("Auto", 0), ("256 kB", 256 << 10), ("512 kB", 512 << 10), ("1 MB", 1 << 20),
              ("2 MB", 2 << 20), ("4 MB", 4 << 20), ("8 MB", 8 << 20), ("16 MB", 16 << 20)]

    def __init__(self, parent):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Create New Torrent")
        self.resize(600, 480)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        self.txt_src = QLineEdit()
        bf = QPushButton("Add file")
        bf.clicked.connect(self.pick_file)
        bd = QPushButton("Add folder")
        bd.clicked.connect(self.pick_dir)
        row.addWidget(self.txt_src)
        row.addWidget(bf)
        row.addWidget(bd)
        form.addRow("Source:", row)
        self.txt_trackers = QPlainTextEdit()
        self.txt_trackers.setPlaceholderText("udp://tracker.opentrackr.org:1337/announce\n(one tracker per line)")
        form.addRow("Trackers:", self.txt_trackers)
        self.txt_comment = QLineEdit()
        form.addRow("Comment:", self.txt_comment)
        self.cmb_piece = QComboBox()
        self.cmb_piece.addItems([p[0] for p in self.PIECES])
        form.addRow("Piece size:", self.cmb_piece)
        self.chk_private = QCheckBox("Private torrent (no DHT/PEX)")
        self.chk_seed = QCheckBox("Start seeding")
        self.chk_seed.setChecked(True)
        form.addRow(self.chk_private)
        form.addRow(self.chk_seed)
        lay.addLayout(form)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        lay.addWidget(self.progress)
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_create = QPushButton("Create and save as...")
        self.btn_create.clicked.connect(self.create)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(self.btn_create)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.worker = None

    def pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select file")
        if f:
            self.txt_src.setText(f)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select folder")
        if d:
            self.txt_src.setText(d)

    def create(self):
        src = self.txt_src.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Create Torrent", "Choose a file or folder first.")
            return
        default = os.path.join(os.path.dirname(src), os.path.basename(src.rstrip("/\\")) + ".torrent")
        out, _ = QFileDialog.getSaveFileName(self, "Save .torrent", default, "Torrent Files (*.torrent)")
        if not out:
            return
        trackers = [t.strip() for t in self.txt_trackers.toPlainText().splitlines() if t.strip()]
        self.btn_create.setEnabled(False)
        self.progress.show()
        self.worker = CreateTorrentWorker(src, out, trackers, self.txt_comment.text().strip(),
                                          self.chk_private.isChecked(),
                                          self.PIECES[self.cmb_piece.currentIndex()][1])
        self.worker.done.connect(lambda o, e: self.finished_create(o, e, src))
        self.worker.start()

    def finished_create(self, out, err, src):
        self.progress.hide()
        self.btn_create.setEnabled(True)
        if err:
            QMessageBox.warning(self, "Create Torrent", f"Failed: {err}")
            return
        if self.chk_seed.isChecked():
            self.main.add_torrent_file(out, interactive=False, save_dir=os.path.dirname(os.path.abspath(src)))
        QMessageBox.information(self, "Create Torrent", f"Torrent saved:\n{out}")
        self.accept()


class PreferencesDialog(QDialog):
    PAGES = ["General", "Privacy", "UI Settings", "Directories", "Connection", "Bandwidth",
             "BitTorrent", "Transfer Cap", "Queueing", "Scheduler", "Label", "RSS Feeds"]

    def __init__(self, config, parent):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle(f"Preferences — {APP_NAME}")
        self.resize(860, 600)
        self.config = json.loads(json.dumps(config))
        self._binds = []

        layout = QHBoxLayout(self)
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(165)
        self.nav_list.addItems(self.PAGES)
        self.nav_list.currentRowChanged.connect(self.switch_page)
        layout.addWidget(self.nav_list)

        right = QVBoxLayout()
        self.header_banner = QLabel("  General")
        self.header_banner.setFixedHeight(32)
        self.header_banner.setStyleSheet(
            "background-color: #0078D7; color: white; font-weight: bold; font-size: 14px; border-radius: 2px;")
        right.addWidget(self.header_banner)
        self.pages = QStackedWidget()
        right.addWidget(self.pages)
        for name in self.PAGES:
            getattr(self, "page_" + name.lower().replace(" ", "_"))()

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        for text, slot in (("OK", self.save_and_accept), ("Cancel", self.reject), ("Apply", self.apply_only)):
            b = QPushButton(text)
            b.setFixedWidth(80)
            b.clicked.connect(slot)
            btn_box.addWidget(b)
        right.addLayout(btn_box)
        layout.addLayout(right)
        self.nav_list.setCurrentRow(0)

    # -- binding helpers --------------------------------------------------
    def chk(self, key, text):
        w = QCheckBox(text)
        w.setChecked(bool(self.config.get(key, DEFAULTS.get(key, False))))
        self._binds.append((key, w))
        return w

    def spin(self, key, lo, hi, suffix=""):
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setValue(int(self.config.get(key, DEFAULTS.get(key, 0))))
        if suffix:
            w.setSuffix(suffix)
        self._binds.append((key, w))
        return w

    def dspin(self, key, lo, hi, step=0.1, suffix=""):
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setValue(float(self.config.get(key, DEFAULTS.get(key, 0.0))))
        if suffix:
            w.setSuffix(suffix)
        self._binds.append((key, w))
        return w

    def combo(self, key, items):
        w = QComboBox()
        w.addItems(items)
        w.setCurrentText(str(self.config.get(key, DEFAULTS.get(key, items[0]))))
        self._binds.append((key, w))
        return w

    def line(self, key, password=False, placeholder=""):
        w = QLineEdit(str(self.config.get(key, DEFAULTS.get(key, ""))))
        if password:
            w.setEchoMode(QLineEdit.EchoMode.Password)
        if placeholder:
            w.setPlaceholderText(placeholder)
        self._binds.append((key, w))
        return w

    def path_row(self, key, file_filter=None):
        row = QHBoxLayout()
        w = self.line(key)
        b = QPushButton("...")
        b.setFixedWidth(35)

        def browse():
            if file_filter:
                f, _ = QFileDialog.getOpenFileName(self, "Select file", w.text(), file_filter)
            else:
                f = QFileDialog.getExistingDirectory(self, "Select Directory", w.text())
            if f:
                w.setText(f)
        b.clicked.connect(browse)
        row.addWidget(w)
        row.addWidget(b)
        return row

    def text_list(self, key):
        w = QPlainTextEdit("\n".join(self.config.get(key, DEFAULTS.get(key, []))))
        self._binds.append((key, w))
        return w

    def new_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.pages.addWidget(page)
        return lay

    @staticmethod
    def grid(group, widgets, cols=2):
        g = QGridLayout(group)
        for i, w in enumerate(widgets):
            g.addWidget(w, i // cols, i % cols)
        return g

    # -- pages -------------------------------------------------------------
    def page_general(self):
        lay = self.new_page()
        grp = QGroupBox("Windows Integration")
        gl = QVBoxLayout(grp)
        if IS_WIN:
            self.config["start_with_windows"] = is_autostart()
        c1 = self.chk("start_with_windows", "Start STorrent when Windows starts")
        c2 = self.chk("start_minimized", "Start minimized to the tray")
        if not IS_WIN:
            c1.setEnabled(False)
            c2.setEnabled(False)
        gl.addWidget(c1)
        gl.addWidget(c2)
        b = QPushButton("Make STorrent the default app for .torrent files and magnet links")
        b.setEnabled(IS_WIN)
        b.clicked.connect(self.do_associate)
        gl.addWidget(b)
        lay.addWidget(grp)

        grp = QGroupBox("Appearance")
        fl = QFormLayout(grp)
        fl.addRow("Theme:", self.combo("theme", ["System", "Light", "Dark"]))
        lay.addWidget(grp)

        grp = QGroupBox("When Downloading")
        dl = QVBoxLayout(grp)
        dl.addWidget(self.chk("append_incomplete_ext", f"Append {INCOMPLETE_EXT} to incomplete files"))
        dl.addWidget(self.chk("preallocate", "Pre-allocate all files on disk"))
        dl.addWidget(self.chk("prevent_standby", "Prevent standby (sleep) while torrents are downloading"))
        dl.addWidget(self.chk("notify_complete", "Show a notification when a download completes"))
        lay.addWidget(grp)
        lay.addStretch()

    def do_associate(self):
        ok = register_associations()
        QMessageBox.information(self, "File association",
                                "Done. .torrent files and magnet links now open in STorrent."
                                if ok else "Could not change the association.")

    def page_privacy(self):
        lay = self.new_page()
        grp = QGroupBox("Privacy & Telemetry")
        pl = QVBoxLayout(grp)
        lbl = QLabel(f"{APP_NAME} by {ORG} contains zero ads, zero trackers, and zero telemetry.")
        lbl.setWordWrap(True)
        pl.addWidget(lbl)
        pl.addWidget(self.chk("anonymous_mode", "Enable Anonymous Mode (hide client name, version and local IP from peers)"))
        lay.addWidget(grp)
        lay.addStretch()

    def page_ui_settings(self):
        lay = self.new_page()
        grp = QGroupBox("Display Options")
        self.grid(grp, [
            self.chk("confirm_delete_torrent", "Confirm when deleting torrents"),
            self.chk("confirm_delete_tracker", "Confirm when deleting trackers"),
            self.chk("confirm_exit", "Show confirmation dialog on exit"),
            self.chk("alt_row_colors", "Alternate list background color"),
            self.chk("speed_in_title", "Show current speed in the title bar"),
            self.chk("limits_in_status", "Show speed limits in the status bar"),
            self.chk("fine_priorities", "Use fine grained file priorities"),
            self.chk("confirm_critical_seeder", "Confirm exit if critical seeder"),
        ])
        lay.addWidget(grp)
        grp = QGroupBox("System Tray")
        self.grid(grp, [
            self.chk("minimize_btn_to_tray", "Minimize button minimizes ST to tray"),
            self.chk("always_show_tray", "Always show tray icon"),
            self.chk("close_btn_to_tray", "Close button closes ST to tray"),
            self.chk("single_click_tray", "Single click on tray icon to open"),
            self.chk("balloon_notifications", "Show balloon notifications in tray"),
            self.chk("always_activate_tray", "Always activate when clicked"),
        ])
        lay.addWidget(grp)
        grp = QGroupBox("When Adding Torrents")
        g = self.grid(grp, [self.chk("dont_start_auto", "Don't start the download automatically"),
                            self.chk("activate_on_add", "Activate the program window")])
        g.addWidget(self.chk("ask_save_dir", "Show options to choose location, files and label"), 1, 0, 1, 2)
        lay.addWidget(grp)
        grp = QGroupBox("Actions for Double Click")
        fl = QFormLayout(grp)
        acts = ["Open Folder", "Show Properties", "Start/Stop", "Play Media"]
        fl.addRow("For seeding torrents:", self.combo("dbl_click_seeding", acts))
        fl.addRow("For downloading torrents:", self.combo("dbl_click_downloading", acts))
        lay.addWidget(grp)

    def page_directories(self):
        lay = self.new_page()
        grp = QGroupBox("Location of Downloaded Files")
        gl = QVBoxLayout(grp)
        gl.addWidget(self.chk("use_default_save_path", "Put new downloads in:"))
        gl.addLayout(self.path_row("save_path"))
        r = QHBoxLayout()
        r.addWidget(self.chk("move_completed_enabled", "Move completed downloads to:"))
        r.addWidget(self.chk("append_label_to_path", "Append the torrent's label"))
        gl.addLayout(r)
        gl.addLayout(self.path_row("completed_path"))
        gl.addWidget(self.chk("only_move_from_default", "Only move from the default download directory"))
        lay.addWidget(grp)

        grp = QGroupBox("Location of .torrents")
        tl = QVBoxLayout(grp)
        tl.addWidget(self.chk("store_torrents_enabled", "Store .torrents in:"))
        tl.addLayout(self.path_row("store_torrents_path"))
        tl.addWidget(self.chk("move_finished_torrents", "Move .torrents for finished jobs to:"))
        tl.addLayout(self.path_row("finished_torrents_path"))
        r = QHBoxLayout()
        r.addWidget(self.chk("watch_enabled", "Automatically load .torrents from:"))
        r.addWidget(self.chk("delete_loaded_torrents", "Delete loaded .torrents"))
        tl.addLayout(r)
        tl.addLayout(self.path_row("watch_path"))
        lay.addWidget(grp)
        lay.addStretch()

    def page_connection(self):
        lay = self.new_page()
        grp = QGroupBox("Listening Port")
        pl = QGridLayout(grp)
        pl.addWidget(QLabel("Port used for incoming connections:"), 0, 0)
        pb = QHBoxLayout()
        sp = self.spin("listen_port", 1024, 65535)
        br = QPushButton("Random port")
        br.clicked.connect(lambda: sp.setValue(random.randint(10000, 64000)))
        pb.addWidget(sp)
        pb.addWidget(br)
        pl.addLayout(pb, 0, 1)
        pl.addWidget(self.chk("enable_upnp", "Enable UPnP port mapping"), 1, 0)
        pl.addWidget(self.chk("randomize_port_start", "Randomize port each start"), 1, 1)
        pl.addWidget(self.chk("enable_natpmp", "Enable NAT-PMP port mapping"), 2, 0)
        fw = self.chk("add_firewall_rule", "Add Windows Firewall exception")
        fw.setEnabled(IS_WIN)
        pl.addWidget(fw, 2, 1)
        pl.addWidget(QLabel("Bind to network interface / VPN:"), 3, 0)
        pl.addWidget(self.line("bind_interface", placeholder="empty = any; e.g. 10.8.0.2 or VPN adapter name"), 3, 1)
        lay.addWidget(grp)

        grp = QGroupBox("Proxy Server")
        prl = QGridLayout(grp)
        prl.addWidget(QLabel("Type:"), 0, 0)
        prl.addWidget(self.combo("proxy_type", ["(none)", "SOCKS4", "SOCKS5", "HTTP"]), 0, 1)
        prl.addWidget(QLabel("Proxy:"), 0, 2)
        prl.addWidget(self.line("proxy_host"), 0, 3)
        prl.addWidget(QLabel("Port:"), 0, 4)
        prl.addWidget(self.spin("proxy_port", 1, 65535), 0, 5)
        prl.addWidget(self.chk("proxy_auth", "Authentication"), 1, 0)
        prl.addWidget(QLabel("Username:"), 1, 1)
        prl.addWidget(self.line("proxy_user"), 1, 2)
        prl.addWidget(QLabel("Password:"), 1, 3)
        prl.addWidget(self.line("proxy_pass", password=True), 1, 4, 1, 2)
        prl.addWidget(self.chk("proxy_hostnames", "Use proxy for hostname lookups"), 2, 0, 1, 3)
        prl.addWidget(self.chk("proxy_p2p", "Use proxy for peer-to-peer connections"), 3, 0, 1, 3)
        lay.addWidget(grp)

        grp = QGroupBox("Proxy Privacy")
        pvl = QVBoxLayout(grp)
        pvl.addWidget(self.chk("disable_leaks",
                               "Disable features that leak identifying information (turns off UPnP, NAT-PMP, LSD; enables anonymous mode)"))
        lay.addWidget(grp)
        lay.addStretch()

    def page_bandwidth(self):
        lay = self.new_page()
        grp = QGroupBox("Global Rate Limiting (0 = Unlimited)")
        fl = QFormLayout(grp)
        fl.addRow("Maximum upload rate:", self.spin("max_ul_kbps", 0, 1000000, " kB/s"))
        fl.addRow("Maximum download rate:", self.spin("max_dl_kbps", 0, 1000000, " kB/s"))
        lay.addWidget(grp)
        grp = QGroupBox("Number of Connections")
        cl = QFormLayout(grp)
        cl.addRow("Global maximum number of connections:", self.spin("max_connections", 10, 5000))
        cl.addRow("Maximum number of connected peers per torrent:", self.spin("max_peers_per_torrent", 5, 1000))
        cl.addRow("Number of upload slots per torrent:", self.spin("upload_slots", 1, 100))
        lay.addWidget(grp)
        lay.addStretch()

    def page_bittorrent(self):
        lay = self.new_page()
        grp = QGroupBox("Basic BitTorrent Features")
        self.grid(grp, [self.chk("enable_dht", "Enable DHT Network"),
                        self.chk("enable_lsd", "Enable Local Peer Discovery"),
                        self.chk("enable_pex", "Enable Peer Exchange (PEX)"),
                        self.chk("enable_utp", "Enable bandwidth management [uTP]")])
        lay.addWidget(grp)
        grp = QGroupBox("Protocol Encryption")
        el = QFormLayout(grp)
        el.addRow("Outgoing:", self.combo("encryption", ["Enabled", "Forced", "Disabled"]))
        lay.addWidget(grp)
        grp = QGroupBox("IP Filter (ipfilter.dat / blocklist.p2p)")
        il = QFormLayout(grp)
        il.addRow("IP Blocklist Path:", self.path_row("blocklist_path", "Blocklist Files (*.p2p *.dat *.txt);;All files (*)"))
        lay.addWidget(grp)
        lay.addStretch()

    def page_transfer_cap(self):
        lay = self.new_page()
        grp = QGroupBox("Transfer Cap Settings")
        fl = QFormLayout(grp)
        fl.addRow(self.chk("transfer_cap_enabled", "Enable Transfer Cap (auto-pause all torrents when reached)"))
        fl.addRow("Cap (download + upload):", self.dspin("transfer_cap_gb", 0.1, 100000.0, 1.0, " GB"))
        fl.addRow("Reset the counter:", self.combo("transfer_cap_period", ["Monthly", "Daily", "Session"]))
        used = QLabel(f"Used so far: {fmt_bytes(self.config.get('cap_used_bytes', 0))}")
        rst = QPushButton("Reset counter now")

        def reset():
            self.config["cap_used_bytes"] = 0
            self.config["cap_reset_now"] = True
            used.setText("Used so far: 0.0 B")
        rst.clicked.connect(reset)
        fl.addRow(used, rst)
        lay.addWidget(grp)
        lay.addStretch()

    def page_queueing(self):
        lay = self.new_page()
        grp = QGroupBox("Queue Settings")
        ql = QFormLayout(grp)
        ql.addRow("Maximum number of active torrents (upload or download):", self.spin("active_limit", 1, 500))
        ql.addRow("Maximum number of active downloads:", self.spin("active_downloads", 1, 500))
        ql.addRow("Maximum number of active seeds:", self.spin("active_seeds", 1, 500))
        ql.addRow(self.chk("dont_count_slow", "Don't count slow torrents toward these limits"))
        lay.addWidget(grp)
        grp = QGroupBox("Seeding Goal (stop seeding when reached)")
        sl = QFormLayout(grp)
        sl.addRow("Minimum ratio (0 = seed forever):", self.dspin("seed_ratio_limit", 0.0, 100.0))
        sl.addRow("Minimum seeding time (0 = forever):", self.spin("seed_time_limit_min", 0, 1000000, " min"))
        lay.addWidget(grp)
        lay.addStretch()

    def page_scheduler(self):
        lay = self.new_page()
        grp = QGroupBox("Bandwidth Scheduler")
        fl = QFormLayout(grp)
        fl.addRow(self.chk("scheduler_enabled", "Enable Scheduler (limit speeds during these hours)"))
        fl.addRow("From hour (0-23):", self.spin("scheduler_start_hour", 0, 23))
        fl.addRow("To hour (0-23):", self.spin("scheduler_end_hour", 0, 23))
        days_row = QHBoxLayout()
        self.day_checks = []
        active = self.config.get("scheduler_days", DEFAULTS["scheduler_days"])
        for i, d in enumerate(WEEKDAYS):
            c = QCheckBox(d)
            c.setChecked(i in active)
            self.day_checks.append(c)
            days_row.addWidget(c)
        fl.addRow("On days:", days_row)
        fl.addRow("Limited download rate:", self.spin("scheduler_dl_kbps", 1, 1000000, " kB/s"))
        fl.addRow("Limited upload rate:", self.spin("scheduler_ul_kbps", 1, 1000000, " kB/s"))
        note = QLabel("Tip: these limits are also used by the 🐢 Limit button in the toolbar and tray menu. "
                      "A window like 22 → 6 runs overnight.")
        note.setWordWrap(True)
        fl.addRow(note)
        lay.addWidget(grp)
        lay.addStretch()

    def page_label(self):
        lay = self.new_page()
        lay.addWidget(QLabel("Labels (one per line — used in the sidebar and for completed-folder sorting):"))
        lay.addWidget(self.text_list("labels"))

    def page_rss_feeds(self):
        lay = self.new_page()
        lay.addWidget(QLabel("RSS feed URLs (one per line):"))
        lay.addWidget(self.text_list("rss_feeds"))
        fl = QFormLayout()
        fl.addRow("Refresh feeds every:", self.spin("rss_refresh_min", 5, 1440, " min"))
        fl.addRow(self.chk("rss_auto_download", "Automatically download new items matching a filter below"))
        lay.addLayout(fl)
        lay.addWidget(QLabel("Auto-download filters (one per line; words or regex, e.g.  ubuntu.*desktop ):"))
        lay.addWidget(self.text_list("rss_filters"))

    # -- collect / apply ---------------------------------------------------
    def switch_page(self, index):
        self.pages.setCurrentIndex(index)
        item = self.nav_list.item(index)
        if item:
            self.header_banner.setText(f"  {item.text()}")

    def collect_values(self):
        for key, w in self._binds:
            if isinstance(w, QCheckBox):
                self.config[key] = w.isChecked()
            elif isinstance(w, QDoubleSpinBox):
                self.config[key] = w.value()
            elif isinstance(w, QSpinBox):
                self.config[key] = w.value()
            elif isinstance(w, QComboBox):
                self.config[key] = w.currentText()
            elif isinstance(w, QPlainTextEdit):
                self.config[key] = [x.strip() for x in w.toPlainText().splitlines() if x.strip()]
            elif isinstance(w, QLineEdit):
                self.config[key] = w.text() if key == "proxy_pass" else w.text().strip()
        self.config["scheduler_days"] = [i for i, c in enumerate(self.day_checks) if c.isChecked()]

    def apply_only(self):
        self.collect_values()
        self.main.apply_preferences(self.config)
        self.config = json.loads(json.dumps(self.main.config))

    def save_and_accept(self):
        self.apply_only()
        self.accept()


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
STATES = ['Queued', 'Checking', 'Fetching metadata', 'Downloading', 'Finished', 'Seeding',
          'Allocating', 'Checking resume']
NAV_KEYS = ["All", "Downloading", "Seeding", "Completed", "Active", "Inactive", "Paused", "Errors"]


class STorrentClient(QMainWindow):
    def __init__(self, ipc_server, start_args):
        super().__init__()
        self.base_title = f"{APP_NAME} {APP_VERSION} — Free Edition ({ORG})"
        self.setWindowTitle(self.base_title)
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        self.setAcceptDrops(True)

        os.makedirs(STATE_DIR, exist_ok=True)
        self.config = self.load_config()
        if self.config.get("randomize_port_start"):
            self.config["listen_port"] = random.randint(10000, 64000)

        self.handles = []
        self.handle_by_ih = {}
        self.torrent_labels = dict(self.config.get("torrent_labels", {}))
        self.finished_set = set(self.config.get("finished_hashes", []))
        self.goal_done = set(self.config.get("goal_done", []))
        self.stored_torrents = dict(self.config.get("stored_torrents", {}))
        self.rss_seen = list(self.config.get("rss_seen", []))
        self.current_filter = ("status", "All")
        self.search_query = ""
        self.session_dl = 0
        self.session_ul = 0
        self._last_totals = {}
        self.cap_paused = []
        self.alt_speed_manual = False
        self._limited = None
        self._keep_awake = False
        self._blocklist_loaded = None
        self._shutting_down = False
        self._workers = []
        self._tick = 0
        self.started_at = time.time()

        self.ses = self.create_session()
        self.init_menu()
        self.init_ui()
        self.init_tray()
        self.apply_session_settings()
        self.apply_ui_settings()
        self.apply_theme()
        self.restore_saved_torrents()
        self.check_cap_period(startup=True)

        self.ipc = ipc_server
        self.ipc.newConnection.connect(self.on_ipc_connection)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(1000)

        try:
            QApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        except Exception:
            pass
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        QTimer.singleShot(400, lambda: self.handle_args(start_args))
        if self.config.get("rss_feeds"):
            QTimer.singleShot(5000, lambda: self.fetch_rss_feeds(silent=True))
        self.log(f"{APP_NAME} {APP_VERSION} started. Data folder: {DATA_DIR}")

    # ------------------------------------------------------------------ config
    def load_config(self):
        cfg = json.loads(json.dumps(DEFAULTS))
        for path in (CONFIG_FILE, LEGACY_CONFIG):
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cfg.update(json.load(f))
                    break
                except Exception:
                    pass
        if "dark_mode" in cfg and not os.path.exists(CONFIG_FILE):
            cfg["theme"] = "Dark" if cfg.pop("dark_mode") else "Light"
        cfg.pop("dark_mode", None)
        return cfg

    def save_config(self):
        self.config["torrent_labels"] = self.torrent_labels
        self.config["finished_hashes"] = sorted(self.finished_set)
        self.config["goal_done"] = sorted(self.goal_done)
        self.config["stored_torrents"] = self.stored_torrents
        self.config["rss_seen"] = self.rss_seen[-3000:]
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except Exception as e:
            self.log(f"Could not save settings: {e}")

    # ------------------------------------------------------------------ session
    def listen_string(self):
        port = self.config.get("listen_port", 31405)
        iface = self.config.get("bind_interface", "").strip()
        if iface:
            return f"{iface}:{port}"
        return f"0.0.0.0:{port},[::]:{port}"

    def create_session(self):
        base = {"listen_interfaces": self.listen_string(), "alert_mask": alert_mask(),
                "user_agent": f"{APP_NAME}/{APP_VERSION}"}
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "rb") as f:
                    ses = lt.session(lt.read_session_params(f.read()))
                ses.apply_settings(base)
                return ses
            except Exception:
                pass
        return lt.session(base)

    def apply_session_settings(self):
        c = self.config
        leaks = c.get("disable_leaks", False)
        s = {
            "listen_interfaces": self.listen_string(),
            "outgoing_interfaces": c.get("bind_interface", "").strip(),
            "enable_dht": c.get("enable_dht", True),
            "enable_lsd": c.get("enable_lsd", True) and not leaks,
            "enable_upnp": c.get("enable_upnp", True) and not leaks,
            "enable_natpmp": c.get("enable_natpmp", True) and not leaks,
            "enable_incoming_utp": c.get("enable_utp", True),
            "enable_outgoing_utp": c.get("enable_utp", True),
            "anonymous_mode": c.get("anonymous_mode", False) or leaks,
            "connections_limit": c.get("max_connections", 500),
            "active_limit": c.get("active_limit", 8),
            "active_downloads": c.get("active_downloads", 5),
            "active_seeds": c.get("active_seeds", 5),
            "dont_count_slow_torrents": c.get("dont_count_slow", True),
            "alert_mask": alert_mask(),
        }
        enc = {"Forced": lt.enc_policy.forced, "Disabled": lt.enc_policy.disabled}.get(
            c.get("encryption"), lt.enc_policy.enabled)
        s["out_enc_policy"] = int(enc)
        s["in_enc_policy"] = int(enc)

        ptype = c.get("proxy_type", "(none)")
        auth = c.get("proxy_auth", False) and bool(c.get("proxy_user"))
        P = lt.proxy_type_t
        s["proxy_type"] = int({"SOCKS4": P.socks4,
                               "SOCKS5": P.socks5_pw if auth else P.socks5,
                               "HTTP": P.http_pw if auth else P.http,
                               "HTTPS": P.http_pw if auth else P.http}.get(ptype, P.none))
        s["proxy_hostname"] = c.get("proxy_host", "")
        s["proxy_port"] = int(c.get("proxy_port", 8080))
        s["proxy_username"] = c.get("proxy_user", "")
        s["proxy_password"] = c.get("proxy_pass", "")
        s["proxy_hostnames"] = c.get("proxy_hostnames", True)
        s["proxy_peer_connections"] = c.get("proxy_p2p", True)
        try:
            self.ses.apply_settings(s)
        except Exception as e:
            self.log(f"Some network settings were rejected: {e}")
        self._limited = None
        self.apply_rate_limits()
        self.load_blocklist()
        for h in self.handles:
            self.apply_torrent_settings(h)

    def schedule_active(self):
        c = self.config
        if not c.get("scheduler_enabled"):
            return False
        now = datetime.datetime.now()
        if now.weekday() not in c.get("scheduler_days", []):
            return False
        a, b, hr = c.get("scheduler_start_hour", 9), c.get("scheduler_end_hour", 18), now.hour
        return (a <= hr < b) if a <= b else (hr >= a or hr < b)

    def apply_rate_limits(self):
        limited = self.alt_speed_manual or self.schedule_active()
        if limited == self._limited:
            return
        self._limited = limited
        c = self.config
        if limited:
            dl, ul = c.get("scheduler_dl_kbps", 500), c.get("scheduler_ul_kbps", 100)
        else:
            dl, ul = c.get("max_dl_kbps", 0), c.get("max_ul_kbps", 0)
        self.ses.apply_settings({"download_rate_limit": int(dl) * 1024, "upload_rate_limit": int(ul) * 1024})
        if hasattr(self, "btn_turtle"):
            self.btn_turtle.setChecked(self.alt_speed_manual)
            self.act_tray_turtle.setChecked(self.alt_speed_manual)

    def apply_torrent_settings(self, h):
        try:
            h.set_max_connections(int(self.config.get("max_peers_per_torrent", 100)))
            h.set_max_uploads(int(self.config.get("upload_slots", 8)))
            flag = getattr(lt.torrent_flags, "disable_pex", None)
            if flag is not None:
                if self.config.get("enable_pex", True):
                    h.unset_flags(flag)
                else:
                    h.set_flags(flag)
        except Exception:
            pass

    def load_blocklist(self):
        path = self.config.get("blocklist_path", "")
        stamp = (path, os.path.getmtime(path)) if path and os.path.exists(path) else (path, 0)
        if stamp == self._blocklist_loaded:
            return
        self._blocklist_loaded = stamp
        ipf = lt.ip_filter()
        count = 0
        if path and os.path.exists(path):
            rng = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})\s*-\s*(\d{1,3}(?:\.\d{1,3}){3})")
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("#"):
                            continue
                        m = rng.search(line)
                        if m:
                            a = ".".join(str(int(x)) for x in m.group(1).split("."))
                            b = ".".join(str(int(x)) for x in m.group(2).split("."))
                            try:
                                ipf.add_rule(a, b, 1)
                                count += 1
                            except Exception:
                                pass
            except Exception as e:
                self.log(f"Blocklist error: {e}")
        self.ses.set_ip_filter(ipf)
        if path:
            self.log(f"IP blocklist loaded: {count} ranges blocked.")

    def apply_ui_settings(self):
        self.table.setAlternatingRowColors(self.config.get("alt_row_colors", True))
        self.update_tray_visibility()

    def apply_preferences(self, new):
        old = self.config
        new = dict(new)
        if new.pop("cap_reset_now", False):
            new["cap_used_bytes"] = 0
            self.resume_cap_paused()
        if IS_WIN:
            if new.get("start_with_windows") != is_autostart() or \
                    new.get("start_minimized") != old.get("start_minimized"):
                set_autostart(new.get("start_with_windows"), new.get("start_minimized", True))
            if new.get("add_firewall_rule") != old.get("add_firewall_rule"):
                firewall_rule(new.get("add_firewall_rule"))
        self.config = new
        self.save_config()
        self.apply_session_settings()
        self.apply_ui_settings()
        self.rebuild_sidebar_labels()
        self.apply_theme()
        self.check_cap_period()
        if not self.config.get("transfer_cap_enabled"):
            self.resume_cap_paused()

    # ------------------------------------------------------------------ UI
    def init_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        self._menu_action(fm, "Add Torrent...", "Ctrl+O", lambda: self.add_torrent_file())
        self._menu_action(fm, "Add Torrent from URL / Magnet...", "Ctrl+U", lambda: self.add_magnet_link())
        self._menu_action(fm, "Create New Torrent...", "Ctrl+N", self.open_create_torrent)
        fm.addSeparator()
        self._menu_action(fm, "Exit", "Ctrl+Q", self.quit_application)

        om = mb.addMenu("&Options")
        self._menu_action(om, "Preferences...", "Ctrl+P", self.open_preferences)
        om.addSeparator()
        self._menu_action(om, "Pause All", None, self.pause_all)
        self._menu_action(om, "Resume All", None, self.resume_all)
        om.addSeparator()
        self._menu_action(om, "Toggle Dark / Light Theme", "Ctrl+T", self.toggle_theme)

        hm = mb.addMenu("&Help")
        self._menu_action(hm, f"{ORG} Official Website", None,
                          lambda: QDesktopServices.openUrl(QUrl("https://smartupworld.com")))
        self._menu_action(hm, "Open Data Folder", None,
                          lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR)))
        self._menu_action(hm, f"About {APP_NAME}", None, self.show_about)

    def _menu_action(self, menu, text, shortcut, slot):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        tb = QHBoxLayout()
        for text, slot, tip in (
                ("+ Add Torrent", lambda: self.add_torrent_file(), "Add a .torrent file"),
                ("+ Magnet / URL", lambda: self.add_magnet_link(), "Add a magnet link or .torrent URL"),
                ("✚ Create", self.open_create_torrent, "Create a new torrent"),
                ("Remove", lambda: self.remove_selected(False), "Remove from list"),
                ("Remove + Data", lambda: self.remove_selected(True), "Remove and delete files"),
                ("▶ Start", lambda: self.set_state_selected(False), "Start selected"),
                ("⏸ Pause", lambda: self.set_state_selected(True), "Pause selected"),
                ("▲", lambda: self.move_queue("up"), "Move up queue"),
                ("▼", lambda: self.move_queue("down"), "Move down queue")):
            b = QPushButton(text)
            b.setToolTip(tip)
            if text in ("▲", "▼"):
                b.setFixedWidth(30)
            if text == "Remove + Data":
                b.setStyleSheet("color: #d9534f; font-weight: bold;")
            b.clicked.connect(slot)
            tb.addWidget(b)
        self.btn_turtle = QPushButton("🐢 Limit")
        self.btn_turtle.setCheckable(True)
        self.btn_turtle.setToolTip("Temporarily use the Scheduler's limited speeds")
        self.btn_turtle.clicked.connect(self.toggle_turtle)
        tb.addWidget(self.btn_turtle)
        self.chk_sequential = QCheckBox("Sequential (Stream)")
        self.chk_sequential.stateChanged.connect(self.toggle_sequential)
        tb.addWidget(self.chk_sequential)
        tb.addStretch()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Filter torrents...")
        self.txt_search.setFixedWidth(180)
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self.on_search_changed)
        tb.addWidget(self.txt_search)
        bp = QPushButton("⚙ Preferences")
        bp.clicked.connect(self.open_preferences)
        tb.addWidget(bp)
        main_layout.addLayout(tb)

        h_split = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setMinimumWidth(170)
        self.sidebar.itemClicked.connect(self.on_sidebar_clicked)
        self.torrents_root = QTreeWidgetItem(self.sidebar, ["Torrents (0)"])
        self.torrents_root.setData(0, Qt.ItemDataRole.UserRole, ("status", "All"))
        self.torrents_root.setExpanded(True)
        self.nav_items = {}
        for key in NAV_KEYS:
            it = QTreeWidgetItem(self.torrents_root, [f"{key} (0)"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("status", key))
            self.nav_items[key] = it
        self.labels_root = QTreeWidgetItem(self.sidebar, ["Labels"])
        self.labels_root.setExpanded(True)
        self.label_items = {}
        self.rebuild_sidebar_labels()
        self.rss_root = QTreeWidgetItem(self.sidebar, ["Feeds (RSS)"])
        self.rss_root.setData(0, Qt.ItemDataRole.UserRole, ("feeds", ""))
        h_split.addWidget(self.sidebar)

        v_split = QSplitter(Qt.Orientation.Vertical)
        cols = ["#", "Name", "Size", "Done", "Status", "Seeds", "Peers", "Down Speed",
                "Up Speed", "ETA", "Ratio", "Label"]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 38)
        self.table.setColumnWidth(3, 120)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setItemDelegateForColumn(3, ProgressDelegate(self.table))
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.doubleClicked.connect(self.on_torrent_double_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_torrent_context_menu)
        del_act = QAction(self.table)
        del_act.setShortcut(QKeySequence.StandardKey.Delete)
        del_act.triggered.connect(lambda: self.remove_selected(False))
        self.table.addAction(del_act)
        v_split.addWidget(self.table)

        self.tabs = QTabWidget()
        # Info
        self.general_text = QTextEdit()
        self.general_text.setReadOnly(True)
        self.tabs.addTab(self.general_text, "Info")
        # Files
        self.files_table = QTableWidget(0, 5)
        self.files_table.setHorizontalHeaderLabels(["Path", "Size", "Done", "Priority", "Streamable"])
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_table.setColumnWidth(2, 120)
        self.files_table.setItemDelegateForColumn(2, ProgressDelegate(self.files_table))
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files_table.customContextMenuRequested.connect(self.show_file_context_menu)
        self.files_table.doubleClicked.connect(self.play_selected_file)
        self.tabs.addTab(self.files_table, "Files")
        # Playback
        play = QWidget()
        pl = QVBoxLayout(play)
        pl.addWidget(QLabel("Double-click a media file in the 'Files' tab, or use the button below. "
                            "Sequential mode downloads the file from start to end so it can play early."))
        b = QPushButton("▶ Enable Sequential Mode && Play Largest Media File")
        b.setFixedWidth(360)
        b.clicked.connect(self.play_largest_file)
        pl.addWidget(b)
        pl.addStretch()
        self.tabs.addTab(play, "Playback")
        # Peers
        self.peers_table = QTableWidget(0, 6)
        self.peers_table.setHorizontalHeaderLabels(["IP", "Client", "Done %", "Down Speed", "Up Speed", "Flags"])
        self.peers_table.verticalHeader().setVisible(False)
        self.peers_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.peers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.peers_table, "Peers")
        # Trackers
        trk = QWidget()
        tl = QVBoxLayout(trk)
        self.trackers_table = QTableWidget(0, 3)
        self.trackers_table.setHorizontalHeaderLabels(["Tracker URL", "Tier", "Status"])
        self.trackers_table.verticalHeader().setVisible(False)
        self.trackers_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trackers_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trackers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tl.addWidget(self.trackers_table)
        tr = QHBoxLayout()
        for text, slot in (("Add tracker...", self.add_tracker), ("Remove tracker", self.remove_tracker),
                           ("Force re-announce", self.reannounce_selected)):
            bt = QPushButton(text)
            bt.clicked.connect(slot)
            tr.addWidget(bt)
        tr.addStretch()
        tl.addLayout(tr)
        self.tabs.addTab(trk, "Trackers")
        # Speed
        self.speed_graph = SpeedGraph()
        self.tabs.addTab(self.speed_graph, "Speed")
        # Feeds
        rss = QWidget()
        rl = QVBoxLayout(rss)
        rt = QHBoxLayout()
        br = QPushButton("Refresh Feeds")
        br.clicked.connect(lambda: self.fetch_rss_feeds())
        rt.addWidget(br)
        rt.addWidget(QLabel("Double-click an item to download it. Manage feeds and auto-download filters in Preferences › RSS Feeds."))
        rt.addStretch()
        rl.addLayout(rt)
        self.rss_table = QTableWidget(0, 3)
        self.rss_table.setHorizontalHeaderLabels(["Title", "Feed", "Torrent / Magnet Link"])
        self.rss_table.verticalHeader().setVisible(False)
        self.rss_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rss_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rss_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rss_table.doubleClicked.connect(self.download_rss_item)
        rl.addWidget(self.rss_table)
        self.tabs.addTab(rss, "Feeds")
        self.rss_tab = rss
        # Log
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs.addTab(self.log_view, "Log")

        v_split.addWidget(self.tabs)
        v_split.setSizes([480, 270])
        h_split.addWidget(v_split)
        h_split.setSizes([200, 1080])
        main_layout.addWidget(h_split)

        self.status_label = QLabel("Starting...")
        self.statusBar().addWidget(self.status_label, 1)

    def log(self, msg):
        if hasattr(self, "log_view"):
            self.log_view.appendPlainText(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

    def rebuild_sidebar_labels(self):
        self.labels_root.takeChildren()
        self.label_items = {}
        for lbl in self.config.get("labels", []):
            it = QTreeWidgetItem(self.labels_root, [lbl])
            it.setData(0, Qt.ItemDataRole.UserRole, ("label", lbl))
            self.label_items[lbl] = it

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(app_icon(), self)
        self.tray_icon.setToolTip(APP_NAME)
        self.tray_icon.activated.connect(self.on_tray_activated)
        m = QMenu()
        self._menu_action(m, f"Show {APP_NAME}", None, self.restore_window)
        m.addSeparator()
        self._menu_action(m, "Add Torrent...", None, lambda: self.add_torrent_file())
        self._menu_action(m, "Add Magnet / URL...", None, lambda: self.add_magnet_link())
        m.addSeparator()
        self._menu_action(m, "Pause All", None, self.pause_all)
        self._menu_action(m, "Resume All", None, self.resume_all)
        self.act_tray_turtle = self._menu_action(m, "🐢 Limit speeds", None, self.toggle_turtle)
        self.act_tray_turtle.setCheckable(True)
        m.addSeparator()
        self._menu_action(m, "Exit", None, self.quit_application)
        self.tray_menu = m
        self.tray_icon.setContextMenu(m)

    def update_tray_visibility(self):
        want = self.config.get("always_show_tray", True) or not self.isVisible()
        self.tray_icon.setVisible(bool(want))

    def on_tray_activated(self, reason):
        R = QSystemTrayIcon.ActivationReason
        if reason == R.DoubleClick or (reason == R.Trigger and self.config.get("single_click_tray")):
            if self.isVisible() and not self.isMinimized() and reason == R.Trigger:
                self.hide_to_tray()
            else:
                self.restore_window()

    def restore_window(self):
        self.show()
        if self.isMinimized():
            self.showNormal()
        if self.config.get("always_activate_tray", True):
            self.raise_()
            self.activateWindow()
        self.update_tray_visibility()

    def hide_to_tray(self):
        self.tray_icon.show()
        self.hide()

    def notify(self, title, msg):
        if self.config.get("balloon_notifications", True) and QSystemTrayIcon.supportsMessages():
            if not self.tray_icon.isVisible():
                self.tray_icon.show()
            self.tray_icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 4000)

    # ------------------------------------------------------------------ theme
    def apply_theme(self):
        mode = self.config.get("theme", "System")
        dark = system_is_dark() if mode == "System" else (mode == "Dark")
        QApplication.setPalette(build_palette(dark))
        self.is_dark = dark
        self.speed_graph.update()

    def toggle_theme(self):
        self.config["theme"] = "Light" if self.is_dark else "Dark"
        self.save_config()
        self.apply_theme()

    # ------------------------------------------------------------------ IPC / args
    def on_ipc_connection(self):
        while self.ipc.hasPendingConnections():
            sock = self.ipc.nextPendingConnection()
            sock.setProperty("buf", b"")
            sock.readyRead.connect(lambda s=sock: s.setProperty("buf", bytes(s.property("buf")) + bytes(s.readAll())))
            sock.disconnected.connect(lambda s=sock: self._ipc_done(s))

    def _ipc_done(self, sock):
        try:
            args = json.loads(bytes(sock.property("buf") or b"[]").decode("utf-8") or "[]")
        except Exception:
            args = []
        sock.deleteLater()
        self.restore_window()
        self.handle_args(args)

    def handle_args(self, args):
        for a in args or []:
            if not a or a.startswith("--"):
                continue
            if a.lower().startswith("magnet:"):
                self.add_magnet_link(a)
            elif a.lower().startswith(("http://", "https://")):
                self.add_from_url(a)
            elif os.path.isfile(a):
                self.add_torrent_file(a)

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or (md.hasText() and md.text().strip().lower().startswith(("magnet:", "http"))):
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        items = []
        if md.hasUrls():
            for u in md.urls():
                items.append(u.toLocalFile() if u.isLocalFile() else u.toString())
        elif md.hasText():
            items = md.text().split()
        self.handle_args(items)

    # ------------------------------------------------------------------ adding torrents
    def add_torrent_file(self, file_path=None, interactive=True, save_dir=None, label=""):
        if not file_path:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select Torrent(s)", "", "Torrent Files (*.torrent)")
            for p in paths:
                self.add_torrent_file(p, interactive=len(paths) == 1)
            return None
        if not os.path.exists(file_path):
            return None
        try:
            info = lt.torrent_info(file_path)
        except Exception as e:
            self.log(f"Invalid torrent file {file_path}: {e}")
            if interactive:
                QMessageBox.warning(self, "Invalid torrent", f"Could not read this torrent file:\n{e}")
            return None
        params = lt.add_torrent_params()
        params.ti = info
        return self._finalize_add(params, info, info.name(), interactive, save_dir, label, src_file=file_path)

    def add_magnet_link(self, magnet=None, interactive=True, label=""):
        if not magnet:
            magnet, ok = QInputDialog.getText(self, "Add Magnet / URL", "Paste a magnet link or .torrent URL:")
            if not ok:
                return None
            magnet = magnet.strip()
        if magnet.lower().startswith(("http://", "https://")):
            return self.add_from_url(magnet, interactive, label)
        if not magnet.lower().startswith("magnet:?"):
            if interactive:
                QMessageBox.warning(self, "Invalid Link", "Please enter a valid magnet:? link or http(s) URL.")
            return None
        try:
            params = lt.parse_magnet_uri(magnet)
        except Exception as e:
            if interactive:
                QMessageBox.warning(self, "Invalid Link", str(e))
            return None
        name = getattr(params, "name", "") or "Magnet link"
        return self._finalize_add(params, None, name, interactive, None, label)

    def add_from_url(self, url, interactive=True, label=""):
        self.log(f"Downloading .torrent from {url}")
        w = UrlTorrentWorker(url)

        def done(path, err):
            self._workers.remove(w)
            if err:
                self.log(f"URL download failed: {err}")
                if interactive:
                    QMessageBox.warning(self, "Download failed", f"Could not download the torrent:\n{err}")
                return
            try:
                self.add_torrent_file(path, interactive=interactive, label=label)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        w.done.connect(done)
        self._workers.append(w)
        w.start()

    def _finalize_add(self, params, ti, name, interactive, save_dir, label, src_file=None):
        c = self.config
        default_dir = save_dir or c.get("save_path") or DEFAULT_DL
        start = not c.get("dont_start_auto", False)
        seq = False
        need_dialog = interactive and save_dir is None and (
            c.get("ask_save_dir") or not c.get("use_default_save_path", True) or not os.path.isdir(default_dir))
        if need_dialog:
            dlg = AddTorrentDialog(self, ti, name, default_dir, c.get("labels", []), start)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            v = dlg.values()
            default_dir, label, start, seq = v["save_path"] or default_dir, v["label"], v["start"], v["sequential"]
            if v["priorities"] is not None:
                params.file_priorities = v["priorities"]
        try:
            os.makedirs(default_dir, exist_ok=True)
        except OSError as e:
            if interactive:
                QMessageBox.warning(self, "Folder error", f"Cannot use folder {default_dir}:\n{e}")
            return None
        params.save_path = default_dir
        if c.get("preallocate"):
            params.storage_mode = lt.storage_mode_t.storage_mode_allocate
        params.max_connections = int(c.get("max_peers_per_torrent", 100))
        params.max_uploads = int(c.get("upload_slots", 8))
        if not start:
            params.flags |= lt.torrent_flags.paused
            params.flags &= ~lt.torrent_flags.auto_managed
        if seq:
            params.flags |= lt.torrent_flags.sequential_download

        before = set(self.handle_by_ih)
        try:
            h = self.ses.add_torrent(params)
        except Exception as e:
            self.log(f"Could not add {name}: {e}")
            if interactive:
                QMessageBox.warning(self, "Add torrent", f"Could not add torrent:\n{e}")
            return None
        ih = ih_of(h)
        if ih in before:
            if interactive:
                QMessageBox.information(self, "Already added", f"'{name}' is already in your list.")
            return h
        self._register_handle(h)
        if label:
            if label not in c.setdefault("labels", []):
                c["labels"].append(label)
                self.rebuild_sidebar_labels()
            self.torrent_labels[ih] = label

        if src_file and c.get("store_torrents_enabled"):
            store = c.get("store_torrents_path", "")
            if store:
                try:
                    os.makedirs(store, exist_ok=True)
                    dest = os.path.join(store, os.path.basename(src_file))
                    if os.path.abspath(dest) != os.path.abspath(src_file):
                        shutil.copy2(src_file, dest)
                    self.stored_torrents[ih] = dest
                except Exception as e:
                    self.log(f"Could not store .torrent copy: {e}")
        self.apply_incomplete_ext(h)
        request_resume(h)
        self.save_config()
        self.log(f"Added: {name}")
        if interactive and c.get("activate_on_add", True):
            self.restore_window()
        self.refresh()
        return h

    def _register_handle(self, h):
        ih = ih_of(h)
        if ih in self.handle_by_ih:
            return
        self.handles.append(h)
        self.handle_by_ih[ih] = h
        self.apply_torrent_settings(h)

    def restore_saved_torrents(self):
        dirs = [STATE_DIR]
        if os.path.isdir(LEGACY_STATE) and not os.listdir(STATE_DIR):
            dirs.append(LEGACY_STATE)
        n = 0
        for d in dirs:
            for fname in os.listdir(d):
                if not fname.endswith(".fastresume"):
                    continue
                try:
                    with open(os.path.join(d, fname), "rb") as f:
                        params = lt.read_resume_data(f.read())
                    self._register_handle(self.ses.add_torrent(params))
                    n += 1
                except Exception as e:
                    self.log(f"Could not restore {fname}: {e}")
        if n:
            self.log(f"Restored {n} torrent(s).")

    # ------------------------------------------------------------------ incomplete extension
    def apply_incomplete_ext(self, h):
        if not self.config.get("append_incomplete_ext") or not h.is_valid() or not h.has_metadata():
            return
        s = h.status()
        if s.is_seeding or s.is_finished:
            return
        fs = h.torrent_file().files()
        for i in range(fs.num_files()):
            p = fs.file_path(i)
            if not p.endswith(INCOMPLETE_EXT):
                h.rename_file(i, p + INCOMPLETE_EXT)

    def strip_incomplete_ext(self, h, only_index=None):
        if not h.is_valid() or not h.has_metadata():
            return
        fs = h.torrent_file().files()
        for i in range(fs.num_files()):
            if only_index is not None and i != only_index:
                continue
            p = fs.file_path(i)
            if p.endswith(INCOMPLETE_EXT):
                h.rename_file(i, p[:-len(INCOMPLETE_EXT)])

    # ------------------------------------------------------------------ selection helpers
    def selected_handles(self):
        out = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 1)
            if it:
                h = self.handle_by_ih.get(it.data(Qt.ItemDataRole.UserRole))
                if h is not None and h.is_valid():
                    out.append(h)
        return out

    def get_selected_handle(self):
        hs = self.selected_handles()
        return hs[0] if hs else None

    # ------------------------------------------------------------------ actions
    def set_state_selected(self, pause=True, force=False):
        for h in self.selected_handles():
            ih = ih_of(h)
            if pause:
                h.unset_flags(lt.torrent_flags.auto_managed)
                h.pause()
            else:
                if ih in self.cap_paused:
                    self.cap_paused.remove(ih)
                if force:
                    h.unset_flags(lt.torrent_flags.auto_managed)
                else:
                    h.set_flags(lt.torrent_flags.auto_managed)
                h.resume()
        self.refresh()

    def pause_all(self):
        for h in self.handles:
            h.unset_flags(lt.torrent_flags.auto_managed)
            h.pause()
        self.refresh()

    def resume_all(self):
        self.cap_paused = []
        for h in self.handles:
            h.set_flags(lt.torrent_flags.auto_managed)
            h.resume()
        self.refresh()

    def toggle_turtle(self):
        self.alt_speed_manual = not self.alt_speed_manual
        self.apply_rate_limits()
        self.log("Speed limiter " + ("ON" if self.alt_speed_manual else "OFF"))

    def move_queue(self, where):
        for h in self.selected_handles():
            try:
                {"up": h.queue_position_up, "down": h.queue_position_down,
                 "top": h.queue_position_top, "bottom": h.queue_position_bottom}[where]()
            except Exception:
                pass
        self.refresh()

    def remove_selected(self, delete_data=False):
        hs = self.selected_handles()
        if not hs:
            return
        if self.config.get("confirm_delete_torrent", True) or delete_data:
            what = f"{len(hs)} torrents" if len(hs) > 1 else f"'{hs[0].status().name}'"
            msg = (f"Delete {what} AND all downloaded files from disk?" if delete_data
                   else f"Remove {what} from the list? (files stay on disk)")
            if QMessageBox.question(self, "Confirm Removal", msg) != QMessageBox.StandardButton.Yes:
                return
        for h in hs:
            ih = ih_of(h)
            name = h.status().name
            if h in self.handles:
                self.handles.remove(h)
            self.handle_by_ih.pop(ih, None)
            self._last_totals.pop(ih, None)
            self.torrent_labels.pop(ih, None)
            self.finished_set.discard(ih)
            self.goal_done.discard(ih)
            self.stored_torrents.pop(ih, None)
            try:
                os.remove(os.path.join(STATE_DIR, f"{ih}.fastresume"))
            except OSError:
                pass
            self.ses.remove_torrent(h, lt.session.delete_files if delete_data else 0)
            self.log(f"Removed{' with data' if delete_data else ''}: {name}")
        self.save_config()
        self.table.clearSelection()
        self.refresh()

    def toggle_sequential(self, state):
        on = state == Qt.CheckState.Checked.value
        for h in self.selected_handles():
            if on:
                h.set_flags(lt.torrent_flags.sequential_download)
            else:
                h.unset_flags(lt.torrent_flags.sequential_download)

    def move_data_selected(self):
        hs = self.selected_handles()
        if not hs:
            return
        d = QFileDialog.getExistingDirectory(self, "Move data to", hs[0].status().save_path)
        if d:
            for h in hs:
                h.move_storage(d)
                self.log(f"Moving data of {h.status().name} to {d}")

    def set_limits_selected(self):
        hs = self.selected_handles()
        if not hs:
            return
        cur_d = max(hs[0].download_limit(), 0) // 1024
        cur_u = max(hs[0].upload_limit(), 0) // 1024
        d, ok = QInputDialog.getInt(self, "Download limit", "Download limit for selected (kB/s, 0 = unlimited):", cur_d, 0, 10000000)
        if not ok:
            return
        u, ok = QInputDialog.getInt(self, "Upload limit", "Upload limit for selected (kB/s, 0 = unlimited):", cur_u, 0, 10000000)
        if not ok:
            return
        for h in hs:
            h.set_download_limit(d * 1024 if d else -1)
            h.set_upload_limit(u * 1024 if u else -1)
            request_resume(h)

    def reannounce_selected(self):
        for h in self.selected_handles():
            h.force_reannounce()
            try:
                h.force_dht_announce()
            except Exception:
                pass

    def on_torrent_double_clicked(self):
        h = self.get_selected_handle()
        if not h:
            return
        s = h.status()
        key = "dbl_click_seeding" if s.progress >= 1.0 else "dbl_click_downloading"
        action = self.config.get(key, "Show Properties")
        if action == "Open Folder":
            self.open_folder(h)
        elif action == "Start/Stop":
            self.set_state_selected(pause=not bool(s.flags & lt.torrent_flags.paused))
        elif action == "Play Media":
            self.play_largest_file()
        else:
            self.tabs.setCurrentWidget(self.general_text)

    def open_folder(self, h):
        s = h.status()
        path = os.path.join(s.save_path, s.name) if s.name else s.save_path
        if not os.path.isdir(path):
            path = s.save_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def show_torrent_context_menu(self, pos):
        hs = self.selected_handles()
        if not hs:
            return
        h = hs[0]
        m = QMenu(self)
        self._menu_action(m, "Open Containing Folder", None, lambda: self.open_folder(h))
        m.addSeparator()
        self._menu_action(m, "Start", None, lambda: self.set_state_selected(False))
        self._menu_action(m, "Force Start", None, lambda: self.set_state_selected(False, force=True))
        self._menu_action(m, "Pause", None, lambda: self.set_state_selected(True))
        m.addSeparator()
        q = m.addMenu("Queue")
        for text, where in (("Move to Top", "top"), ("Move Up", "up"), ("Move Down", "down"), ("Move to Bottom", "bottom")):
            self._menu_action(q, text, None, lambda _=False, w=where: self.move_queue(w))
        lm = m.addMenu("Label")
        self._menu_action(lm, "(None)", None, lambda: self.assign_label(hs, ""))
        lm.addSeparator()
        for lbl in self.config.get("labels", []):
            self._menu_action(lm, lbl, None, lambda _=False, l=lbl: self.assign_label(hs, l))
        lm.addSeparator()
        self._menu_action(lm, "New Label...", None, lambda: self.create_and_assign_label(hs))
        self._menu_action(m, "Bandwidth Limits...", None, self.set_limits_selected)
        self._menu_action(m, "Move Data To...", None, self.move_data_selected)
        m.addSeparator()
        self._menu_action(m, "Force Re-check", None, lambda: [x.force_recheck() for x in hs])
        self._menu_action(m, "Force Re-announce", None, self.reannounce_selected)
        self._menu_action(m, "Copy Magnet URI", None,
                          lambda: QApplication.clipboard().setText("\n".join(lt.make_magnet_uri(x) for x in hs)))
        m.addSeparator()
        self._menu_action(m, "Remove", None, lambda: self.remove_selected(False))
        self._menu_action(m, "Remove And Delete Data", None, lambda: self.remove_selected(True))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def assign_label(self, hs, label_name):
        for h in hs:
            ih = ih_of(h)
            if label_name:
                self.torrent_labels[ih] = label_name
            else:
                self.torrent_labels.pop(ih, None)
        self.save_config()
        self.refresh()

    def create_and_assign_label(self, hs):
        lbl, ok = QInputDialog.getText(self, "New Label", "Enter label name:")
        if ok and lbl.strip():
            lbl = lbl.strip()
            if lbl not in self.config["labels"]:
                self.config["labels"].append(lbl)
                self.rebuild_sidebar_labels()
            self.assign_label(hs, lbl)

    # ------------------------------------------------------------------ files / playback
    def show_file_context_menu(self, pos):
        m = QMenu(self)
        self._menu_action(m, "Play / Stream File", None, self.play_selected_file)
        self._menu_action(m, "Open Containing Folder", None, self.open_selected_file_folder)
        m.addSeparator()
        self._menu_action(m, "Don't Download (Skip)", None, lambda: self.set_file_priority(0))
        if self.config.get("fine_priorities"):
            self._menu_action(m, "Low Priority", None, lambda: self.set_file_priority(1))
        self._menu_action(m, "Normal Priority", None, lambda: self.set_file_priority(4))
        if self.config.get("fine_priorities"):
            self._menu_action(m, "Higher Priority", None, lambda: self.set_file_priority(6))
        self._menu_action(m, "High Priority", None, lambda: self.set_file_priority(7))
        m.exec(self.files_table.viewport().mapToGlobal(pos))

    def _file_path(self, h, idx):
        return os.path.join(h.status().save_path, h.torrent_file().files().file_path(idx))

    def _open_media(self, h, idx):
        h.set_flags(lt.torrent_flags.sequential_download)
        prios = h.file_priorities()
        if prios[idx] < 7:
            prios[idx] = 7
            h.prioritize_files(prios)
        path = self._file_path(h, idx)
        if path.endswith(INCOMPLETE_EXT):
            self.strip_incomplete_ext(h, idx)
            path = path[:-len(INCOMPLETE_EXT)]
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Buffering",
                                    "Sequential streaming is on and this file is first in line. "
                                    "Try again in a few seconds once some data has arrived.")

    def play_selected_file(self):
        h = self.get_selected_handle()
        rows = self.files_table.selectionModel().selectedRows()
        if h and h.has_metadata() and rows:
            self._open_media(h, rows[0].row())

    def open_selected_file_folder(self):
        h = self.get_selected_handle()
        rows = self.files_table.selectionModel().selectedRows()
        if h and h.has_metadata() and rows:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._file_path(h, rows[0].row()))))

    def play_largest_file(self):
        h = self.get_selected_handle()
        if not h or not h.has_metadata():
            QMessageBox.information(self, "Playback", "Select a torrent (with metadata) first.")
            return
        fs = h.torrent_file().files()
        idxs = list(range(fs.num_files()))
        media = [i for i in idxs if fs.file_path(i).lower().replace(INCOMPLETE_EXT, "").endswith(MEDIA_EXTS)]
        best = max(media or idxs, key=lambda i: fs.file_size(i))
        self._open_media(h, best)

    def set_file_priority(self, level):
        h = self.get_selected_handle()
        if not h or not h.has_metadata():
            return
        rows = {i.row() for i in self.files_table.selectedIndexes()}
        prios = h.file_priorities()
        for r in rows:
            if r < len(prios):
                prios[r] = level
        h.prioritize_files(prios)
        self.update_inspector(h)

    # ------------------------------------------------------------------ trackers
    def add_tracker(self):
        h = self.get_selected_handle()
        if not h:
            return
        url, ok = QInputDialog.getText(self, "Add tracker", "Tracker announce URL:")
        if ok and url.strip():
            h.add_tracker({"url": url.strip(), "tier": len(h.trackers())})
            request_resume(h)
            self.update_inspector(h)

    def remove_tracker(self):
        h = self.get_selected_handle()
        rows = {i.row() for i in self.trackers_table.selectedIndexes()}
        if not h or not rows:
            return
        urls = {self.trackers_table.item(r, 0).text() for r in rows}
        if self.config.get("confirm_delete_tracker", True):
            if QMessageBox.question(self, "Remove tracker", f"Remove {len(urls)} tracker(s)?") != QMessageBox.StandardButton.Yes:
                return
        keep = [{"url": t["url"], "tier": t["tier"]} for t in h.trackers() if t["url"] not in urls]
        h.replace_trackers(keep)
        request_resume(h)
        self.update_inspector(h)

    # ------------------------------------------------------------------ RSS
    def fetch_rss_feeds(self, silent=False):
        feeds = self.config.get("rss_feeds", [])
        if not feeds:
            if not silent:
                QMessageBox.information(self, "No RSS Feeds", "Add RSS feed URLs in Options › Preferences › RSS Feeds first.")
            return
        if any(isinstance(w, RssWorker) for w in self._workers):
            return
        w = RssWorker(feeds)
        w.done.connect(lambda items, w=w: self.on_rss_done(items, w))
        self._workers.append(w)
        self._last_rss = time.time()
        w.start()

    def on_rss_done(self, items, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        self.rss_table.setRowCount(len(items))
        for r, it in enumerate(items):
            set_cell(self.rss_table, r, 0, it["title"])
            set_cell(self.rss_table, r, 1, it["feed"])
            set_cell(self.rss_table, r, 2, it["link"])
        if not self.config.get("rss_auto_download"):
            return
        filters = []
        for f in self.config.get("rss_filters", []):
            try:
                filters.append(re.compile(f, re.I))
            except re.error:
                filters.append(re.compile(re.escape(f), re.I))
        for it in items:
            link = it.get("link", "")
            if it.get("error") or not link or link in self.rss_seen:
                continue
            if any(f.search(it["title"]) for f in filters):
                self.rss_seen.append(link)
                self.log(f"RSS auto-download: {it['title']}")
                self.add_magnet_link(link, interactive=False)
        self.save_config()

    def download_rss_item(self):
        rows = self.rss_table.selectionModel().selectedRows()
        if not rows:
            return
        link = self.rss_table.item(rows[0].row(), 2).text()
        if link:
            self.add_magnet_link(link)

    # ------------------------------------------------------------------ sidebar / search
    def on_sidebar_clicked(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data[0] == "feeds":
            self.tabs.setCurrentWidget(self.rss_tab)
            return
        self.current_filter = tuple(data)
        self.refresh()

    def on_search_changed(self, text):
        self.search_query = text.strip().lower()
        self.refresh()

    # ------------------------------------------------------------------ inspector
    def on_selection_changed(self):
        h = self.get_selected_handle()
        if h:
            s = h.status()
            self.chk_sequential.blockSignals(True)
            self.chk_sequential.setChecked(bool(s.flags & lt.torrent_flags.sequential_download))
            self.chk_sequential.blockSignals(False)
            self.update_inspector(h, full=True)

    def update_inspector(self, h, full=False):
        if not h.is_valid():
            return
        s = h.status()
        current = self.tabs.currentWidget()
        if full or current is self.general_text:
            err = error_text(s)
            added = datetime.datetime.fromtimestamp(s.added_time).strftime("%Y-%m-%d %H:%M") if s.added_time else "-"
            done = datetime.datetime.fromtimestamp(s.completed_time).strftime("%Y-%m-%d %H:%M") if s.completed_time else "-"
            lines = [
                f"Name: {s.name}",
                f"Save As: {s.save_path}",
                f"Total Size: {fmt_bytes(s.total_wanted)}   |   Hash: {ih_of(h)}",
                f"Downloaded: {fmt_bytes(s.all_time_download)}   |   Uploaded: {fmt_bytes(s.all_time_upload)}   |   Ratio: {share_ratio(s):.3f}",
                f"Pieces: {s.num_pieces}   |   Seeds: {s.num_seeds} ({s.list_seeds})   |   Peers: {s.num_peers} ({s.list_peers})   |   Availability: {s.distributed_copies:.2f}",
                f"Added: {added}   |   Completed: {done}   |   Seeding time: {int(seeding_seconds(s) // 60)} min",
                f"Limits: down {fmt_speed(max(h.download_limit(), 0)) if h.download_limit() > 0 else '∞'}, up {fmt_speed(h.upload_limit()) if h.upload_limit() > 0 else '∞'}",
                f"Sequential Streaming: {'Enabled' if (s.flags & lt.torrent_flags.sequential_download) else 'Disabled'}",
            ]
            if err:
                lines.append(f"ERROR: {err}")
            text = "\n".join(lines)
            if self.general_text.toPlainText() != text:
                self.general_text.setPlainText(text)

        if (full or current is self.files_table) and h.has_metadata():
            fs = h.torrent_file().files()
            progress = h.file_progress()
            prios = h.file_priorities()
            n = fs.num_files()
            if self.files_table.rowCount() != n:
                self.files_table.setRowCount(n)
            names = {0: "Skip", 1: "Low", 2: "Low", 3: "Normal", 4: "Normal", 5: "Normal", 6: "Higher", 7: "High"}
            for i in range(n):
                fpath = fs.file_path(i)
                size = fs.file_size(i)
                frac = (progress[i] / size) if size > 0 else 1.0
                set_cell(self.files_table, i, 0, fpath)
                set_cell(self.files_table, i, 1, fmt_bytes(size))
                set_cell(self.files_table, i, 2, "", float(frac))
                set_cell(self.files_table, i, 3, names.get(prios[i], str(prios[i])))
                set_cell(self.files_table, i, 4, "Yes" if fpath.lower().replace(INCOMPLETE_EXT, "").endswith(MEDIA_EXTS) else "No")
        elif full and not h.has_metadata():
            self.files_table.setRowCount(0)

        if full or current is self.peers_table:
            peers = h.get_peer_info()
            self.peers_table.setRowCount(len(peers))
            for i, p in enumerate(peers):
                client = p.client.decode('utf-8', 'ignore') if isinstance(p.client, bytes) else str(p.client)
                set_cell(self.peers_table, i, 0, f"{p.ip[0]}:{p.ip[1]}")
                set_cell(self.peers_table, i, 1, client)
                set_cell(self.peers_table, i, 2, f"{p.progress * 100:.1f}%")
                set_cell(self.peers_table, i, 3, fmt_speed(p.down_speed))
                set_cell(self.peers_table, i, 4, fmt_speed(p.up_speed))
                flags = []
                if p.flags & lt.peer_info.seed:
                    flags.append("seed")
                if p.flags & lt.peer_info.utp_socket:
                    flags.append("uTP")
                if p.flags & (lt.peer_info.rc4_encrypted | lt.peer_info.plaintext_encrypted):
                    flags.append("enc")
                set_cell(self.peers_table, i, 5, " ".join(flags))

        if full or current is self.trackers_table.parent():
            trs = h.trackers()
            self.trackers_table.setRowCount(len(trs))
            for i, t in enumerate(trs):
                msg = ""
                for ep in t.get("endpoints", []) or []:
                    infos = ep.get("info_hashes") or [ep]
                    for inf in infos:
                        if inf.get("message"):
                            msg = inf["message"]
                        elif inf.get("fails"):
                            msg = f"failed ({inf['fails']}x)"
                        elif inf.get("updating"):
                            msg = "updating..."
                        elif not msg:
                            msg = "working" if inf.get("verified", True) else ""
                set_cell(self.trackers_table, i, 0, t["url"])
                set_cell(self.trackers_table, i, 1, str(t["tier"]))
                set_cell(self.trackers_table, i, 2, msg)

    # ------------------------------------------------------------------ periodic work
    def on_tick(self):
        if self._shutting_down:
            return
        self._tick += 1
        try:
            self.process_alerts()
            self.refresh(tick=True)
            if self._tick % 5 == 0:
                self.watch_folder()
            if self._tick % 30 == 0:
                self.apply_rate_limits()
                self.check_cap_period()
            if self._tick % 60 == 0:
                for h in self.handles:
                    try:
                        if h.need_save_resume_data():
                            request_resume(h)
                    except Exception:
                        pass
                self.save_config()
            mins = max(5, int(self.config.get("rss_refresh_min", 30)))
            if self.config.get("rss_feeds") and time.time() - getattr(self, "_last_rss", 0) > mins * 60:
                self.fetch_rss_feeds(silent=True)
        except Exception as e:
            self.log(f"Internal error: {e}")

    def process_alerts(self):
        for a in self.ses.pop_alerts():
            if isinstance(a, lt.save_resume_data_alert):
                self.write_resume(a)
            elif isinstance(a, lt.torrent_finished_alert):
                self.on_torrent_finished(a.handle)
            elif isinstance(a, lt.metadata_received_alert):
                self.apply_incomplete_ext(a.handle)
                request_resume(a.handle)
                self.log(f"Metadata received: {a.handle.status().name}")
            elif isinstance(a, (lt.torrent_error_alert, lt.file_error_alert)):
                self.log(f"Error: {a.message()}")
            elif isinstance(a, lt.storage_moved_alert):
                request_resume(a.handle)
                self.log(a.message())
            elif isinstance(a, lt.storage_moved_failed_alert):
                self.log(f"Move failed: {a.message()}")
            elif isinstance(a, (lt.listen_failed_alert, lt.portmap_error_alert)):
                self.log(a.message())

    def write_resume(self, a):
        try:
            ih = ih_of(a.handle)
        except Exception:
            return
        if ih not in self.handle_by_ih:
            return
        try:
            data = lt.write_resume_data_buf(a.params)
            path = os.path.join(STATE_DIR, f"{ih}.fastresume")
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        except Exception as e:
            self.log(f"Could not save resume data: {e}")

    def on_torrent_finished(self, h):
        if not h.is_valid():
            return
        ih = ih_of(h)
        self.strip_incomplete_ext(h)
        s = h.status()
        if ih not in self.finished_set:
            self.finished_set.add(ih)
            if s.total_payload_download > 0:
                self.log(f"Download complete: {s.name}")
                if self.config.get("notify_complete", True):
                    self.notify("Download complete", s.name)
            self.move_completed(h, s)
            if self.config.get("move_finished_torrents") and ih in self.stored_torrents:
                src = self.stored_torrents[ih]
                dst_dir = self.config.get("finished_torrents_path", "")
                if dst_dir and os.path.exists(src):
                    try:
                        os.makedirs(dst_dir, exist_ok=True)
                        dst = os.path.join(dst_dir, os.path.basename(src))
                        shutil.move(src, dst)
                        self.stored_torrents[ih] = dst
                    except Exception as e:
                        self.log(f"Could not move .torrent: {e}")
            self.save_config()
        request_resume(h)

    def move_completed(self, h, s):
        c = self.config
        comp = c.get("completed_path", "")
        if not c.get("move_completed_enabled") or not comp:
            return
        lbl = self.torrent_labels.get(ih_of(h), "")
        target = os.path.join(comp, lbl) if (c.get("append_label_to_path") and lbl) else comp
        if c.get("only_move_from_default", True) and c.get("save_path"):
            if os.path.normcase(os.path.normpath(s.save_path)) != os.path.normcase(os.path.normpath(c["save_path"])):
                return
        if os.path.normcase(os.path.normpath(s.save_path)) == os.path.normcase(os.path.normpath(target)):
            return
        try:
            os.makedirs(target, exist_ok=True)
            h.move_storage(target)
        except Exception as e:
            self.log(f"Could not move completed download: {e}")

    def watch_folder(self):
        if not self.config.get("watch_enabled"):
            return
        d = self.config.get("watch_path", "")
        if not d or not os.path.isdir(d):
            return
        for fname in os.listdir(d):
            if not fname.lower().endswith(".torrent"):
                continue
            full = os.path.join(d, fname)
            self.log(f"Watch folder: loading {fname}")
            self.add_torrent_file(full, interactive=False)
            try:
                if self.config.get("delete_loaded_torrents"):
                    os.remove(full)
                else:
                    os.replace(full, full + ".loaded")
            except OSError:
                pass

    # -- transfer cap --
    def cap_key(self):
        p = self.config.get("transfer_cap_period", "Monthly")
        now = datetime.date.today()
        if p == "Daily":
            return now.isoformat()
        if p == "Monthly":
            return now.strftime("%Y-%m")
        return f"session-{int(self.started_at)}"

    def check_cap_period(self, startup=False):
        key = self.cap_key()
        if self.config.get("cap_period_key") != key:
            self.config["cap_period_key"] = key
            self.config["cap_used_bytes"] = 0
            if not startup:
                self.log("Transfer cap counter reset for the new period.")
            self.resume_cap_paused()

    def resume_cap_paused(self):
        for ih in self.cap_paused:
            h = self.handle_by_ih.get(ih)
            if h is not None and h.is_valid():
                h.set_flags(lt.torrent_flags.auto_managed)
                h.resume()
        self.cap_paused = []

    def enforce_cap(self):
        c = self.config
        if not c.get("transfer_cap_enabled") or self.cap_paused:
            return
        if c.get("cap_used_bytes", 0) >= float(c.get("transfer_cap_gb", 500)) * (1024 ** 3):
            for h in self.handles:
                s = h.status()
                if not (s.flags & lt.torrent_flags.paused):
                    h.unset_flags(lt.torrent_flags.auto_managed)
                    h.pause()
                    self.cap_paused.append(ih_of(h))
            if self.cap_paused:
                self.log("Transfer cap reached — all torrents paused.")
                self.notify("Transfer cap reached", "All torrents were paused. Change the cap in Preferences › Transfer Cap.")

    # -- main refresh --
    def refresh(self, tick=False):
        counts = {k: 0 for k in NAV_KEYS}
        label_counts = {}
        rows = []
        tot_dl = tot_ul = 0
        delta = 0
        any_downloading = False
        ratio_goal = float(self.config.get("seed_ratio_limit", 0.0))
        time_goal = int(self.config.get("seed_time_limit_min", 0)) * 60

        for h in list(self.handles):
            if not h.is_valid():
                continue
            s = h.status()
            ih = ih_of(h)
            lbl = self.torrent_labels.get(ih, "")
            paused = bool(s.flags & lt.torrent_flags.paused)
            user_paused = paused and not (s.flags & lt.torrent_flags.auto_managed)
            complete = s.progress >= 1.0 or s.is_seeding
            active = (s.download_rate > 0 or s.upload_rate > 0) and not paused
            err = bool(error_text(s))

            if tick:
                last = self._last_totals.get(ih, (0, 0))
                d = s.total_download - last[0] if s.total_download >= last[0] else s.total_download
                u = s.total_upload - last[1] if s.total_upload >= last[1] else s.total_upload
                self._last_totals[ih] = (s.total_download, s.total_upload)
                delta += d + u
                self.session_dl += d
                self.session_ul += u

                if complete and not paused and ih not in self.goal_done and (ratio_goal > 0 or time_goal > 0):
                    reached = (ratio_goal > 0 and share_ratio(s) >= ratio_goal) or \
                              (time_goal > 0 and seeding_seconds(s) >= time_goal)
                    if reached:
                        h.unset_flags(lt.torrent_flags.auto_managed)
                        h.pause()
                        self.goal_done.add(ih)
                        self.log(f"Seeding goal reached, stopped: {s.name}")

            if not complete and not paused:
                any_downloading = True
            counts["All"] += 1
            counts["Downloading"] += (not complete and not user_paused)
            counts["Seeding"] += (complete and not paused)
            counts["Completed"] += complete
            counts["Active"] += active
            counts["Inactive"] += not active
            counts["Paused"] += user_paused
            counts["Errors"] += err
            if lbl:
                label_counts[lbl] = label_counts.get(lbl, 0) + 1
            tot_dl += s.download_rate
            tot_ul += s.upload_rate

            if self.search_query and self.search_query not in (s.name or "").lower():
                continue
            kind, key = self.current_filter
            if kind == "label":
                show = lbl == key
            else:
                show = {"All": True, "Downloading": not complete and not user_paused,
                        "Seeding": complete and not paused, "Completed": complete,
                        "Active": active, "Inactive": not active, "Paused": user_paused, "Errors": err}.get(key, True)
            if show:
                rows.append((h, s, ih, lbl, paused, err))

        if tick:
            self.config["cap_used_bytes"] = self.config.get("cap_used_bytes", 0) + delta
            self.enforce_cap()
            want_awake = any_downloading and self.config.get("prevent_standby", True)
            if want_awake != self._keep_awake:
                self._keep_awake = want_awake
                set_keep_awake(want_awake)

        # Sidebar
        self.torrents_root.setText(0, f"Torrents ({counts['All']})")
        for k, it in self.nav_items.items():
            it.setText(0, f"{k} ({counts[k]})")
        for lbl, it in self.label_items.items():
            it.setText(0, f"{lbl} ({label_counts.get(lbl, 0)})")

        # Torrent table — ordered by queue position (seeds at the end)
        rows.sort(key=lambda r: (r[1].queue_position < 0, r[1].queue_position, (r[1].name or "").lower()))
        selected = {ih_of(h) for h in self.selected_handles()}
        if self.table.rowCount() != len(rows):
            self.table.setRowCount(len(rows))
        for row, (h, s, ih, lbl, paused, err) in enumerate(rows):
            auto = bool(s.flags & lt.torrent_flags.auto_managed)
            st = int(s.state)
            if err:
                status = "Error"
            elif paused and auto:
                status = "Queued (seed)" if s.progress >= 1.0 else "Queued"
            elif paused:
                status = "Paused" + (" (cap)" if ih in self.cap_paused else "")
            else:
                status = STATES[st] if st < len(STATES) else str(st)
                if not auto:
                    status = "[F] " + status
            qp = s.queue_position
            set_cell(self.table, row, 0, str(qp + 1) if qp >= 0 else "*")
            set_cell(self.table, row, 1, s.name or "Fetching metadata...", ih)
            set_cell(self.table, row, 2, fmt_bytes(s.total_wanted))
            set_cell(self.table, row, 3, "", float(s.progress))
            set_cell(self.table, row, 4, status)
            set_cell(self.table, row, 5, f"{s.num_seeds} ({s.list_seeds})")
            set_cell(self.table, row, 6, f"{s.num_peers - s.num_seeds} ({max(s.list_peers - s.list_seeds, 0)})")
            set_cell(self.table, row, 7, fmt_speed(s.download_rate) if s.download_rate else "")
            set_cell(self.table, row, 8, fmt_speed(s.upload_rate) if s.upload_rate else "")
            set_cell(self.table, row, 9, "" if paused else fmt_eta(s.total_wanted - s.total_wanted_done, s.download_rate))
            set_cell(self.table, row, 10, f"{share_ratio(s):.3f}")
            set_cell(self.table, row, 11, lbl)

        # keep selection on the same torrents after re-ordering
        sm = self.table.selectionModel()
        cur = {self.table.item(r, 1).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())
               if sm.isRowSelected(r) and self.table.item(r, 1)}
        if selected and cur != selected:
            self.table.blockSignals(True)
            self.table.clearSelection()
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 1)
                if it and it.data(Qt.ItemDataRole.UserRole) in selected:
                    self.table.selectRow(r) if len(selected) == 1 else sm.select(
                        self.table.model().index(r, 0),
                        sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
            self.table.blockSignals(False)

        h = self.get_selected_handle()
        if h:
            self.update_inspector(h)

        # Status bar, title, tray, graph
        limited = bool(self._limited)
        c = self.config
        lim = ""
        if c.get("limits_in_status", True):
            if limited:
                lim = f"   |   🐢 Limited: D {c.get('scheduler_dl_kbps')} / U {c.get('scheduler_ul_kbps')} kB/s"
            else:
                d, u = c.get("max_dl_kbps", 0), c.get("max_ul_kbps", 0)
                lim = f"   |   Limits: D {d or '∞'} / U {u or '∞'} kB/s"
        cap = ""
        if c.get("transfer_cap_enabled"):
            cap = f"   |   Cap: {fmt_bytes(c.get('cap_used_bytes', 0))} / {c.get('transfer_cap_gb')} GB"
        try:
            dht = self.ses.status().dht_nodes
        except Exception:
            dht = 0
        self.status_label.setText(
            f"DHT: {dht} nodes   |   D: {fmt_speed(tot_dl)}  T: {fmt_bytes(self.session_dl)}   |   "
            f"U: {fmt_speed(tot_ul)}  T: {fmt_bytes(self.session_ul)}{lim}{cap}")
        if c.get("speed_in_title"):
            self.setWindowTitle(f"[D: {fmt_speed(tot_dl)} U: {fmt_speed(tot_ul)}] {self.base_title}")
        elif self.windowTitle() != self.base_title:
            self.setWindowTitle(self.base_title)
        self.tray_icon.setToolTip(f"{APP_NAME}\nD: {fmt_speed(tot_dl)}\nU: {fmt_speed(tot_ul)}")
        if tick:
            self.speed_graph.add(tot_dl, tot_ul, f"Session: ↓ {fmt_bytes(self.session_dl)}  ↑ {fmt_bytes(self.session_ul)}")

    # ------------------------------------------------------------------ dialogs
    def open_preferences(self):
        PreferencesDialog(self.config, self).exec()

    def open_create_torrent(self):
        CreateTorrentDialog(self).exec()

    def show_about(self):
        msg = QMessageBox(self)
        msg.setWindowTitle(f"About {APP_NAME}")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            f"<h2>{APP_NAME} {APP_VERSION} — Free Edition</h2>"
            f"<p><b>Developer:</b> {ORG}</p>"
            "<p><b>Website:</b> <a href='https://smartupworld.com'>https://smartupworld.com</a></p>"
            "<p><b>License:</b> 100% Free &amp; Ad-Free</p>"
            f"<p>libtorrent {lt.__version__}</p>"
            "<br><p>Full-featured BitTorrent client: default and completed folders, watch folders, "
            "proxy &amp; VPN binding, IP blocklists, bandwidth scheduler, transfer cap, labels, "
            "RSS auto-downloader, torrent creator and sequential streaming.</p>")
        msg.exec()

    # ------------------------------------------------------------------ window events
    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange and self.isMinimized():
            if self.config.get("minimize_btn_to_tray", False):
                QTimer.singleShot(0, self.hide_to_tray)
        super().changeEvent(event)

    def closeEvent(self, event):
        if self._shutting_down:
            event.accept()
            return
        if self.config.get("close_btn_to_tray", True):
            event.ignore()
            self.hide_to_tray()
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                self.notify(APP_NAME, "Still running in the system tray. Right-click the tray icon to exit.")
        else:
            event.ignore()
            self.quit_application()

    def quit_application(self):
        if self.config.get("confirm_critical_seeder", True):
            critical = [h.status().name for h in self.handles
                        if h.is_valid() and h.status().is_seeding and h.status().num_peers > 0
                        and 0 <= h.status().distributed_copies < 1.0]
            if critical:
                if QMessageBox.question(self, "Critical seeder",
                                        "You are the only full source for:\n" + "\n".join(critical[:5]) +
                                        "\n\nExit anyway?") != QMessageBox.StandardButton.Yes:
                    return
        if self.config.get("confirm_exit", True):
            if QMessageBox.question(self, f"Exit {APP_NAME}", f"Are you sure you want to exit {APP_NAME}?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self.shutdown()
        QApplication.instance().quit()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self.timer.stop()
        try:
            self.ses.pause()
        except Exception:
            pass
        outstanding = sum(1 for h in self.handles if h.is_valid() and request_resume(h))
        deadline = time.time() + 8
        while outstanding > 0 and time.time() < deadline:
            if not self.ses.wait_for_alert(500):
                continue
            for a in self.ses.pop_alerts():
                if isinstance(a, lt.save_resume_data_alert):
                    self.write_resume(a)
                    outstanding -= 1
                elif isinstance(a, lt.save_resume_data_failed_alert):
                    outstanding -= 1
        try:
            with open(SESSION_FILE, "wb") as f:
                f.write(lt.write_session_params_buf(self.ses.session_state()))
        except Exception:
            pass
        self.save_config()
        set_keep_awake(False)
        self.tray_icon.hide()
        try:
            self.ipc.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Single instance + startup
# ----------------------------------------------------------------------------
def send_to_running_instance(args, wait_ms=700):
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if not sock.waitForConnected(wait_ms):
        return False
    sock.write(json.dumps([os.path.abspath(a) if os.path.isfile(a) else a for a in args]).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1500)
    sock.disconnectFromServer()
    return True


def main():
    args = sys.argv[1:]
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORG}.STorrentPro")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    # 1) Already running? Hand our arguments over and quit.
    if send_to_running_instance(args):
        return 0
    if IS_WIN:
        kernel32 = ctypes.windll.kernel32
        main._mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if kernel32.GetLastError() == 183:          # another copy is starting right now
            for _ in range(20):
                if send_to_running_instance(args, 300):
                    return 0
                time.sleep(0.2)
            return 0

    # 2) We are the first instance: start listening for later launches.
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(IPC_NAME):
        QLocalServer.removeServer(IPC_NAME)
        server.listen(IPC_NAME)

    os.makedirs(DATA_DIR, exist_ok=True)
    window = STorrentClient(server, args)
    if "--minimized" in args and QSystemTrayIcon.isSystemTrayAvailable():
        window.hide_to_tray()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
