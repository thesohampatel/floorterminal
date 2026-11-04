"""Read-only roster health and explicit refresh using the saved connection."""

import tkinter as tk


class RosterSettingsMixin:
    def build_roster_tools(self, body):
        form = self._section(
            body,
            "Saved team members",
            "Names are stored privately on this kiosk, not in the connector. "
            "Daily refresh waits until after midnight and the kiosk is idle. "
            "Save team/connector changes before refreshing.",
        )
        self.roster_status_text = tk.StringVar(value=self.app.delivery.roster_status())
        self._autowrap(
            tk.Label(
                form,
                textvariable=self.roster_status_text,
                font=self.font(9),
                bg="white",
                fg=self.app.TEXT,
                justify="left",
                anchor="w",
            ),
            form,
            16,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.roster_refresh_button = self._button(
            form,
            "Refresh team members",
            self._refresh_team_members,
            self.app.BLUE,
            "white",
        )
        self.roster_refresh_button.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._poll_roster_status()

    def _refresh_team_members(self):
        active = self.app.connector_inventory.active
        active_name = active.path.name if active else ""
        if (
            self.vars["engineering_team_name"].get().strip()
            != self.app.config.get("engineering_team_name", "")
            or self.connector_selection.get().strip() != active_name
        ):
            self.error.set(
                "Save team and connector changes, then reopen Settings to refresh their members."
            )
            return
        message = self.app.delivery.request_roster()
        self.roster_status_text.set(message)

    def _poll_roster_status(self):
        self._roster_after = None
        message = self.app.delivery.roster_status()
        if self.roster_status_text.get() != message:
            self.roster_status_text.set(message)
        provider = self.app.provider
        enabled = (
            provider.connected
            and provider.INFO.supports_team_directory
            and not self.app.busy
            and self.app.delivery.active != "roster"
            and not self.app.delivery.roster_requested
        )
        state = "normal" if enabled else "disabled"
        if str(self.roster_refresh_button.cget("state")) != state:
            self.roster_refresh_button.configure(state=state)
        self._roster_after = self.win.after(1000, self._poll_roster_status)
