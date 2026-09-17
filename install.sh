#!/usr/bin/env bash
# install.sh — установить «интерфейс под обои».
#
#   ./install.sh            установить и подключить
#   ./install.sh --dry-run  только показать, что будет сделано
#
# Что делает:
#   1. копирует программу в ~/.local/share/wallpaper-theme и ставит команду
#      ~/.local/bin/wallpaper-theme;
#   2. сохраняет копии всех конфигов, которые будут тронуты, в
#      ~/.local/share/repo-backups/wallpaper-theme-before-install-<дата-время>/;
#   3. подключает сгенерированные файлы (wallpaper-theme integrate);
#   4. встраивает пересчёт в ~/.config/hypr/scripts/wallpaper.sh и пункт
#      «Интерфейс под обои» в ~/.config/hypr/scripts/wallpaper-picker.sh.
# Режим после установки — выключен: ничего не меняется, пока не включишь.
# Повторный запуск безопасен: всё, что уже сделано, пропускается.

set -Eeuo pipefail

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1
[[ $EUID -ne 0 ]] || { echo "не запускай от root" >&2; exit 1; }

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP="$HOME/.local/share/wallpaper-theme"
BIN="$HOME/.local/bin/wallpaper-theme"
BACKUP="$HOME/.local/share/repo-backups/wallpaper-theme-before-install-$(date +%Y-%m-%d-%H%M%S)"
HYPR_SCRIPTS="$HOME/.config/hypr/scripts"

say() { printf '==> %s\n' "$*"; }
run() { if (( DRY )); then printf '   would run: %s\n' "$*"; else "$@"; fi; }

command -v matugen >/dev/null || { echo "нет matugen: pkexec pacman -S matugen" >&2; exit 1; }
command -v python3 >/dev/null || { echo "нет python3" >&2; exit 1; }

say "Копии конфигов → $BACKUP"
run mkdir -p "$BACKUP"
for f in .config/hypr/hyprland.conf .config/hypr/hyprlock.conf .config/kitty/kitty.conf \
         .config/hyprpanel/config.json .config/gtk-3.0/gtk.css .config/gtk-4.0/gtk.css \
         .config/rofi/config.rasi .config/rofi/wallpaper.rasi \
         .local/share/rofi-launcher/themes/hub.rasi .local/share/rofi-launcher/themes/grid.rasi \
         .local/share/rofi-launcher/themes/monochrome.rasi \
         .config/hypr/scripts/wallpaper.sh .config/hypr/scripts/wallpaper-picker.sh; do
    [[ -e "$HOME/$f" ]] || continue
    run mkdir -p "$BACKUP/$(dirname "$f")"
    run cp -p "$HOME/$f" "$BACKUP/$f"
done

say "Программа → $APP"
run install -d -m 755 "$APP/bin" "$(dirname "$BIN")"
run install -m 644 "$SRC/wallpaper_theme.py" "$APP/wallpaper_theme.py"
run install -m 755 "$SRC/bin/wallpaper-theme" "$APP/bin/wallpaper-theme"
run ln -sfn "$APP/bin/wallpaper-theme" "$BIN"

say "Подключение к конфигам"
if (( DRY )); then
    echo "   would run: $BIN integrate"
else
    "$BIN" integrate
fi

say "Встраивание в скрипты обоев"
if (( DRY )); then
    echo "   would patch: $HYPR_SCRIPTS/wallpaper.sh, $HYPR_SCRIPTS/wallpaper-picker.sh"
else
    python3 - "$HYPR_SCRIPTS" <<'PY'
import sys
from pathlib import Path

scripts = Path(sys.argv[1])
MARK = "wallpaper-theme"

