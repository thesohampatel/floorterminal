"""Password-protected, touch-friendly production configuration editor."""

from __future__ import annotations

import queue
import re
import string
import threading
import tkinter as tk
from copy import deepcopy
from tkinter import ttk

from ..core.config import (
    COLORBLIND_SAFE_COLORS,
    STATION_FAILURE_FALLBACK,
    ConfigurationError,
    validate_config,
    validate_station_failures,
    write_config,
)
from ..i18n import available_languages, load_translator
from ..integration import (
    CONNECTOR_FILE,
    DefinitionError,
    basic_diagnostic_connector,
    discover_connectors,
    select_connector,
    test_connector,
    write_connector,
)
from ..storage.audit import ActivityLogger
from ..update import trust as update_trust
from .responsive import design_scale, fitted_window_geometry

UI_LANGUAGE_CONFIG_KEY = "ui_language"


class SettingsWindow:
    COLOR_KEYS = (
        "background",
        "card",
        "text",
        "muted",
        "red",
        "green",
        "blue",
        "orange",
        "purple",
        "border",
    )

    def __init__(self, app, directory):
        self.app = app
        self.t = app.t
        self.directory = directory or {"teams": [], "conversations": []}
        screen_width, screen_height = (
            app.root.winfo_screenwidth(),
            app.root.winfo_screenheight(),
        )
        width, height, x, y = fitted_window_geometry(
            screen_width, screen_height, 0.96, 0.88
        )
        responsive_scale = design_scale(width, height, 980, 650)
        self.viewport_width, self.compact = width, responsive_scale < 0.8
        self.scale = max(0.7, min(1.6, responsive_scale))
        self.current_station = None
        self.stations = [
            {
                "name": zone,
                "failures": list(
                    app.config["station_failure_types"].get(
                        zone, STATION_FAILURE_FALLBACK
                    )
                ),
            }
            for zone in app.config.get("zones", [])
        ]
        self.win = tk.Toplevel(app.root)
        self.win.title(f"{app.project_profile.product_short_name} Settings")
        self.win.configure(bg=app.BG)
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.transient(app.root)
        self.win.grab_set()
        self.font = lambda size, weight="normal": (
            "Helvetica",
            max(8, round(size * self.scale)),
            weight,
        )
        self.vars = {}
        self.texts = {}
        self.error = tk.StringVar()
        app.connector_inventory = discover_connectors()
        self._styles()
        self._build()

    def _styles(self):
        style = ttk.Style(self.win)
        style.configure("Settings.TNotebook", background=self.app.BG, borderwidth=0)
        style.configure(
            "Settings.TNotebook.Tab", font=self.font(9, "bold"), padding=(14, 9)
        )
        style.configure("Settings.TCombobox", font=self.font(10), padding=5)

    def _build(self):
        header = tk.Frame(self.win, bg=self.app.BG)
        header.pack(fill="x", padx=20, pady=(14, 6))
        tk.Label(
            header,
            text=self.t("settings_title"),
            font=self.font(19, "bold"),
            fg=self.app.TEXT,
            bg=self.app.BG,
        ).pack(side="left")
        if not self.compact:
            tk.Label(
                header,
                text=self.t("settings_validation"),
                font=self.font(9),
                fg=self.app.MUTED,
                bg=self.app.BG,
            ).pack(side="right", pady=7)
        self.tabs = ttk.Notebook(self.win, style="Settings.TNotebook")
        self.tabs.pack(fill="both", expand=True, padx=18)
        self._general_tab()
        self._integration_tab()
        self._stations_tab()
        self._messages_tab()
        self._system_tab()
        self._appearance_tab()
        footer = tk.Frame(self.win, bg=self.app.BG)
        footer.pack(fill="x", padx=20, pady=12)
        tk.Label(
            footer,
            textvariable=self.error,
            font=self.font(9, "bold"),
            fg=self.app.RED,
            bg=self.app.BG,
            anchor="w",
            wraplength=500,
        ).pack(side="left", fill="x", expand=True)
        self._button(footer, self.t("cancel"), self.win.destroy, "#DCE5F0", self.app.TEXT).pack(
            side="right", padx=(10, 0)
        )
        self._button(
            footer,
            self.t("settings_save_compact") if self.compact else self.t("save_settings"),
            self.save,
            self.app.BLUE,
            "white",
        ).pack(side="right")

    def _button(self, parent, text, command, bg, fg):
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=self.font(9, "bold"),
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=18,
            pady=9,
            cursor="hand2",
        )

    def _scroll_tab(self, title):
        tab = tk.Frame(self.tabs, bg=self.app.BG)
        compact_labels = {"CONNECTOR": "CONNECTION", "STATIONS & FAILURES": self.t("settings_stations")}
        localized = {
            "GENERAL": self.t("tab_general"),
            "CONNECTOR": self.t("tab_connector"),
            "STATIONS & FAILURES": self.t("tab_stations"),
            "MESSAGES": self.t("tab_messages"),
            "SYSTEM": self.t("tab_system"),
            "COLORS": self.t("tab_colors"),
        }
        self.tabs.add(
            tab,
            text=(
                compact_labels.get(title, localized.get(title, title))
                if self.compact
                else localized.get(title, title)
            ),
        )
        canvas = tk.Canvas(tab, bg=self.app.BG, highlightthickness=0)
        bar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=self.app.BG)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        body.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfigure(window, width=e.width)
        )
        wheel = lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        canvas.bind("<MouseWheel>", wheel)
        body.bind("<MouseWheel>", wheel)
        canvas.bind("<Button-4>", lambda _e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda _e: canvas.yview_scroll(1, "units"))
        return body

    def _section(self, parent, title, description=""):
        box = tk.Frame(
            parent,
            bg="white",
            highlightthickness=1,
            highlightbackground=self.app.BORDER,
        )
        box.pack(fill="x", padx=8, pady=7)
        tk.Label(
            box, text=title, font=self.font(11, "bold"), fg=self.app.TEXT, bg="white"
        ).pack(anchor="w", padx=14, pady=(11, 1))
        if description:
            tk.Label(
                box, text=description, font=self.font(8), fg=self.app.MUTED, bg="white"
            ).pack(anchor="w", padx=14, pady=(0, 5))
        form = tk.Frame(box, bg="white")
        form.pack(fill="x", padx=14, pady=(3, 12))
        form.columnconfigure(1, weight=1)
        return form

    def _field(self, parent, row, label, key, value=None, choices=None, secret=False):
        label_options = (
            {"textvariable": label}
            if isinstance(label, tk.StringVar)
            else {"text": label}
        )
        tk.Label(
            parent,
            font=self.font(8, "bold"),
            fg=self.app.MUTED,
            bg="white",
            **label_options,
        ).grid(row=row, column=0, sticky="w", pady=5)
        var = tk.StringVar(
            value=str(self.app.config.get(key, "") if value is None else value)
        )
        self.vars[key] = var
        if choices is not None:
            values = list(choices)
            if var.get() and var.get() not in values:
                values.insert(0, var.get())
            widget = ttk.Combobox(
                parent,
                textvariable=var,
                values=values,
                state="readonly" if values else "normal",
                style="Settings.TCombobox",
            )
        else:
            widget = tk.Entry(
                parent,
                textvariable=var,
                font=self.font(10),
                show="●" if secret else "",
                relief="flat",
                highlightthickness=1,
                highlightbackground="#B9C7D8",
                highlightcolor=self.app.BLUE,
            )
        widget.grid(row=row, column=1, sticky="ew", padx=(16, 0), ipady=5)
        return widget

    def _general_tab(self):
        body = self._scroll_tab("GENERAL")
        identity = self._section(
            body,
            self.t("settings_line_identity"),
            self.t("settings_product_and_licensing_identity_is_fixed"),
        )
        for row, (label, key) in enumerate(
            (
                (self.t("settings_line_machine_name"), "line_name"),
                (self.t("settings_location_identifier"), "location_id"),
                (self.t("settings_asset_identifier"), "asset_id"),
            )
        ):
            self._field(identity, row, label, key)
        workflow = self._section(body, self.t("settings_response_record_defaults"))
        self._field(
            workflow,
            0,
            self.t("settings_unplanned_priority"),
            "response_record_priority",
            choices=("NONE", "LOW", "MEDIUM", "HIGH"),
        )
        self._field(
            workflow,
            1,
            self.t("settings_unplanned_work_type"),
            "response_record_type",
            choices=("REACTIVE", "PREVENTIVE", "OTHER"),
        )
        self._field(
            workflow,
            2,
            self.t("settings_planned_priority"),
            "planned_work_priority",
            choices=("NONE", "LOW", "MEDIUM", "HIGH"),
        )
        self.asset_status_tracking = tk.BooleanVar(
            value=bool(self.app.config.get("asset_status_tracking", False))
        )
        tk.Checkbutton(
            workflow,
            text=self.t("settings_synchronize_asset_offline_online_status"),
            variable=self.asset_status_tracking,
            font=self.font(9, "bold"),
            fg=self.app.TEXT,
            bg="white",
            activebackground="white",
            selectcolor="white",
        ).grid(row=3, column=1, sticky="w", padx=(12, 0), pady=6)

    def _integration_tab(self):
        body = self._scroll_tab("CONNECTOR")
        form = self._section(
            body,
            self.t("settings_detected_external_connectors"),
            self.t("settings_connector_files_beside_the_application_are"),
        )
        capability_labels = {
            "response_records": "Response records",
            "response_record_status": "Status updates",
            "response_record_comments": "Comments",
            "response_record_assignments": "Assignments",
            "asset_status": "Asset state",
            "messaging": "Messaging",
            "team_directory": "Team directory",
        }
        inventory = self.app.connector_inventory
        active_name = inventory.active.path.name if inventory.active else ""
        self.connector_selection = tk.StringVar(value=active_name)
        if not inventory.candidates:
            tk.Label(
                form,
                text=self.t("settings_no_connector_files_found"),
                font=self.font(10, "bold"),
                fg=self.app.ORANGE,
                bg="white",
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=8)
            tk.Label(
                form,
                text=self.t("settings_place_connector_json_connector_json_connector"),
                font=self.font(8),
                fg=self.app.MUTED,
                bg="white",
                wraplength=680,
                justify="left",
            ).grid(row=1, column=0, columnspan=2, sticky="w")
        row = 0
        for candidate in inventory.candidates:
            definition = candidate.definition
            color = (
                self.app.GREEN
                if candidate.ready
                else (self.app.RED if candidate.error else self.app.ORANGE)
            )
            card = tk.Frame(
                form,
                bg="#F7F9FC",
                highlightthickness=1,
                highlightbackground=self.app.BORDER,
            )
            card.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
            card.columnconfigure(1, weight=1)
            if candidate.valid:
                tk.Radiobutton(
                    card,
                    variable=self.connector_selection,
                    value=candidate.path.name,
                    bg="#F7F9FC",
                    activebackground="#F7F9FC",
                    selectcolor="white",
                ).grid(row=0, column=0, rowspan=3, padx=8)
            title = definition.display_name if definition else candidate.path.name
            tk.Label(
                card,
                text=title,
                font=self.font(10, "bold"),
                fg=self.app.TEXT,
                bg="#F7F9FC",
            ).grid(row=0, column=1, sticky="w", pady=(7, 0))
            tk.Label(
                card,
                text=f"{candidate.status}  •  {candidate.path.name}"
                + (
                    f"  •  {definition.data['connection'].get('protocol', 'rest').upper()}"
                    if definition
                    else ""
                ),
                font=self.font(8, "bold"),
                fg=color,
                bg="#F7F9FC",
            ).grid(row=1, column=1, sticky="w")
            detail = candidate.error
            if definition:
                enabled = [
                    label
                    for key, label in capability_labels.items()
                    if definition.capabilities.get(key)
                ]
                detail = "Features: " + (
                    ", ".join(enabled) if enabled else "Local terminal only"
                )
            tk.Label(
                card,
                text=detail,
                font=self.font(8),
                fg=self.app.MUTED,
                bg="#F7F9FC",
                wraplength=650,
                justify="left",
            ).grid(row=2, column=1, sticky="w", pady=(0, 7))
            row += 1
        tk.Label(
            form,
            text=self.t("settings_validation_is_offline_and_makes_no"),
            font=self.font(8),
            fg=self.app.MUTED,
            bg="white",
            wraplength=680,
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 10))
        row += 1
        diagnostics = tk.Frame(form, bg="white")
        diagnostics.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        diagnostics.columnconfigure(0, weight=1)
        self.connector_test_status = tk.StringVar(
            value="Test performs local validation plus one safe read-only network request."
        )
        tk.Label(
            diagnostics,
            textvariable=self.connector_test_status,
            font=self.font(8, "bold"),
            fg=self.app.MUTED,
            bg="white",
            wraplength=520,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        self.connector_test_button = self._button(
            diagnostics,
            self.t("settings_test_selected_connector"),
            self._test_selected_connector,
            self.app.BLUE,
            "white",
        )
        self.connector_test_button.grid(row=0, column=1, sticky="e", padx=(10, 0))
        row += 1
        self._button(
            form,
            self.t("settings_create_new_basic_connector"),
            self._create_connector_wizard,
            "#DCE5F0",
            self.app.TEXT,
        ).grid(row=row, column=0, columnspan=2, sticky="e", pady=(0, 10))
        row += 1
        rows = (
            (
                "Engineering assignment team",
                "engineering_team_name",
                self.directory.get("teams", []),
            ),
            (
                "Engineering chat or person",
                "engineering_chat_name",
                self.directory.get("conversations", []),
            ),
            (
                "Quality chat or person",
                "quality_chat_name",
                self.directory.get("conversations", []),
            ),
            (
                "Production chat or person",
                "production_chat_name",
                self.directory.get("conversations", []),
            ),
            (
                "Common activity chat or person",
                "common_activity_chat_name",
                self.directory.get("conversations", []),
            ),
        )
        for field_row, (label, key, choices) in enumerate(rows, row):
            self._field(form, field_row, label, key, choices=choices)
        self._field(
            form,
            row + len(rows),
            "Escalation chat or person (optional)",
            "escalation_chat_name",
            choices=self.directory.get("conversations", []),
        )

    def _test_selected_connector(self):
        selected = self.connector_selection.get().strip()
        candidate = next(
            (
                item
                for item in self.app.connector_inventory.candidates
                if item.path.name == selected
            ),
            None,
        )
        if not candidate:
            self.connector_test_status.set("Select a detected connector first.")
            return
        self.connector_test_button.configure(state="disabled")
        self.connector_test_status.set(
            "Testing local contract and one safe GET request…"
        )
        self.connector_test_queue = queue.Queue(maxsize=1)

        def worker():
            result = test_connector(candidate, self.app.config, self.app.logger)
            self.connector_test_queue.put(result)

        threading.Thread(target=worker, daemon=True).start()
        self.win.after(100, self._poll_connector_test)

    def _create_connector_wizard(self):
        dialog = tk.Toplevel(self.win)
        dialog.title("Create New Basic Connector")
        dialog.configure(bg=self.app.BG)
        dialog.transient(self.win)
        dialog.grab_set()
        width = min(660, max(500, int(self.viewport_width * 0.72)))
        dialog.geometry(f"{width}x470")
        shell = tk.Frame(dialog, bg="white")
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(
            shell,
            text=self.t("settings_create_new_basic_connector"),
            font=self.font(15, "bold"),
            fg=self.app.TEXT,
            bg="white",
        ).pack(anchor="w", padx=16, pady=(16, 2))
        tk.Label(
            shell,
            text=self.t("settings_creates_a_new_diagnostic_only_rest"),
            font=self.font(8),
            fg=self.app.MUTED,
            bg="white",
            wraplength=width - 64,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))
        form = tk.Frame(shell, bg="white")
        form.pack(fill="x", padx=16)
        form.columnconfigure(1, weight=1)
        values = {
            "name": tk.StringVar(value="Plant Operations System"),
            "base": tk.StringVar(value="https://"),
            "auth": tk.StringVar(value="Bearer token"),
            "credential": tk.StringVar(),
            "path": tk.StringVar(value="/users/me"),
        }
        labels = (
            (self.t("settings_connector_name"), "name"),
            (self.t("settings_https_base_url"), "base"),
            (self.t("settings_authentication"), "auth"),
            (self.t("settings_token_api_key"), "credential"),
            (self.t("settings_safe_get_diagnostic_path"), "path"),
        )
        for row_index, (label, key) in enumerate(labels):
            tk.Label(
                form,
                text=label,
                font=self.font(8, "bold"),
                fg=self.app.MUTED,
                bg="white",
            ).grid(row=row_index, column=0, sticky="w", pady=6)
            if key == "auth":
                widget = ttk.Combobox(
                    form,
                    textvariable=values[key],
                    values=("Bearer token", "X-API-Key"),
                    state="readonly",
                )
            else:
                widget = tk.Entry(
                    form,
                    textvariable=values[key],
                    show="●" if key == "credential" else "",
                    font=self.font(9),
                )
            widget.grid(row=row_index, column=1, sticky="ew", padx=(12, 0), ipady=5)
        error = tk.StringVar()
        tk.Label(
            shell,
            textvariable=error,
            font=self.font(8, "bold"),
            fg=self.app.RED,
            bg="white",
            wraplength=width - 64,
        ).pack(anchor="w", padx=16, pady=(10, 4))

        def create():
            try:
                data = basic_diagnostic_connector(
                    values["name"].get(),
                    values["base"].get(),
                    values["credential"].get(),
                    values["path"].get(),
                    values["auth"].get(),
                )
                slug = re.sub(
                    r"[^a-z0-9]+", "-", values["name"].get().casefold()
                ).strip("-")
                target = CONNECTOR_FILE.parent / f"{slug or 'new'}.connector.json"
                if target.exists():
                    raise ConfigurationError(
                        f"{target.name} already exists; choose another name"
                    )
                write_connector(data, target)
                self.app.connector_inventory = select_connector(target.name)
                self.connector_selection.set(target.name)
                self.app.logger.log(
                    "connector_created_by_wizard",
                    connector_file=target.name,
                    capabilities="diagnostic-only",
                    administrator=self.app.authorized_admin_identity,
                )
                dialog.destroy()
                self.connector_test_status.set(
                    f"{target.name} created securely • starting diagnostic…"
                )
                self._test_selected_connector()
            except (DefinitionError, ConfigurationError, OSError) as exc:
                error.set(str(exc))

        buttons = tk.Frame(shell, bg="white")
        buttons.pack(fill="x", padx=16, pady=(4, 16))
        self._button(buttons, self.t("cancel"), dialog.destroy, "#DCE5F0", self.app.TEXT).pack(
            side="right", padx=(8, 0)
        )
        self._button(buttons, self.t("settings_create_test"), create, self.app.BLUE, "white").pack(
            side="right"
        )

    def _poll_connector_test(self):
        try:
            result = self.connector_test_queue.get_nowait()
        except queue.Empty:
            if self.win.winfo_exists():
                self.win.after(100, self._poll_connector_test)
            return
        self._connector_test_finished(result)

    def _connector_test_finished(self, result):
        self.connector_test_button.configure(state="normal")
        suffix = (
            f" • {result.operation_id} • {result.duration_ms} ms"
            if result.operation_id
            else ""
        )
        self.connector_test_status.set(
            ("PASSED • " if result.success else "FAILED • ") + result.message + suffix
        )
        self.app.logger.log(
            "connector_diagnostic_completed",
            "INFO" if result.success else "WARNING",
            success=result.success,
            operation=result.operation_id,
            duration_ms=result.duration_ms,
        )

    def _stations_tab(self):
        tab = tk.Frame(self.tabs, bg=self.app.BG)
        self.tabs.add(tab, text=self.t("settings_stations") if self.compact else "STATIONS & FAILURES")
        shell = tk.Frame(
            tab, bg="white", highlightthickness=1, highlightbackground=self.app.BORDER
        )
        shell.pack(fill="both", expand=True, padx=8, pady=8)
        left_width = round(self.viewport_width * (0.34 if self.compact else 0.24))
        left = tk.Frame(shell, bg="#F5F8FC", width=left_width)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(
            left,
            text=self.t("settings_line_sequence"),
            font=self.font(9, "bold"),
            fg=self.app.MUTED,
            bg="#F5F8FC",
        ).pack(anchor="w", padx=12, pady=(12, 6))
        list_frame = tk.Frame(left, bg="#F5F8FC")
        list_frame.pack(fill="both", expand=True, padx=10)
        self.station_list = tk.Listbox(
            list_frame,
            font=self.font(11, "bold"),
            bg="white",
            fg=self.app.TEXT,
            selectbackground=self.app.BLUE,
            selectforeground="white",
            activestyle="none",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#B9C7D8",
        )
        scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.station_list.yview
        )
        self.station_list.configure(yscrollcommand=scroll.set)
        self.station_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        controls = tk.Frame(left, bg="#F5F8FC")
        controls.pack(fill="x", padx=8, pady=10)
        actions = (
            ("+ ADD", self.add_station),
            ("REMOVE", self.remove_station),
            ("MOVE UP", lambda: self.move_station(-1)),
            ("MOVE DOWN", lambda: self.move_station(1)),
        )
        for index, (text, command) in enumerate(actions):
            self._button(controls, text, command, "#DCE5F0", self.app.TEXT).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2
            )
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        right = tk.Frame(shell, bg="white")
        right.pack(side="left", fill="both", expand=True, padx=18, pady=12)
        tk.Label(
            right,
            text=self.t("settings_station_details"),
            font=self.font(14, "bold"),
            fg=self.app.TEXT,
            bg="white",
        ).pack(anchor="w")
        tk.Label(
            right,
            text=self.t("settings_use_any_user_defined_name_such"),
            font=self.font(8),
            fg=self.app.MUTED,
            bg="white",
        ).pack(anchor="w", pady=(1, 10))
        self.station_name = tk.StringVar()
        name_form = tk.Frame(right, bg="white")
        name_form.pack(fill="x")
        tk.Label(
            name_form,
            text=self.t("settings_station_name"),
            font=self.font(8, "bold"),
            fg=self.app.MUTED,
            bg="white",
        ).pack(anchor="w")
        tk.Entry(
            name_form,
            textvariable=self.station_name,
            font=self.font(12, "bold"),
            relief="flat",
            highlightthickness=1,
            highlightbackground="#B9C7D8",
            highlightcolor=self.app.BLUE,
        ).pack(fill="x", ipady=6, pady=(3, 10))
        tk.Label(
            right,
            text=self.t("settings_custom_failure_types"),
            font=self.font(8, "bold"),
            fg=self.app.MUTED,
            bg="white",
        ).pack(anchor="w")
        self.failure_vars = [tk.StringVar() for _ in range(4)]
        for index, var in enumerate(self.failure_vars):
            row = tk.Frame(right, bg="white")
            row.pack(fill="x", pady=3)
            tk.Label(
                row,
                text=str(index + 1),
                font=self.font(9, "bold"),
                fg=self.app.BLUE,
                bg="#EAF1FF",
                width=3,
                pady=6,
            ).pack(side="left")
            tk.Entry(
                row,
                textvariable=var,
                font=self.font(10),
                relief="flat",
                highlightthickness=1,
                highlightbackground="#B9C7D8",
                highlightcolor=self.app.BLUE,
            ).pack(side="left", fill="x", expand=True, ipady=6, padx=(7, 0))
        tk.Label(
            right,
            text=self.t("settings_leave_unused_rows_blank_at_least"),
            font=self.font(8, "bold"),
            fg=self.app.GREEN,
            bg="white",
            justify="left",
        ).pack(anchor="w", pady=(10, 0))
        self.station_list.bind("<<ListboxSelect>>", self.select_station)
        self._refresh_station_list(0)

    def _messages_tab(self):
        body = self._scroll_tab("MESSAGES")
        specs = (
            ("Unplanned response-record title", "downtime_title_template", 2),
            ("Unplanned description", "downtime_description_template", 3),
            ("Support request message", "help_message_template", 4),
            ("Planned response-record title", "planned_work_title_template", 2),
            ("Planned description", "planned_work_description_template", 3),
        )
        for title, key, height in specs:
            form = self._section(
                body,
                title,
                "Template placeholders such as {line}, {zones}, {timestamp}, {time}, {department}, and {work_label} are preserved.",
            )
            text = tk.Text(
                form,
                height=height,
                font=self.font(9),
                wrap="word",
                relief="flat",
                highlightthickness=1,
                highlightbackground="#B9C7D8",
            )
            text.insert("1.0", str(self.app.config.get(key, "")))
            text.grid(row=0, column=0, columnspan=2, sticky="ew", ipady=3)
            self.texts[key] = text

    def _system_tab(self):
        body = self._scroll_tab("SYSTEM")
        access = self._section(body, self.t("settings_administrator_access"))
        self.password_status = tk.StringVar(value=self._password_status())
        tk.Label(
            access, textvariable=self.password_status, font=self.font(9),
            fg=self.app.TEXT, bg="white", justify="left",
            wraplength=max(180, self.viewport_width - 120),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._button(
            access, self.t("settings_change_password"), self.change_password,
            self.app.BLUE, "white",
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        runtime = self._section(body, self.t("settings_touchscreen_runtime"))
        specs = (
            (self.t("settings_animation_interval_ms"), "animation_interval_ms"),
            (self.t("settings_sound_volume_0_100"), "sound_volume"),
            (self.t("settings_sound_repeat_cooldown_ms"), "sound_cooldown_ms"),
            (self.t("settings_directory_max_pages"), "directory_max_pages"),
            (self.t("settings_downtime_escalation_minutes_0_disables"), "escalation_minutes"),
            (self.t("settings_micro_stop_threshold_minutes"), "micro_stop_threshold_minutes"),
        )
        for row, (label, key) in enumerate(specs):
            self._field(runtime, row, label, key)
        self.fullscreen = tk.BooleanVar(
            value=bool(self.app.config.get("fullscreen_on_linux", True))
        )
        tk.Checkbutton(
            runtime,
            text=self.t("settings_fullscreen_on_linux"),
            variable=self.fullscreen,
            font=self.font(9, "bold"),
            fg=self.app.TEXT,
            bg="white",
            activebackground="white",
            selectcolor="white",
        ).grid(row=len(specs), column=1, sticky="w", padx=(12, 0), pady=6)
        self.sound_enabled = tk.BooleanVar(
            value=bool(self.app.config.get("sound_enabled", True))
        )
        tk.Checkbutton(
            runtime,
            text=self.t("settings_operational_sound_cues"),
            variable=self.sound_enabled,
            font=self.font(9, "bold"),
            fg=self.app.TEXT,
            bg="white",
            activebackground="white",
            selectcolor="white",
        ).grid(row=len(specs) + 1, column=1, sticky="w", padx=(12, 0), pady=6)
        self._button(
            runtime,
            self.t("settings_test_sound"),
            lambda: self.app.sound.preview(self.vars["sound_volume"].get()),
            "#DCE8F8",
            self.app.TEXT,
        ).grid(row=len(specs) + 2, column=1, sticky="w", padx=(12, 0), pady=6)
        updates = self._section(
            body,
            self.t("settings_software_updates"),
            self.t("settings_software_updates_description"),
        )
        self.update_check_enabled = tk.BooleanVar(
            value=bool(self.app.config.get("software_update_check_enabled", True))
        )
        tk.Checkbutton(
            updates,
            text=self.t("settings_check_whether_a_newer_version_has"),
            variable=self.update_check_enabled,
            font=self.font(9, "bold"),
            fg=self.app.TEXT,
            bg="white",
            activebackground="white",
            selectcolor="white",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=6)
        for row, (label, value) in enumerate(self._update_summary(), start=1):
            tk.Label(
                updates,
                text=label,
                font=self.font(9),
                fg=self.app.MUTED,
                bg="white",
                anchor="e",
            ).grid(row=row, column=0, sticky="e", padx=(14, 8), pady=3)
            tk.Label(
                updates,
                text=value,
                font=self.font(9, "bold"),
                fg=self.app.TEXT,
                bg="white",
                anchor="w",
                wraplength=max(220, int(self.viewport_width * 0.45)),
                justify="left",
            ).grid(row=row, column=1, sticky="w", padx=(12, 14), pady=3)
        logs = self._section(body, self.t("settings_logs_and_storage"))
        for row, (label, key) in enumerate(
            (
                (self.t("settings_log_directory"), "log_directory"),
                (self.t("settings_log_level"), "log_level"),
                (self.t("settings_retention_days"), "log_retention_days"),
                (self.t("settings_filesystem_reserve_mb"), "log_storage_reserve_mb"),
                (self.t("settings_daily_growth_floor_mb"), "log_daily_growth_floor_mb"),
            )
        ):
            choices = (
                ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
                if key == "log_level"
                else None
            )
            self._field(logs, row, label, key, choices=choices)

    def _password_status(self):
        if self.app.settings_credentials.path.exists():
            return self.t("settings_local_password_active")
        return self.t("settings_initial_password_active")

    def change_password(self):
        if self.app.modal:
            return

        def resume(changed):
            if not self.win.winfo_exists():
                return
            self.password_status.set(self._password_status())
            self.win.deiconify()
            self.win.lift()
            self.win.grab_set()
            self.win.focus_set()
            if changed:
                self.error.set(self.t("settings_password_saved"))

        self.win.grab_release()
        self.win.withdraw()
        self.app.request_password_change(resume)
        self.app.root.focus_set()
        self.app.render()

    def _update_summary(self):
        """Read-only facts an auditor or supervisor may need from Settings."""
        status = self.app.update_status()
        staged = status.staged.version if status.staged else "None"
        return (
            ("Installed version", status.installed_version),
            (
                "Installation type",
                "Managed version slots" if status.managed else "Standard installation",
            ),
            ("Activation state", status.state.replace("_", " ").title()),
            ("Verified update waiting", staged),
            ("Version available for rollback", status.rollback_version or "None"),
            ("Latest published version", status.latest_version or "Not known"),
            ("Update drive volume label", update_trust.UPDATE_VOLUME_LABELS[0]),
            ("Release source (fixed at build time)", update_trust.RELEASES_URL),
            (
                "Trusted signing key",
                ", ".join(key.key_id for key in update_trust.TRUSTED_KEYS),
            ),
        )

    def _appearance_tab(self):
        body = self._scroll_tab("COLORS")
        colors = self._section(
            body,
            self.t("settings_interface_colors"),
            self.t("settings_use_six_digit_hexadecimal_colors_for"),
        )
        self._field(
            colors,
            0,
            self.t("settings_color_preset"),
            "ui_color_preset",
            choices=("standard", "colorblind_safe", "custom"),
        )
        self._field(
            colors,
            1,
            self.t("settings_interface_language"),
            UI_LANGUAGE_CONFIG_KEY,
            choices=available_languages(),
        )
        for row, key in enumerate(self.COLOR_KEYS):
            self._field(
                colors,
                row + 2,
                key.replace("_", " ").title(),
                f"color_{key}",
                self.app.config["ui_colors"].get(key, ""),
            )

    def _store_station(self):
        if self.current_station is None or self.current_station >= len(self.stations):
            return
        self.stations[self.current_station] = {
            "name": self.station_name.get().strip(),
            "failures": [
                var.get().strip() for var in self.failure_vars if var.get().strip()
            ],
        }

    def _refresh_station_list(self, index=None):
        self.station_list.delete(0, "end")
        for number, station in enumerate(self.stations, 1):
            self.station_list.insert(
                "end", f"{number:02}   {station['name'] or '(unnamed)'}"
            )
        if self.stations:
            index = max(
                0, min(index if index is not None else 0, len(self.stations) - 1)
            )
            self.station_list.selection_set(index)
            self.station_list.activate(index)
            self.current_station = index
            self._load_station(index)

    def _load_station(self, index):
        station = self.stations[index]
        self.station_name.set(station["name"])
        for pos, var in enumerate(self.failure_vars):
            var.set(station["failures"][pos] if pos < len(station["failures"]) else "")

    def select_station(self, _event=None):
        selection = self.station_list.curselection()
        if not selection:
            return
        target = int(selection[0])
        if self.current_station is not None and target != self.current_station:
            self._store_station()
        self.current_station = target
        self._load_station(target)

    def add_station(self):
        self._store_station()
        existing = {station["name"].casefold() for station in self.stations}
        number = len(self.stations) + 1
        name = f"Station {number}"
        while name.casefold() in existing:
            number += 1
            name = f"Station {number}"
        self.stations.append({"name": name, "failures": list(STATION_FAILURE_FALLBACK)})
        self._refresh_station_list(len(self.stations) - 1)

    def remove_station(self):
        if len(self.stations) <= 1:
            self.error.set("At least one station is required.")
            return
        index = self.current_station or 0
        removed = self.stations.pop(index)
        self._refresh_station_list(min(index, len(self.stations) - 1))
        self.error.set(f"{removed['name']} removed. Save to confirm.")

    def move_station(self, direction):
        self._store_station()
        index = self.current_station
        if index is None:
            return
        target = index + direction
        if not 0 <= target < len(self.stations):
            return
        self.stations[index], self.stations[target] = (
            self.stations[target],
            self.stations[index],
        )
        self._refresh_station_list(target)

    def save(self):
        try:
            self._store_station()
            candidate = deepcopy(self.app.config)
            for key, var in self.vars.items():
                if not key.startswith("color_") and not key.startswith("integration_"):
                    candidate[key] = var.get().strip()
            if not candidate.get("line_name"):
                raise ConfigurationError("Line / machine name cannot be empty")
            numeric_ranges = {
                "animation_interval_ms": (30, 1000),
                "sound_volume": (0, 100),
                "sound_cooldown_ms": (0, 5000),
                "directory_max_pages": (1, 20),
                "log_retention_days": (1, 730),
                "log_storage_reserve_mb": (128, 102400),
                "log_daily_growth_floor_mb": (1, 1024),
                "escalation_minutes": (0, 1440),
                "micro_stop_threshold_minutes": (1, 1440),
            }
            for key, (minimum, maximum) in numeric_ranges.items():
                try:
                    value = int(candidate[key])
                except (TypeError, ValueError):
                    raise ConfigurationError(
                        f"{key.replace('_', ' ')} must be a whole number"
                    )
                if not minimum <= value <= maximum:
                    raise ConfigurationError(
                        f"{key.replace('_', ' ')} must be between {minimum} and {maximum}"
                    )
                candidate[key] = value
            candidate["fullscreen_on_linux"] = bool(self.fullscreen.get())
            candidate["sound_enabled"] = bool(self.sound_enabled.get())
            candidate["software_update_check_enabled"] = bool(
                self.update_check_enabled.get()
            )
            candidate["asset_status_tracking"] = bool(self.asset_status_tracking.get())
            candidate["zones"] = [station["name"].strip() for station in self.stations]
            candidate["station_failure_types"] = {
                station["name"].strip(): station["failures"]
                for station in self.stations
            }
            validate_station_failures(candidate)
            for key, text in self.texts.items():
                value = text.get("1.0", "end-1c").strip()
                if not value:
                    raise ConfigurationError(f"{key.replace('_', ' ')} cannot be empty")
                allowed = {
                    "line",
                    "zones",
                    "timestamp",
                    "time",
                    "department",
                    "condition",
                    "work_label",
                }
                try:
                    fields = {
                        name
                        for _, name, _, _ in string.Formatter().parse(value)
                        if name
                    }
                except ValueError as exc:
                    raise ConfigurationError(
                        f"Invalid braces in {key.replace('_', ' ')}: {exc}"
                    )
                unknown = fields - allowed
                if unknown:
                    raise ConfigurationError(
                        f"Unsupported placeholder in {key.replace('_', ' ')}: {', '.join(sorted(unknown))}"
                    )
                candidate[key] = value
            colors = {}
            for key in self.COLOR_KEYS:
                value = self.vars[f"color_{key}"].get().strip().upper()
                if not re.fullmatch(r"#[0-9A-F]{6}", value):
                    raise ConfigurationError(f"Invalid color for {key}: {value}")
                colors[key] = value
            if candidate.get("ui_color_preset") == "colorblind_safe":
                colors = dict(COLORBLIND_SAFE_COLORS)
            elif colors != self.app.config.get("ui_colors"):
                candidate["ui_color_preset"] = "custom"
            candidate["ui_colors"] = colors
            validate_config(candidate)
            selected_connector = self.connector_selection.get().strip()
            if selected_connector:
                try:
                    self.app.connector_inventory = select_connector(selected_connector)
                except (DefinitionError, OSError) as exc:
                    raise ConfigurationError(str(exc)) from exc
            write_config(candidate)
            self._apply(candidate)
            self.win.destroy()
            self.app.notify("All settings saved", "success", 6)
        except ConfigurationError as exc:
            self.error.set(str(exc).replace("\n", "  "))
            self.tabs.select(
                2
                if "station" in str(exc).casefold() or "failure" in str(exc).casefold()
                else self.tabs.index("current")
            )

    def _apply(self, candidate):
        app = self.app
        old_zones = set(app.config.get("zones", []))
        app.config = candidate
        app.sound.update(candidate)
        update_service = getattr(app, "update_service", None)
        if update_service is not None:
            update_service.config = candidate
        # Configuration keys are stable schema identifiers, never translated UI
        # text. Using a localized label here would silently break language changes
        # as soon as a second locale translated that label.
        app.t = load_translator(candidate.get(UI_LANGUAGE_CONFIG_KEY, "en"))
        app.station_page = 0
        new_logger = ActivityLogger(candidate)
        app.reload_connector(new_logger)
        colors = candidate["ui_colors"]
        app.BG, app.CARD, app.TEXT, app.MUTED = (
            colors["background"],
            colors["card"],
            colors["text"],
            colors["muted"],
        )
        app.RED, app.GREEN, app.BLUE = colors["red"], colors["green"], colors["blue"]
        app.ORANGE, app.PURPLE, app.BORDER = (
            colors["orange"],
            colors["purple"],
            colors["border"],
        )
        app.root.configure(bg=app.BG)
        app.canvas.configure(bg=app.BG)
        selected = [
            zone
            for zone in app.selected_zones()
            if zone == "ENTIRE LINE" or zone in candidate["zones"]
        ]
        app.state["issue_zones"] = selected
        cleaned = {}
        for zone, values in app.state.get("failure_selections", {}).items():
            if zone not in candidate["zones"]:
                continue
            allowed = set(candidate["station_failure_types"][zone]) | {"Others"}
            retained = [value for value in values if value in allowed]
            if retained:
                cleaned[zone] = retained
        app.state["failure_selections"] = cleaned
        app.state["failure_notes"] = {
            zone: note
            for zone, note in app.state.get("failure_notes", {}).items()
            if zone in cleaned and "Others" in cleaned[zone]
        }
        app.save_state()
        app.logger = new_logger
        app.provider.logger = app.logger
        app.logger.log(
            "settings_saved",
            administrator=app.authorized_admin_identity,
            changed_station_count=len(
                old_zones.symmetric_difference(candidate["zones"])
            ),
            zones=candidate["zones"],
            integration=app.provider.INFO.display_name,
            integration_ready=app.provider.connected,
        )
