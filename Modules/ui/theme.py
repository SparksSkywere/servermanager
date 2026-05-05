import os
import sys
import tkinter as tk
from tkinter import ttk
import ctypes
from ctypes import wintypes

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import REGISTRY_PATH, get_registry_value, set_registry_value
from Modules.core.server_logging import get_component_logger
from Modules.ui.color_palettes import get_palette, list_themes

logger = get_component_logger("Theme")

# Default theme constant
LIGHT = "light"

def normalise_theme(theme_name: str) -> str:
	value = str(theme_name or "").strip().lower()
	available = set(list_themes())
	if value in available:
		return value
	return LIGHT

def _is_dark_palette(palette: dict) -> bool:
	# Estimate whether a palette is dark by checking background luminance.
	try:
		hex_color = str(palette.get("bg", "#f4f5f7")).lstrip("#")
		if len(hex_color) != 6:
			return False
		r = int(hex_color[0:2], 16)
		g = int(hex_color[2:4], 16)
		b = int(hex_color[4:6], 16)
		luminance = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
		return luminance < 140
	except Exception:
		return False

def _hex_to_rgb(hex_color: str):
	# Convert #RRGGBB to RGB tuple.
	try:
		hex_value = str(hex_color or "").strip().lstrip("#")
		if len(hex_value) != 6:
			return None
		return (int(hex_value[0:2], 16), int(hex_value[2:4], 16), int(hex_value[4:6], 16))
	except Exception:
		return None

def _relative_luminance(rgb):
	# WCAG relative luminance helper.
	def _channel(value):
		value = float(value) / 255.0
		if value <= 0.03928:
			return value / 12.92
		return ((value + 0.055) / 1.055) ** 2.4

	r, g, b = rgb
	return (0.2126 * _channel(r)) + (0.7152 * _channel(g)) + (0.0722 * _channel(b))

def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
	# Compute WCAG contrast ratio between two hex colours.
	fg_rgb = _hex_to_rgb(fg_hex)
	bg_rgb = _hex_to_rgb(bg_hex)
	if fg_rgb is None or bg_rgb is None:
		return 1.0

	fg_l = _relative_luminance(fg_rgb)
	bg_l = _relative_luminance(bg_rgb)
	lighter = max(fg_l, bg_l)
	darker = min(fg_l, bg_l)
	return (lighter + 0.05) / (darker + 0.05)

def _pick_accessible_caret_color(palette: dict) -> str:
	# Pick a caret colour that stays visible across text/entry backgrounds.
	backgrounds = [
		palette.get("text_bg", "#ffffff"),
		palette.get("field_bg", "#ffffff"),
		palette.get("panel_bg", "#ffffff"),
	]
	candidates = [
		palette.get("caret_fg", ""),
		palette.get("text_fg", ""),
		palette.get("fg", ""),
		palette.get("accent", ""),
		"#ffffff",
		"#000000",
	]

	best = "#000000"
	best_score = 0.0
	for candidate in candidates:
		if not _hex_to_rgb(candidate):
			continue
		# Maximise worst-case contrast across all typical input backgrounds.
		score = min(_contrast_ratio(candidate, bg) for bg in backgrounds)
		if score > best_score:
			best_score = score
			best = candidate

	return best

def get_theme_preference(default: str = LIGHT) -> str:
	# Prefer DB-configured theme, then registry fallback, then default.
	theme_value = None

	try:
		from Modules.Database.cluster_database import get_cluster_database

		db = get_cluster_database()
		main_cfg = db.get_main_config() or {}
		theme_value = main_cfg.get("theme")
	except Exception as e:
		logger.debug(f"Theme DB lookup failed: {e}")

	if not theme_value:
		try:
			theme_value = get_registry_value(REGISTRY_PATH, "Theme", default)
		except Exception as e:
			logger.debug(f"Theme registry lookup failed: {e}")

	return normalise_theme(theme_value or default)

def persist_theme_preference(theme_name: str, write_registry: bool = True) -> bool:
	# Store chosen theme in DB and optionally mirror to Windows registry.
	theme = normalise_theme(theme_name)
	ok = True

	try:
		from Modules.Database.cluster_database import get_cluster_database

		db = get_cluster_database()
		db.set_main_config("theme", theme, "string", "settings")
	except Exception as e:
		ok = False
		logger.warning(f"Failed to persist theme in main_config: {e}")

	if write_registry and os.name == 'nt':
		try:
			set_registry_value(REGISTRY_PATH, "Theme", theme)
		except Exception as e:
			ok = False
			logger.warning(f"Failed to persist theme in registry: {e}")

	return ok