# Обновления уже встроенного кода из прошлых версий установщика.
UPGRADES = [
    ('theme_refresh() {\n    command -v wallpaper-theme >/dev/null 2>&1 || return 0\n    ( wallpaper-theme refresh "$1" >/dev/null 2>&1 & )\n}',
     'theme_refresh() {\n    command -v wallpaper-theme >/dev/null 2>&1 || return 0\n    if [[ "$1" == lock ]]; then\n        # Блокировка: сразу после этого hypridle запускает hyprlock. Даём пересчёту\n        # не больше 1,5 с (палитры библиотеки посчитаны заранее, обычно это доли\n        # секунды) — оформление никогда не задерживает блокировку экрана.\n        timeout 1.5 wallpaper-theme refresh lock >/dev/null 2>&1\n    else\n        ( wallpaper-theme refresh "$1" >/dev/null 2>&1 & )\n    fi\n}'),
    ('theme_refresh() {\n    command -v wallpaper-theme >/dev/null 2>&1 || return 0\n    if [[ "$1" == lock ]]; then\n        # Блокировка — не в фоне: hypridle сразу после смены картинки запускает\n        # hyprlock, и он успел бы прочитать цвета прошлой картинки (~0,5–1 с).\n        wallpaper-theme refresh lock >/dev/null 2>&1\n    else\n        ( wallpaper-theme refresh "$1" >/dev/null 2>&1 & )\n    fi\n}',
     'theme_refresh() {\n    command -v wallpaper-theme >/dev/null 2>&1 || return 0\n    if [[ "$1" == lock ]]; then\n        # Блокировка: сразу после этого hypridle запускает hyprlock. Даём пересчёту\n        # не больше 1,5 с (палитры библиотеки посчитаны заранее, обычно это доли\n        # секунды) — оформление никогда не задерживает блокировку экрана.\n        timeout 1.5 wallpaper-theme refresh lock >/dev/null 2>&1\n    else\n        ( wallpaper-theme refresh "$1" >/dev/null 2>&1 & )\n    fi\n}'),
    ('# Интерфейс под обои (wallpaper-theme): пересчитать цвета после смены картинки.\n# В фоне — чтобы не задерживать саму смену обоев; при выключенном режиме\n# команда сразу выходит. Нет программы — ничего не делаем.',
     '# Интерфейс под обои (wallpaper-theme): пересчитать цвета после смены картинки.\n# Рабочий стол — в фоне, чтобы не задерживать смену обоев; при выключенном режиме\n# команда сразу выходит. Нет программы — ничего не делаем.'),
]

def patch(path, pairs):
    if not path.is_file():
        print(f"   !! нет {path} — пропускаю")
        return
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        upgraded = text
        for old, new in UPGRADES:
            upgraded = upgraded.replace(old, new)
        if upgraded != text:
            path.write_text(upgraded, encoding="utf-8")
            print(f"   обновлено: {path.name}")
        else:
            print(f"   уже встроено: {path.name}")
        if path.name == "wallpaper.sh" and "timeout 1.5 wallpaper-theme refresh lock" not in upgraded:
            print("   !! wallpaper.sh: пересчёт перед блокировкой не ограничен по времени — "
                  "функция theme_refresh изменена вручную, обнови её по install.sh")
        return
    for anchor, replacement in pairs:
        if text.count(anchor) != 1:
            print(f"   !! {path.name}: не нашёл место для вставки — пропускаю файл целиком")
            return
    for anchor, replacement in pairs:
        text = text.replace(anchor, replacement, 1)
    path.write_text(text, encoding="utf-8")
    print(f"   встроено: {path.name}")

patch(scripts / "wallpaper.sh", [
    ('''# ---------- применение к каждой цели ----------
''', '''# ---------- применение к каждой цели ----------

# Интерфейс под обои (wallpaper-theme): пересчитать цвета после смены картинки.
# Рабочий стол — в фоне, чтобы не задерживать смену обоев; при выключенном режиме
# команда сразу выходит. Нет программы — ничего не делаем.
theme_refresh() {
    command -v wallpaper-theme >/dev/null 2>&1 || return 0
    if [[ "$1" == lock ]]; then
        # Блокировка: сразу после этого hypridle запускает hyprlock. Даём пересчёту
        # не больше 1,5 с (палитры библиотеки посчитаны заранее, обычно это доли
        # секунды) — оформление никогда не задерживает блокировку экрана.
        timeout 1.5 wallpaper-theme refresh lock >/dev/null 2>&1
    else
        ( wallpaper-theme refresh "$1" >/dev/null 2>&1 & )
    fi
}
'''),
    ('''    echo "$img" > "$STATE_DIR/desktop.path"
}''', '''    echo "$img" > "$STATE_DIR/desktop.path"
    theme_refresh desktop
}'''),
    ('''    echo "$img" > "$STATE_DIR/lock.path"
}''', '''    echo "$img" > "$STATE_DIR/lock.path"
    theme_refresh lock
}'''),
])

