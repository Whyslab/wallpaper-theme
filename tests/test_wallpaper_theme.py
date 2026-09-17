"""
Что здесь важно проверить — то, что ломает систему незаметно:

  * выключение возвращает все файлы побайтно, а отключение — к состоянию до установки;
  * повторный integrate ничего не дублирует;
  * подключение hyprlock стоит сразу после colors.conf, до использования переменных;
  * у колец блокировки сохраняется своя прозрачность — уровни различаются яркостью;
  * у панели при выключении остаются её собственные цвета.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wallpaper_theme as wt  # noqa: E402

PALETTE = {
    "primary": "#adc6ff", "on_primary": "#002e69", "surface": "#0f131c",
    "surface_container_lowest": "#0a0e17", "surface_container": "#1b1f28",
    "surface_container_high": "#262a33", "on_surface": "#dfe2ef",
    "on_surface_variant": "#c3c6d3", "outline": "#8d909c", "outline_variant": "#434651",
}

MATUGEN_JSON = json.dumps({
    "colors": {role: {"dark": {"color": value.upper()}, "default": {"color": "#000000"},
                      "light": {"color": "#ffffff"}} for role, value in PALETTE.items()},
})

COLORS_CONF = """# палитра
$font = JetBrainsMono Nerd Font
$c_black        = rgba(10, 10, 10, 1.0)
$c_panel        = rgba(18, 18, 20, 0.55)
$c_panel_border = rgba(255, 255, 255, 0.12)
$c_white       = rgba(240, 240, 242, 1.0)
$c_grey_mid    = rgba(165, 165, 169, 0.80)
$c_idle_ring  = rgba(255, 255, 255, 0.20)
$c_fail_ring  = rgba(255, 255, 255, 1.0)
"""


def test_parse_matugen_takes_the_dark_scheme():
    assert wt.parse_matugen(MATUGEN_JSON) == PALETTE


@pytest.mark.parametrize("render", [wt.render_hyprland, wt.render_kitty, wt.render_rofi])
def test_off_renders_a_file_that_sets_nothing(render):
    text = render(None)
    assert text.strip().startswith(("#", "/*"))
    assert len(text.strip().splitlines()) == 1


def test_hyprland_borders_use_primary_and_outline_variant():
    text = wt.render_hyprland(PALETTE)
    assert "col.active_border = rgba(adc6ffff)" in text
    assert "col.inactive_border = rgba(434651ff)" in text


def test_kitty_leaves_the_sixteen_terminal_colours_alone():
    text = wt.render_kitty(PALETTE)
    assert "color0" not in text and "color1 " not in text
    assert "background #0a0e17" in text


def test_rofi_sets_both_naming_schemes():
    text = wt.render_rofi(PALETTE)
    for name in ("bg:", "bg-element:", "accent:", "bg-base:", "bg-selected:", "fg-secondary:"):
        assert name in text


def test_hyprlock_keeps_each_variables_own_alpha():
    text = wt.render_hyprlock(PALETTE, COLORS_CONF)
    assert "$c_idle_ring = rgba(173, 198, 255, 0.20)" in text
    assert "$c_fail_ring = rgba(173, 198, 255, 1.0)" in text
    assert "$c_panel = rgba(27, 31, 40, 0.55)" in text
    assert "$font" not in text


def test_gtk_block_replaces_itself_and_stays_single():
    css = "@define-color window_bg_color #000000;\n"
    once = wt.replace_gtk_block(css, PALETTE)
    twice = wt.replace_gtk_block(once, PALETTE)
    assert once == twice
    assert once.count(wt.GTK_START) == 1
    assert once.index("@define-color window_bg_color #000000") < once.index(wt.GTK_START)
    off = wt.replace_gtk_block(once, None)
    assert "#0a0e17" not in off and off.count(wt.GTK_START) == 1


def test_gtk_block_strip_restores_the_original():
    css = "@define-color a #000;\n/* comment */\n"
    assert wt.strip_gtk_block(wt.replace_gtk_block(css, PALETTE)) == css


def test_panel_off_only_flips_the_switch():
    config = {"theme.bar.background": "#000000", "theme.matugen": True,
              "wallpaper.image": "/x.png", "theme.matugen_settings.scheme_type": "vibrant"}
    off = wt.set_hyprpanel(config, "off", "/y.png")
    assert off["theme.matugen"] is False
    assert off["theme.bar.background"] == "#000000"
    on = wt.set_hyprpanel(config, "tinted", "/y.png")
    assert on["theme.matugen_settings.scheme_type"] == "neutral"
    assert on["wallpaper.image"] == "/y.png"


def test_add_hook_is_idempotent_and_removable():
    text = "general {\n}\n"
    line = wt.hook_line("hyprland", Path("/tmp/wt"))
    once = wt.add_hook(text, line)
    assert wt.add_hook(once, line) == once
    assert wt.remove_hook(once) == text


def test_hyprlock_hook_goes_right_after_colors():
    text = "source = ~/.config/hypr/colors.conf\n\nbackground {\n    color = $c_black\n}\n"
    line = wt.hook_line("hyprlock", Path("/tmp/wt"))
    out = wt.add_hook(text, line, after=r"^source\s*=.*colors\.conf.*$")
    lines = out.splitlines()
    assert lines[1] == line
    assert out.index(line) < out.index("$c_black")


def test_kitty_hook_has_no_inline_comment_and_is_still_removable():
    line = wt.hook_line("kitty", Path("/home/u/.cache/wallpaper-theme"))
    assert "#" not in line
    assert wt.MARK in line
    assert wt.remove_hook("font_size 12\n" + line + "\n") == "font_size 12\n"


def test_hyprlock_hook_refuses_to_guess():
    with pytest.raises(wt.ThemeError):
        wt.add_hook("background {}\n", "x", after=r"^source\s*=.*colors\.conf.*$")


# ─────────────────────────── на временном домашнем каталоге ───────────────────────────

@pytest.fixture
def home(tmp_path, monkeypatch):
    files = {
        ".config/hypr/hyprland.conf": "general {\n    border_size = 2\n}\n",
        ".config/hypr/hyprlock.conf": (
            "source = ~/.config/hypr/colors.conf\nlabel {\n    color = $c_white\n}\n"
        ),
        ".config/hypr/colors.conf": COLORS_CONF,
        ".config/kitty/kitty.conf": "background #0a0a0a\n",
        ".config/hyprpanel/config.json": json.dumps({"theme.matugen": False, "theme.bar.background": "#000"}),
        ".config/gtk-3.0/gtk.css": "@define-color window_bg_color #000000;\n",
        ".config/gtk-4.0/gtk.css": "@define-color window_bg_color #000000;\n/* gtk4 */\n",
        ".config/rofi/config.rasi": "* { bg: #0a0a0a; }\n",
        ".local/share/rofi-launcher/themes/hub.rasi": "* { bg-base: #0a0a0a; }\n",
        ".local/state/hypr-wallpaper/desktop.path": str(tmp_path / "wall.png"),
        ".local/state/hypr-wallpaper/lock.path": str(tmp_path / "wall.png"),
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / "wall.png").write_bytes(b"not really a png")

    def at(*parts):
        return tmp_path.joinpath(*parts)

    monkeypatch.setattr(wt, "CONFIG_DIR", at(".config", "wallpaper-theme"))
    monkeypatch.setattr(wt, "MODE_FILE", at(".config", "wallpaper-theme", "mode"))
    monkeypatch.setattr(wt, "OUT_DIR", at(".cache", "wallpaper-theme"))
    monkeypatch.setattr(wt, "WALLPAPER_STATE", at(".local", "state", "hypr-wallpaper"))
    monkeypatch.setattr(wt, "HYPRLAND_CONF", at(".config", "hypr", "hyprland.conf"))
    monkeypatch.setattr(wt, "HYPRLOCK_CONF", at(".config", "hypr", "hyprlock.conf"))
    monkeypatch.setattr(wt, "HYPRLOCK_COLORS", at(".config", "hypr", "colors.conf"))
    monkeypatch.setattr(wt, "KITTY_CONF", at(".config", "kitty", "kitty.conf"))
    monkeypatch.setattr(wt, "HYPRPANEL_CONF", at(".config", "hyprpanel", "config.json"))
    monkeypatch.setattr(wt, "GTK_CSS", (at(".config", "gtk-3.0", "gtk.css"),
                                        at(".config", "gtk-4.0", "gtk.css")))
    monkeypatch.setattr(wt, "ROFI_THEMES", (at(".config", "rofi", "config.rasi"),
                                            at(".config", "rofi", "wallpaper.rasi"),
                                            at(".local", "share", "rofi-launcher", "themes", "hub.rasi")))
    calls = []
    monkeypatch.setattr(wt, "_run", lambda *cmd: calls.append(cmd) or type("R", (), {"stdout": ""})())
    monkeypatch.setattr(wt, "palette_from_image", lambda image, mode: dict(PALETTE))
    monkeypatch.setattr(wt, "notify", lambda text: calls.append(("notify", text)))
    return tmp_path, files, calls


def _snapshot(root, files):
    return {rel: (root / rel).read_text(encoding="utf-8") for rel in files}


def test_integrate_twice_changes_nothing_the_second_time(home):
    root, files, _ = home
    wt.integrate()
    first = _snapshot(root, files)
    wt.integrate()
    assert _snapshot(root, files) == first
    assert (root / ".cache/wallpaper-theme/hyprland.conf").is_file()


def test_on_then_off_restores_every_config_byte_for_byte(home):
    root, files, _ = home
    wt.integrate()
    integrated = _snapshot(root, files)
    wt.set_mode("vivid")
    on = _snapshot(root, files)
    assert "adc6ff" in (root / ".cache/wallpaper-theme/rofi.rasi").read_text()
    assert json.loads(on[".config/hyprpanel/config.json"])["theme.matugen"] is True
    assert "#0a0e17" in on[".config/gtk-3.0/gtk.css"]
    wt.set_mode("off")
    off = _snapshot(root, files)
    for rel in files:
        if rel.endswith("config.json"):
            continue  # панель: переключатель выключен, остальное сравнивается ниже
        assert off[rel] == integrated[rel], rel
    panel = json.loads(off[".config/hyprpanel/config.json"])
    assert panel["theme.matugen"] is False and panel["theme.bar.background"] == "#000"
    assert "adc6ff" not in (root / ".cache/wallpaper-theme/rofi.rasi").read_text()


def test_unintegrate_returns_to_before_install(home):
    root, files, _ = home
    before = _snapshot(root, files)
    wt.integrate()
    wt.set_mode("tinted")
    wt.set_mode("off")
    wt.unintegrate()
    after = _snapshot(root, files)
    for rel in files:
        if rel.endswith("config.json"):
            continue
        assert after[rel] == before[rel], rel


def test_a_failed_palette_leaves_the_last_good_theme(home, monkeypatch):
    root, _, calls = home
    wt.integrate()
    wt.set_mode("vivid")
    good = (root / ".cache/wallpaper-theme/rofi.rasi").read_text()

    def broken(image, mode):
        raise wt.ThemeError("matugen не смог")
    monkeypatch.setattr(wt, "palette_from_image", broken)
    problems = wt.refresh("all")
    assert problems
    assert (root / ".cache/wallpaper-theme/rofi.rasi").read_text() == good


def test_off_reloads_hyprland_and_on_sets_borders_live(home):
    _, _, calls = home
    wt.integrate()
    wt.set_mode("vivid")
    assert ("hyprctl", "keyword", "general:col.active_border", "rgba(adc6ffff)") in calls
    wt.set_mode("off")
    assert ("hyprctl", "reload") in calls


def test_unknown_mode_is_refused(home):
    with pytest.raises(wt.ThemeError):
        wt.set_mode("purple")


def test_mode_file_junk_means_off(home):
    root, _, _ = home
    (root / ".config/wallpaper-theme").mkdir(parents=True, exist_ok=True)
    (root / ".config/wallpaper-theme/mode").write_text("rainbow\n")
    assert wt.read_mode() == "off"
