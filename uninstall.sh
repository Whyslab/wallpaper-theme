#!/usr/bin/env bash
# uninstall.sh — убрать «интерфейс под обои».
#
# 1. Выключает режим (панель, рамки, kitty возвращаются к Monochrome Vivid).
# 2. Убирает строки подключения из конфигов и блоки из gtk.css.
# 3. Удаляет программу и команду.
#
# Встроенные в wallpaper.sh и wallpaper-picker.sh куски остаются, но без
# программы ничего не делают (проверяют `command -v wallpaper-theme`, а пункт
# меню пишет «не установлен»). Вернуть сами скрипты дословно — из резервной
# копии, которую сделал install.sh:
#   ~/.local/share/repo-backups/wallpaper-theme-before-install-*/.config/hypr/scripts/

set -uo pipefail
BIN="$HOME/.local/bin/wallpaper-theme"
if [[ -x "$BIN" ]]; then
    "$BIN" mode off || true
    "$BIN" unintegrate || true
fi
rm -f "$BIN"
rm -rf "$HOME/.local/share/wallpaper-theme"
echo "Удалено. Настройки режима: ~/.config/wallpaper-theme, сгенерированные файлы: ~/.cache/wallpaper-theme — можно удалить вручную."