patch(scripts / "wallpaper-picker.sh", [
    ('''        "󰒝  Случайные обои      $(random_summary)" \\
        | rofi -dmenu -format i -p "Фон" \\
               -theme-str 'entry { placeholder: "Что меняем..."; } listview { lines: 5; }')''',
     '''        "󰒝  Случайные обои      $(random_summary)" \\
        "󰏘  Интерфейс под обои  $(theme_label)" \\
        | rofi -dmenu -format i -p "Фон" \\
               -theme-str 'entry { placeholder: "Что меняем..."; } listview { lines: 6; }')'''),
    ('''        4) echo random ;;
        *) return 1 ;;''', '''        4) echo random ;;
        5) echo theme ;;
        *) return 1 ;;'''),
    ('''# Строки для rofi: "подпись\\0icon\\x1fпуть-к-превью".''', '''# Интерфейс под обои (wallpaper-theme). Режим хранится у самой программы.
theme_mode() {
    command -v wallpaper-theme >/dev/null 2>&1 || { echo none; return; }
    wallpaper-theme status 2>/dev/null | sed -n 's/^режим: //p'
}

theme_label() {
    case "$(theme_mode)" in
        vivid)  echo "яркий" ;;
        tinted) echo "приглушённый" ;;
        none)   echo "не установлен" ;;
        *)      echo "выключен" ;;
    esac
}

# Меню не закрывается после выбора: так видно, что режим переключился.
choose_theme() {
    command -v wallpaper-theme >/dev/null 2>&1 || return 0
    local row=0 choice mode
    while true; do
        mode="$(theme_mode)"
        choice=$(printf '%s\\n' \\
            "$([[ $mode == off ]] && echo 󰄲 || echo 󰄱)  Выключен — Monochrome Vivid" \\
            "$([[ $mode == vivid ]] && echo 󰄲 || echo 󰄱)  Яркий — цвета из обоев" \\
            "$([[ $mode == tinted ]] && echo 󰄲 || echo 󰄱)  Приглушённый — чёрно-белое с оттенком обоев" \\
            | rofi -dmenu -format i -p "Интерфейс" -selected-row "$row" \\
                   -mesg "Enter — выбрать, Esc — назад. Панель перекрасится за несколько секунд, rofi — при следующем открытии, программы на GTK — после перезапуска." \\
                   -theme-str 'entry { placeholder: "Режим..."; } listview { lines: 3; }') || return 0
        [[ "$choice" =~ ^[0-9]+$ ]] || return 0
        row="$choice"
        case "$choice" in
            0) wallpaper-theme mode off ;;
            1) wallpaper-theme mode vivid ;;
            2) wallpaper-theme mode tinted ;;
        esac
    done
}

# Строки для rofi: "подпись\\0icon\\x1fпуть-к-превью".'''),
    ('''        random)  choose_random; continue ;;''', '''        random)  choose_random; continue ;;
        theme)   choose_theme; continue ;;'''),
])
PY
fi

if (( ! DRY )) && ! "$BIN" status 2>/dev/null | grep -q "^режим: off"; then
    # Обновление при включённом режиме: досчитать палитры новых обоев заранее,
    # иначе перед блокировкой на них не хватило бы отведённых 1,5 с.
    ( nice -n 19 "$BIN" warm >/dev/null 2>&1 & )
fi

echo
say "Готово. Режим сейчас: $("$BIN" status 2>/dev/null | head -1 || echo '?')"
echo "   Включить: SUPER+R → Обои → «Интерфейс под обои», или: wallpaper-theme mode vivid"
echo "   Резервные копии: $BACKUP"
