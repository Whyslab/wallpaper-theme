"""
Интерфейс под цвет обоев — включается и выключается.

Режимы:
  off     — всё как в теме Monochrome Vivid, ничего не подмешивается
  vivid   — яркие цвета из обоев (matugen, схема vibrant)
  tinted  — чёрно-белое с лёгким оттенком обоев (matugen, схема neutral)

Главный принцип: свои файлы темы не переписываются. В конец каждого конфига один
раз (`integrate`) добавляется подключение сгенерированного файла из
~/.cache/wallpaper-theme/. В режиме off эти файлы пустые, поэтому выключение
возвращает всё ровно как было, а удаление строк подключения — как до установки.

Что перекрашивается и откуда берётся цвет:
  панель HyprPanel   — её собственный режим matugen (theme.matugen в config.json)
  рамки окон         — hyprland.conf ← source сгенерированного файла; сразу через hyprctl
  rofi               — все темы ← @import сгенерированного файла; при следующем открытии
  kitty              — kitty.conf ← include; сразу через SIGUSR1
  GTK-программы      — блок между метками в gtk.css; при следующем запуске программы
  экран блокировки   — hyprlock.conf ← source после colors.conf; по обоям блокировки
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
from pathlib import Path

MODES = ("off", "vivid", "tinted")
SCHEME = {"vivid": "vibrant", "tinted": "neutral"}

HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "wallpaper-theme"
MODE_FILE = CONFIG_DIR / "mode"
OUT_DIR = HOME / ".cache" / "wallpaper-theme"
WALLPAPER_STATE = HOME / ".local" / "state" / "hypr-wallpaper"

HYPRLAND_CONF = HOME / ".config" / "hypr" / "hyprland.conf"
HYPRLOCK_CONF = HOME / ".config" / "hypr" / "hyprlock.conf"
HYPRLOCK_COLORS = HOME / ".config" / "hypr" / "colors.conf"
KITTY_CONF = HOME / ".config" / "kitty" / "kitty.conf"
HYPRPANEL_CONF = HOME / ".config" / "hyprpanel" / "config.json"
GTK_CSS = (HOME / ".config" / "gtk-3.0" / "gtk.css", HOME / ".config" / "gtk-4.0" / "gtk.css")
ROFI_THEMES = (
    HOME / ".config" / "rofi" / "config.rasi",
    HOME / ".config" / "rofi" / "wallpaper.rasi",
    HOME / ".local" / "share" / "rofi-launcher" / "themes" / "hub.rasi",
    HOME / ".local" / "share" / "rofi-launcher" / "themes" / "grid.rasi",
    HOME / ".local" / "share" / "rofi-launcher" / "themes" / "monochrome.rasi",
)

MARK = "wallpaper-theme"
GTK_START = "/* wallpaper-theme:start — генерируется, не править */"
GTK_END = "/* wallpaper-theme:end */"

# Роли палитры, которые нужны рендерам. Всё из тёмного варианта схемы.
ROLES = (
    "primary", "on_primary", "surface", "surface_container_lowest",
    "surface_container", "surface_container_high", "on_surface",
    "on_surface_variant", "outline", "outline_variant",
)


class ThemeError(RuntimeError):
    """Что-то, о чём нужно сказать пользователю, а не упасть молча."""


# ─────────────────────────── палитра ───────────────────────────

def parse_matugen(output):
    """JSON от `matugen --json hex` → {роль: "#rrggbb"} тёмной схемы."""
    data = json.loads(output)
    colors = data["colors"]
    palette = {}
    for role in ROLES:
        value = colors[role]
        if isinstance(value, dict):
            value = value.get("dark") or value.get("default")
        if isinstance(value, dict):
            value = value["color"]
        palette[role] = value.lower()
    return palette


def palette_from_image(image, mode):
    """Палитра по картинке. `--source-color-index 0`: без него matugen 4.2 на
    картинке с несколькими главными цветами спрашивает пользователя в терминале,
    а при запуске из скрипта просто падает."""
    if mode not in SCHEME:
        raise ThemeError(f"нет палитры для режима {mode}")
    if not Path(image).is_file():
        raise ThemeError(f"нет картинки обоев: {image}")
    result = subprocess.run(
        ["matugen", "image", str(image), "-t", f"scheme-{SCHEME[mode]}", "-m", "dark",
         "--json", "hex", "--dry-run", "--source-color-index", "0", "-q"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ThemeError(f"matugen не смог разобрать картинку: {result.stderr.strip()[:200]}")
    return parse_matugen(result.stdout)


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ─────────────────────────── рендеры ───────────────────────────
# Каждый получает палитру или None (режим off) и возвращает текст файла.
# Для off файл пустой, но существует: подключение пустого файла ничего не меняет,
# а подключение отсутствующего у некоторых программ — ошибка.

def render_hyprland(p):
    head = "# wallpaper-theme: генерируется, не править\n"
    if p is None:
        return head
    active = p["primary"].lstrip("#")
    inactive = p["outline_variant"].lstrip("#")
    return head + (
        "general {\n"
        f"    col.active_border = rgba({active}ff)\n"
        f"    col.inactive_border = rgba({inactive}ff)\n"
        "}\n"
    )


def render_kitty(p):
    head = "# wallpaper-theme: генерируется, не править\n"
    if p is None:
        return head
    # Только фон, текст, курсор и выделение. 16 цветов терминала не трогаем:
    # программы рассчитывают на привычные красный/зелёный, и читаемость важнее.
    return head + (
        f"background {p['surface_container_lowest']}\n"
        f"foreground {p['on_surface']}\n"
        f"cursor {p['primary']}\n"
        f"cursor_text_color {p['on_primary']}\n"
        f"selection_background {p['primary']}\n"
        f"selection_foreground {p['on_primary']}\n"
    )


def render_rofi(p):
    head = "/* wallpaper-theme: генерируется, не править */\n"
    if p is None:
        return head
    # У тем rofi две схемы имён переменных; задаём обе, лишние ни на что не влияют.
    return head + "* {\n" + "".join(f"    {k}: {v};\n" for k, v in (
        ("bg", p["surface_container_lowest"]),
        ("bg-element", p["surface_container_high"]),
        ("fg", p["on_surface"]),
        ("fg-alt", p["outline"]),
        ("accent", p["primary"]),
        ("accent-text", p["on_primary"]),
        ("bg-base", p["surface_container_lowest"]),
        ("bg-elevated", p["surface_container_high"]),
        ("bg-selected", p["primary"]),
        ("fg-primary", p["on_surface"]),
        ("fg-secondary", p["outline"]),
        ("border-color", p["outline_variant"]),
    )) + "}\n"


# Имя цвета GTK → роль палитры. Имена, которых нет в таблице, не трогаются.
GTK_ROLES = {
    "window_bg_color": "surface_container_lowest",
    "dialog_bg_color": "surface_container_lowest",
    "view_bg_color": "surface",
    "headerbar_bg_color": "surface",
    "sidebar_bg_color": "surface",
    "popover_bg_color": "surface",
    "card_bg_color": "surface_container_high",
    "thumbnail_bg_color": "surface_container_high",
    "shade_color": "outline_variant",
    "scrollbar_outline_color": "outline_variant",
    "window_fg_color": "on_surface",
    "headerbar_fg_color": "on_surface",
    "card_fg_color": "on_surface",
    "dialog_fg_color": "on_surface",
    "popover_fg_color": "on_surface",
    "view_fg_color": "on_surface_variant",
    "sidebar_fg_color": "on_surface_variant",
    "accent_bg_color": "primary",
    "accent_color": "primary",
    "accent_fg_color": "on_primary",
    "theme_bg_color": "surface_container_lowest",
    "theme_fg_color": "on_surface",
    "theme_base_color": "surface",
    "theme_text_color": "on_surface_variant",
    "theme_selected_bg_color": "primary",
    "theme_selected_fg_color": "on_primary",
    "theme_view_bg_color": "surface",
    "borders": "outline_variant",
    "unfocused_borders": "outline_variant",
    "tooltip_bg_color": "surface_container_lowest",
    "tooltip_fg_color": "on_surface",
    "content_view_bg": "surface",
}


def render_gtk_block(p):
    lines = [GTK_START]
    if p is not None:
        lines += [f"@define-color {name} {p[role]};" for name, role in GTK_ROLES.items()]
    lines.append(GTK_END)
    return "\n".join(lines)


def replace_gtk_block(css_text, p):
    """Вписать блок между метками; если меток нет — дописать в конец.

    В конец, а не в начало: в CSS GTK побеждает последнее определение цвета."""
    block = render_gtk_block(p)
    pattern = re.compile(re.escape(GTK_START) + r".*?" + re.escape(GTK_END), re.S)
    if pattern.search(css_text):
        return pattern.sub(lambda _m: block, css_text, count=1)
    sep = "" if css_text.endswith("\n") else "\n"
    return css_text + sep + "\n" + block + "\n"


def strip_gtk_block(css_text):
    pattern = re.compile(r"\n?\n?" + re.escape(GTK_START) + r".*?" + re.escape(GTK_END) + r"\n?", re.S)
    return pattern.sub("\n", css_text).rstrip("\n") + "\n"


_HYPRLOCK_VAR = re.compile(
    r"^\$(?P<name>c_\w+)\s*=\s*rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*(?P<alpha>[\d.]+)\s*\)",
    re.M,
)


def _hyprlock_role(name):
    if "ring" in name or "border" in name:
        return "primary"
    if "black" in name:
        return "surface_container_lowest"
    if "panel" in name:
        return "surface_container"
    if "white" in name:
        return "on_surface"
    if "grey" in name or "gray" in name:
        return "on_surface_variant"
    return None


def render_hyprlock(p, colors_conf_text):
    """Переопределения переменных из colors.conf: цвет из палитры, прозрачность
    своя. Так уровни «обычное / caps lock / ошибка» у колец остаются различимыми —
    они и задуманы яркостью, а не оттенком."""
    head = "# wallpaper-theme: генерируется, не править\n"
    if p is None:
        return head
    out = [head]
    for m in _HYPRLOCK_VAR.finditer(colors_conf_text):
        role = _hyprlock_role(m.group("name"))
        if role is None:
            continue
        r, g, b = _rgb(p[role])
        out.append(f"${m.group('name')} = rgba({r}, {g}, {b}, {m.group('alpha')})\n")
    return "".join(out)


def set_hyprpanel(config, mode, image):
    """Режим matugen у панели. Её собственные цвета не трогаются: panel сама
    подменяет их при отрисовке, а при выключении берёт снова из конфига."""
    config = dict(config)
    if mode == "off":
        config["theme.matugen"] = False
        return config
    config["theme.matugen"] = True
    config["theme.matugen_settings.scheme_type"] = SCHEME[mode]
    config["theme.matugen_settings.mode"] = "dark"
    config["wallpaper.image"] = str(image)
    return config


# ─────────────────────────── подключения ───────────────────────────

def hook_line(kind, out_dir=None):
    """Строка подключения для файла вида kind. Абсолютный путь: `~` понимают не все."""
    out_dir = out_dir or OUT_DIR
    path = {
        "hyprland": out_dir / "hyprland.conf",
        "hyprlock": out_dir / "hyprlock.conf",
        "kitty": out_dir / "kitty.conf",
        "rofi": out_dir / "rofi.rasi",
    }[kind]
    return {
        "hyprland": f"source = {path}  # {MARK}",
        "hyprlock": f"source = {path}  # {MARK}",
        # kitty понимает комментарии только на отдельной строке: «# …» после пути
        # стал бы частью пути. Метка и так есть в самом пути (…/wallpaper-theme/…).
        "kitty": f"include {path}",
        "rofi": f'@import "{path}" /* {MARK} */',
    }[kind]


def add_hook(text, line, after=None):
    """Добавить строку подключения, если её ещё нет. `after` — регулярка строки,
    сразу после которой ставить (для hyprlock: после подключения colors.conf, до
    первого использования переменных); без неё — в конец."""
    if MARK in text and line in text:
        return text
    if after is not None:
        match = re.search(after, text, re.M)
        if match is None:
            raise ThemeError(f"не нашёл, куда вставить: {after}")
        end = text.find("\n", match.end())
        end = len(text) if end == -1 else end
        return text[:end] + "\n" + line + text[end:]
    sep = "" if text.endswith("\n") or not text else "\n"
    return text + sep + line + "\n"


def remove_hook(text):
    return "".join(line for line in text.splitlines(keepends=True) if MARK not in line)


# ─────────────────────────── действия с системой ───────────────────────────

def read_mode():
    try:
        mode = MODE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "off"
    return mode if mode in MODES else "off"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".wt-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _edit(path, change):
    """Применить change к файлу. True — если файл действительно изменился."""
    if not path.is_file():
        return False
    old = path.read_text(encoding="utf-8")
    new = change(old)
    if new == old:
        return False
    _write(path, new)
    return True


def integrate():
    """Один раз: подключить сгенерированные файлы. Повторный вызов ничего не ломает."""
    # Файлы должны существовать до того, как на них сошлются конфиги.
    empty = {
        "hyprland.conf": render_hyprland(None),
        "hyprlock.conf": render_hyprlock(None, ""),
        "kitty.conf": render_kitty(None),
        "rofi.rasi": render_rofi(None),
    }
    for name, text in empty.items():
        if not (OUT_DIR / name).exists():
            _write(OUT_DIR / name, text)
    done = []
    if _edit(HYPRLAND_CONF, lambda t: add_hook(t, hook_line("hyprland"))):
        done.append(str(HYPRLAND_CONF))
    if _edit(HYPRLOCK_CONF, lambda t: add_hook(
            t, hook_line("hyprlock"), after=r"^source\s*=.*colors\.conf.*$")):
        done.append(str(HYPRLOCK_CONF))
    if _edit(KITTY_CONF, lambda t: add_hook(t, hook_line("kitty"))):
        done.append(str(KITTY_CONF))
    for rasi in ROFI_THEMES:
        if _edit(rasi, lambda t: add_hook(t, hook_line("rofi"))):
            done.append(str(rasi))
    for css in GTK_CSS:
        if _edit(css, lambda t: replace_gtk_block(t, None) if GTK_START not in t else t):
            done.append(str(css))
    return done


def unintegrate():
    """Убрать все строки подключения и блоки GTK. Файлы в кэше остаются, но уже
    ни на что не влияют."""
    for path in (HYPRLAND_CONF, HYPRLOCK_CONF, KITTY_CONF, *ROFI_THEMES):
        _edit(path, remove_hook)
    for css in GTK_CSS:
        _edit(css, strip_gtk_block)


def current_image(target):
    try:
        return Path((WALLPAPER_STATE / f"{target}.path").read_text(encoding="utf-8").strip())
    except OSError:
        return None


def _run(*cmd):
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def _kitty_pids():
    out = _run("pgrep", "-x", "kitty").stdout.split()
    return [int(pid) for pid in out if pid.isdigit()]


def notify(text):
    _run("notify-send", "-a", "Интерфейс под обои", "Интерфейс под обои", text)


def refresh(target="all", mode=None):
    """Пересчитать и применить. target: desktop, lock или all."""
    mode = mode or read_mode()
    problems = []

    if target in ("desktop", "all"):
        image = current_image("desktop")
        palette = None
        if mode != "off":
            try:
                palette = palette_from_image(image, mode) if image else None
                if palette is None:
                    raise ThemeError("не знаю, какие сейчас обои рабочего стола")
            except ThemeError as exc:
                problems.append(str(exc))
        if mode == "off" or palette is not None:
            _write(OUT_DIR / "hyprland.conf", render_hyprland(palette))
            _write(OUT_DIR / "kitty.conf", render_kitty(palette))
            _write(OUT_DIR / "rofi.rasi", render_rofi(palette))
            for css in GTK_CSS:
                _edit(css, lambda t, p=palette: replace_gtk_block(t, p))
            if HYPRPANEL_CONF.is_file():
                panel = json.loads(HYPRPANEL_CONF.read_text(encoding="utf-8"))
                updated = set_hyprpanel(panel, mode, image)
                if updated != panel:
                    _write(HYPRPANEL_CONF, json.dumps(updated, indent=2) + "\n")
            _apply_live(palette)

    if target in ("lock", "all"):
        image = current_image("lock")
        palette = None
        if mode != "off":
            try:
                palette = palette_from_image(image, mode) if image else None
                if palette is None:
                    raise ThemeError("не знаю, какие сейчас обои блокировки")
            except ThemeError as exc:
                problems.append(str(exc))
        if mode == "off" or palette is not None:
            colors = HYPRLOCK_COLORS.read_text(encoding="utf-8") if HYPRLOCK_COLORS.is_file() else ""
            _write(OUT_DIR / "hyprlock.conf", render_hyprlock(palette, colors))
    return problems


def _apply_live(palette):
    """То, что можно показать сразу. rofi, GTK и блокировка подхватят при открытии."""
    if palette is None:
        # Рамки вернёт только перечитывание конфига: keyword не умеет «снять».
        _run("hyprctl", "reload")
    else:
        _run("hyprctl", "keyword", "general:col.active_border",
             f"rgba({palette['primary'].lstrip('#')}ff)")
        _run("hyprctl", "keyword", "general:col.inactive_border",
             f"rgba({palette['outline_variant'].lstrip('#')}ff)")
    for pid in _kitty_pids():
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGUSR1)  # kitty перечитывает конфиг


def set_mode(mode):
    if mode not in MODES:
        raise ThemeError(f"неизвестный режим: {mode}")
    _write(MODE_FILE, mode + "\n")
    problems = refresh("all", mode)
    label = {"off": "выключен", "vivid": "яркий", "tinted": "приглушённый"}[mode]
    if problems:
        notify(f"Режим {label}, но: " + "; ".join(problems))
    else:
        notify(f"Режим {label}. Панель обновится через несколько секунд, "
               "программы на GTK — при следующем запуске.")
    return problems