def apply_theme(root: tk.Misc, theme_name: str, dpi_scale: float = 1.0) -> str:
	# Apply the selected theme style to ttk and baseline tk widgets for a given root.
	if root is None:
		return LIGHT

	theme = normalise_theme(theme_name)
	style = ttk.Style(root)

	# Get all colors from centralized palette
	palette = get_palette(theme)
	caret_color = _pick_accessible_caret_color(palette)
	try:
		caret_width = max(2, int(2 * float(dpi_scale or 1.0)))
	except Exception:
		caret_width = 2
	caret_on_time = 700
	caret_off_time = 350

	def _apply_windows_titlebar_theme(widget: tk.Misc, theme_str: str) -> None:
		# Use native Windows title bar theming when available.
		if os.name != "nt":
			return

		try:
			try:
				widget.update_idletasks()
			except Exception:
				pass

			hwnd = int(widget.winfo_id())
			if not hwnd:
				return

			try:
				parent_hwnd = int(ctypes.windll.user32.GetParent(wintypes.HWND(hwnd)))
				if parent_hwnd:
					hwnd = parent_hwnd
			except Exception:
				pass

			dwmapi = ctypes.windll.dwmapi
			titlebar_palette = get_palette(theme_str)
			value = ctypes.c_int(1 if _is_dark_palette(titlebar_palette) else 0)
			size = ctypes.sizeof(value)

			# Windows 10/11 use 20 or 19 depending on build.
			for attr in (20, 19):
				try:
					result = dwmapi.DwmSetWindowAttribute(
						wintypes.HWND(hwnd),
						ctypes.c_uint(attr),
						ctypes.byref(value),
						ctypes.c_uint(size),
					)
					if result == 0:
						break
				except Exception:
					continue

			# Best effort: set titlebar colors on newer Windows builds.
			def _rgb_to_colorref(hex_color: str) -> int:
				hex_value = str(hex_color).lstrip("#")
				if len(hex_value) != 6:
					return 0
				r = int(hex_value[0:2], 16)
				g = int(hex_value[2:4], 16)
				b = int(hex_value[4:6], 16)
				return (b << 16) | (g << 8) | r

			caption_color = ctypes.c_uint(_rgb_to_colorref(palette.get("titlebar_bg", "#ffffff")))
			text_color = ctypes.c_uint(_rgb_to_colorref(palette.get("titlebar_fg", "#000000")))
			border_color = ctypes.c_uint(_rgb_to_colorref(palette.get("border", "#cccccc")))

			color_size = ctypes.sizeof(caption_color)
			for attr, color_value in ((35, caption_color), (36, text_color), (34, border_color)):
				try:
					dwmapi.DwmSetWindowAttribute(
						wintypes.HWND(hwnd),
						ctypes.c_uint(attr),
						ctypes.byref(color_value),
						ctypes.c_uint(color_size),
					)
				except Exception:
					continue
		except Exception:
			pass

	def _apply_palette_to_existing_widgets(widget: tk.Misc, theme_str: str) -> None:
		# Ensure already-created tk widgets match active theme using palette.
		try:
			klass = str(widget.winfo_class() or "")

			if klass == "Text":
				widget.configure(
					bg=palette.get("text_bg"),
					fg=palette.get("text_fg"),
					insertbackground=caret_color,
					insertwidth=caret_width,
					insertontime=caret_on_time,
					insertofftime=caret_off_time,
					selectbackground=palette.get("text_selection_bg"),
					selectforeground=palette.get("text_selection_fg"),
					highlightbackground=palette.get("border"),
					highlightcolor=palette.get("border"),
				)
			elif klass == "Canvas":
				widget.configure(bg=palette.get("canvas_bg"), highlightbackground=palette.get("canvas_bg"), highlightcolor=palette.get("canvas_bg"))
			elif klass == "Listbox":
				widget.configure(
					bg=palette.get("listbox_bg"),
					fg=palette.get("listbox_fg"),
					selectbackground=palette.get("listbox_selection_bg"),
					selectforeground=palette.get("listbox_selection_fg"),
					highlightbackground=palette.get("border"),
					highlightcolor=palette.get("border"),
				)
			elif klass == "Menu":
				widget.configure(
					bg=palette.get("menu_bg"),
					fg=palette.get("menu_fg"),
					activebackground=palette.get("menu_active_bg"),
					activeforeground=palette.get("menu_active_fg"),
				)
			elif klass == "Frame":
				widget.configure(bg=palette.get("bg"))
			elif klass == "Button":
				widget.configure(
					bg=palette.get("button_bg"),
					fg=palette.get("button_fg"),
					activebackground=palette.get("button_active_bg"),
					activeforeground=palette.get("button_active_fg"),
				)
			elif klass in ("Menubutton", "TMenubutton"):
				widget.configure(
					bg=palette.get("button_bg"),
					fg=palette.get("button_fg"),
					activebackground=palette.get("button_active_bg"),
					activeforeground=palette.get("button_active_fg"),
					highlightbackground=palette.get("border"),
					highlightcolor=palette.get("border"),
				)
				try:
					menu_name = widget.cget("menu")
					if menu_name:
						linked_menu = widget.nametowidget(menu_name)
						linked_menu.configure(
							bg=palette.get("menu_bg"),
							fg=palette.get("menu_fg"),
							activebackground=palette.get("menu_active_bg"),
							activeforeground=palette.get("menu_active_fg"),
						)
				except Exception:
					pass
			elif klass in ("Entry", "TEntry", "Spinbox", "TSpinbox"):
				# Apply insertion cursor colour explicitly so caret remains visible
				# on dark field backgrounds for both tk and ttk entry-like widgets.
				widget_keys = set(widget.keys())
				entry_cfg = {}
				if "bg" in widget_keys:
					entry_cfg["bg"] = palette.get("field_bg")
				if "fieldbackground" in widget_keys:
					entry_cfg["fieldbackground"] = palette.get("field_bg")
				if "fg" in widget_keys:
					entry_cfg["fg"] = palette.get("fg")
				if "foreground" in widget_keys:
					entry_cfg["foreground"] = palette.get("fg")
				if "insertbackground" in widget_keys:
					entry_cfg["insertbackground"] = caret_color
				if "insertcolor" in widget_keys:
					entry_cfg["insertcolor"] = caret_color
				if "insertwidth" in widget_keys:
					entry_cfg["insertwidth"] = caret_width
				if "insertontime" in widget_keys:
					entry_cfg["insertontime"] = caret_on_time
				if "insertofftime" in widget_keys:
					entry_cfg["insertofftime"] = caret_off_time
				if "disabledbackground" in widget_keys:
					entry_cfg["disabledbackground"] = palette.get("field_bg")
				if "disabledforeground" in widget_keys:
					entry_cfg["disabledforeground"] = palette.get("fg")
				if "highlightbackground" in widget_keys:
					entry_cfg["highlightbackground"] = palette.get("border")
				if "highlightcolor" in widget_keys:
					entry_cfg["highlightcolor"] = palette.get("border")
				if "relief" in widget_keys:
					entry_cfg["relief"] = tk.SOLID
				if "bd" in widget_keys:
					entry_cfg["bd"] = 1

				if entry_cfg:
					widget.configure(**entry_cfg)
			elif klass == "TCombobox":
				_theme_combobox_popdown(widget)
			elif klass == "Label":
				widget.configure(bg=palette.get("bg"), fg=palette.get("fg"))
			elif klass == "PanedWindow":
				widget.configure(
					bg=palette.get("bg"),
					sashwidth=max(8, _scaled(8)),
					sashrelief=tk.FLAT,
					showhandle=False,
				)
		except Exception:
			pass

		for child in widget.winfo_children():
			_apply_palette_to_existing_widgets(child, theme_str)

	def _theme_all_menus(widget: tk.Misc, theme_str: str) -> None:
		# Recursively find and theme all tk.Menu objects in the hierarchy.
		try:
			try:
				menubar = widget.nametowidget(widget.cget('menu'))
				if menubar:
					menubar.configure(
						bg=palette.get("menu_bg"),
						fg=palette.get("menu_fg"),
						activebackground=palette.get("menu_active_bg"),
						activeforeground=palette.get("menu_active_fg")
					)
					try:
						for idx in range(int(menubar.index("end")) + 1):
							try:
								submenu = menubar.nametowidget(menubar.entryconfig(idx, "menu")[4])
								if submenu:
									submenu.configure(
										bg=palette.get("menu_bg"),
										fg=palette.get("menu_fg"),
										activebackground=palette.get("menu_active_bg"),
										activeforeground=palette.get("menu_active_fg")
									)
							except Exception:
								pass
					except Exception:
						pass
			except Exception:
				pass
		except Exception:
			pass

		try:
			for child in widget.winfo_children():
				_theme_all_menus(child, theme_str)
		except Exception:
			pass

	def _theme_all_toplevels(widget: tk.Misc, theme_str: str) -> None:
		# Recursively find and theme all Toplevel windows.
		try:
			if isinstance(widget, tk.Toplevel):
				widget.configure(
					bg=palette.get("bg"),
					highlightbackground=palette.get("border"),
					highlightcolor=palette.get("border")
				)

			for child in widget.winfo_children():
				_theme_all_toplevels(child, theme_str)
		except Exception:
			pass

	def _theme_combobox_popdown(widget: tk.Misc) -> None:
		# Force ttk.Combobox popup list colors; some Windows builds ignore ttk style here.
		try:
			if str(widget.winfo_class() or "") != "TCombobox":
				return

			popdown = widget.tk.call("ttk::combobox::PopdownWindow", str(widget))
			if not popdown:
				return

			listbox_path = f"{popdown}.f.l"
			widget.tk.call(
				listbox_path,
				"configure",
				"-background", palette.get("listbox_bg"),
				"-foreground", palette.get("listbox_fg"),
				"-selectbackground", palette.get("listbox_selection_bg"),
				"-selectforeground", palette.get("listbox_selection_fg"),
				"-highlightbackground", palette.get("border"),
				"-highlightcolor", palette.get("border"),
			)
		except Exception:
			pass

	def _scaled(value: int) -> int:
		try:
			return max(1, int(value * float(dpi_scale or 1.0)))
		except Exception:
			return value

	is_dark = _is_dark_palette(palette)
	if theme in ("blue", "green"):
		preferred = None
		for candidate in ("xpnative", "vista", "default", "clam"):
			if candidate in style.theme_names():
				preferred = candidate
				break
		if preferred:
			style.theme_use(preferred)
	elif theme == "classic":
		preferred = None
		for candidate in ("xpnative", "default", "vista", "clam"):
			if candidate in style.theme_names():
				preferred = candidate
				break
		if preferred:
			style.theme_use(preferred)
	elif is_dark:
		if "clam" in style.theme_names():
			style.theme_use("clam")
	else:
		preferred = None
		for candidate in ("vista", "xpnative", "default", "clam"):
			if candidate in style.theme_names():
				preferred = candidate
				break
		if preferred:
			style.theme_use(preferred)

	try:
		root.configure(bg=palette.get("bg"), highlightbackground=palette.get("border"), highlightcolor=palette.get("border"))
	except Exception:
		pass

	style.configure(".", background=palette.get("bg"), foreground=palette.get("fg"), borderwidth=0)
	style.configure("TFrame", background=palette.get("bg"), borderwidth=0, relief="flat")
	style.configure("TLabelframe", background=palette.get("bg"), foreground=palette.get("fg"), borderwidth=1, relief="solid")
	style.configure("TLabelframe.Label", background=palette.get("bg"), foreground=palette.get("fg"))
	style.configure("TLabel", background=palette.get("bg"), foreground=palette.get("fg"))
	style.configure("TButton", background=palette.get("button_bg"), foreground=palette.get("button_fg"), padding=(_scaled(10), _scaled(6)), relief="flat", borderwidth=0)
	style.map(
		"TButton",
		background=[("active", palette.get("button_active_bg")), ("pressed", palette.get("heading_bg"))],
		foreground=[("active", palette.get("button_active_fg")), ("pressed", palette.get("button_active_fg"))],
	)
	style.configure("TCheckbutton", background=palette.get("bg"), foreground=palette.get("fg"), relief="flat", borderwidth=0)
	style.configure("TRadiobutton", background=palette.get("bg"), foreground=palette.get("fg"), relief="flat", borderwidth=0)
	style.configure(
		"TMenubutton",
		background=palette.get("button_bg"),
		foreground=palette.get("button_fg"),
		relief="flat",
		borderwidth=1,
		lightcolor=palette.get("border"),
		darkcolor=palette.get("border"),
	)
	style.map(
		"TMenubutton",
		background=[("active", palette.get("button_active_bg")), ("pressed", palette.get("button_active_bg"))],
		foreground=[("active", palette.get("button_active_fg")), ("pressed", palette.get("button_active_fg"))],
	)
	style.configure(
		"TEntry",
		fieldbackground=palette.get("field_bg"),
		foreground=palette.get("fg"),
		relief="solid",
		borderwidth=1,
		lightcolor=palette.get("border"),
		darkcolor=palette.get("border"),
	)
	style.configure(
		"TCombobox",
		fieldbackground=palette.get("field_bg"),
		foreground=palette.get("fg"),
		padding=(_scaled(6), _scaled(4)),
		relief="solid",
		borderwidth=1,
		lightcolor=palette.get("border"),
		darkcolor=palette.get("border"),
	)
	style.map("TCombobox", fieldbackground=[("readonly", palette.get("field_bg"))], foreground=[("readonly", palette.get("fg"))], background=[("active", palette.get("button_active_bg"))])
	style.configure("TCombobox.Listbox", background=palette.get("field_bg"), foreground=palette.get("fg"), relief="solid", borderwidth=1, lightcolor=palette.get("border"), darkcolor=palette.get("border"))
	style.configure(
		"TProgressbar",
		background=palette.get("success_fg"),
		troughcolor=palette.get("field_bg"),
		bordercolor=palette.get("border"),
		lightcolor=palette.get("success_fg"),
		darkcolor=palette.get("success_fg"),
	)
	style.map("TProgressbar", background=[("!disabled", palette.get("success_fg"))])
	style.configure("TNotebook", background=palette.get("bg"), borderwidth=1, lightcolor=palette.get("border"), darkcolor=palette.get("border"))
	style.configure("TNotebook.Tab", background=palette.get("panel_bg"), foreground=palette.get("fg"), padding=(_scaled(10), _scaled(6)), borderwidth=0)
	style.map("TNotebook.Tab", background=[("selected", palette.get("heading_bg")), ("active", palette.get("button_active_bg"))], foreground=[("selected", palette.get("fg")), ("active", palette.get("fg"))])
	style.configure("TPanedwindow", background=palette.get("bg"), sashrelief="flat")
	style.configure("TSeparator", background=palette.get("border"))
	style.configure("Vertical.TScrollbar", background=palette.get("panel_bg"), troughcolor=palette.get("bg"), arrowcolor=palette.get("fg"), bordercolor=palette.get("border"), lightcolor=palette.get("panel_bg"), darkcolor=palette.get("panel_bg"))
	style.configure("Horizontal.TScrollbar", background=palette.get("panel_bg"), troughcolor=palette.get("bg"), arrowcolor=palette.get("fg"), bordercolor=palette.get("border"), lightcolor=palette.get("panel_bg"), darkcolor=palette.get("panel_bg"))
	style.configure(
		"Treeview",
		background=palette.get("panel_bg"),
		fieldbackground=palette.get("panel_bg"),
		foreground=palette.get("fg"),
		rowheight=max(24, _scaled(24)),
		borderwidth=1,
		relief="solid",
		bordercolor=palette.get("tree_separator", palette.get("border")),
		lightcolor=palette.get("tree_separator", palette.get("border")),
		darkcolor=palette.get("tree_separator", palette.get("border")),
	)
	style.configure(
		"Treeview.Heading",
		background=palette.get("tree_heading_bg", palette.get("heading_bg")),
		foreground=palette.get("fg"),
		borderwidth=1,
		relief="solid",
		padding=(_scaled(8), _scaled(6)),
		bordercolor=palette.get("tree_separator", palette.get("border")),
		lightcolor=palette.get("tree_separator", palette.get("border")),
		darkcolor=palette.get("tree_separator", palette.get("border")),
	)
	style.map(
		"Treeview.Heading",
		background=[
			("active", palette.get("tree_heading_active_bg", palette.get("button_active_bg"))),
			("pressed", palette.get("tree_heading_active_bg", palette.get("button_active_bg"))),
		],
		foreground=[("active", palette.get("fg")), ("pressed", palette.get("fg"))],
	)
	selection_fg = "#ffffff" if is_dark else palette.get("fg")
	style.map("Treeview", background=[("selected", palette.get("accent"))], foreground=[("selected", selection_fg)])

	root.option_add("*Text.Background", palette.get("text_bg"), "interactive")
	root.option_add("*Text.Foreground", palette.get("text_fg"), "interactive")
	root.option_add("*Text.SelectBackground", palette.get("text_selection_bg"), "interactive")
	root.option_add("*Text.SelectForeground", palette.get("text_selection_fg"), "interactive")
	root.option_add("*Text.Relief", "solid", "interactive")
	root.option_add("*Text.BorderWidth", "1", "interactive")
	root.option_add("*Canvas.Background", palette.get("canvas_bg"), "interactive")
	root.option_add("*Canvas.Highlightthickness", "0", "interactive")
	root.option_add("*Menu.Background", palette.get("menu_bg"), "interactive")
	root.option_add("*Menu.Foreground", palette.get("menu_fg"), "interactive")
	root.option_add("*Menu.ActiveBackground", palette.get("menu_active_bg"), "interactive")
	root.option_add("*Menu.ActiveForeground", palette.get("menu_active_fg"), "interactive")
	root.option_add("*Menubutton.Background", palette.get("button_bg"), "interactive")
	root.option_add("*Menubutton.Foreground", palette.get("button_fg"), "interactive")
	root.option_add("*Menubutton.ActiveBackground", palette.get("button_active_bg"), "interactive")
	root.option_add("*Menubutton.ActiveForeground", palette.get("button_active_fg"), "interactive")
	root.option_add("*Menubutton.HighlightBackground", palette.get("border"), "interactive")
	root.option_add("*Menubutton.HighlightColor", palette.get("border"), "interactive")
	root.option_add("*Listbox.Background", palette.get("listbox_bg"), "interactive")
	root.option_add("*Listbox.Foreground", palette.get("listbox_fg"), "interactive")
	root.option_add("*Listbox.SelectBackground", palette.get("listbox_selection_bg"), "interactive")
	root.option_add("*Listbox.SelectForeground", palette.get("listbox_selection_fg"), "interactive")
	root.option_add("*TCombobox*Listbox.background", palette.get("listbox_bg"), "interactive")
	root.option_add("*TCombobox*Listbox.foreground", palette.get("listbox_fg"), "interactive")
	root.option_add("*TCombobox*Listbox.selectBackground", palette.get("listbox_selection_bg"), "interactive")
	root.option_add("*TCombobox*Listbox.selectForeground", palette.get("listbox_selection_fg"), "interactive")
	root.option_add("*Panedwindow.Background", palette.get("bg"), "interactive")
	root.option_add("*insertBackground", caret_color, "interactive")
	root.option_add("*insertWidth", str(caret_width), "interactive")
	root.option_add("*insertOnTime", str(caret_on_time), "interactive")
	root.option_add("*insertOffTime", str(caret_off_time), "interactive")
	root.option_add("*Entry.insertBackground", caret_color, "interactive")
	root.option_add("*Entry.insertWidth", str(caret_width), "interactive")
	root.option_add("*Entry.insertOnTime", str(caret_on_time), "interactive")
	root.option_add("*Entry.insertOffTime", str(caret_off_time), "interactive")
	root.option_add("*TEntry.insertBackground", caret_color, "interactive")
	root.option_add("*TEntry.insertWidth", str(caret_width), "interactive")
	root.option_add("*TEntry.insertOnTime", str(caret_on_time), "interactive")
	root.option_add("*TEntry.insertOffTime", str(caret_off_time), "interactive")
	root.option_add("*Spinbox.insertBackground", caret_color, "interactive")
	root.option_add("*Spinbox.insertWidth", str(caret_width), "interactive")
	root.option_add("*Spinbox.insertOnTime", str(caret_on_time), "interactive")
	root.option_add("*Spinbox.insertOffTime", str(caret_off_time), "interactive")

	try:
		_apply_palette_to_existing_widgets(root, theme)
	except Exception:
		pass

	# Flush pending redraws so the newly-applied bg/fg values are painted
	try:
		root.update_idletasks()
	except Exception:
		pass

	try:
		_theme_all_menus(root, theme)
	except Exception:
		pass

	try:
		_theme_all_toplevels(root, theme)
	except Exception:
		pass

	try:
		_apply_windows_titlebar_theme(root, theme)
		for child in root.winfo_children():
			if isinstance(child, tk.Toplevel):
				_apply_windows_titlebar_theme(child, theme)
	except Exception:
		pass

	if os.name == "nt":
		try:
			root.after(120, lambda: _apply_windows_titlebar_theme(root, theme))
			for child in root.winfo_children():
				if isinstance(child, tk.Toplevel):
					root.after(140, lambda w=child: _apply_windows_titlebar_theme(w, theme))
		except Exception:
			pass

	return theme