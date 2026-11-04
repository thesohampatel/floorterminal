"""Readable software identity, licensing and safe-deployment information."""

from .. import __version__
from .layout import split_row


class InformationViewMixin:
    def about_dialog(self):
        profile = self.project_profile
        body, footer = self.dialog_shell(
            "ABOUT FLOORTERMINAL", "Line-side reporting • open-source software"
        )
        a, b, c, d = body
        self.rounded(a, b, c, b + 64, 18, self.CARD, self.BORDER)
        logo = self.draw_brand_mark(a + 32, b + 32, 40)
        left = a + 62 if logo else a + 14
        self.row_label((left, b + 6, c - 12, b + 32), profile.product_name, 15)
        self.row_label(
            (left, b + 32, c - 12, b + 56),
            f"Version {__version__} • MIT license",
            10,
            self.BLUE,
        )
        page = self.modal.get("about_page", "overview")
        for key, rect in zip(
            ("overview", "license", "safety"), split_row((a, b + 72, c, b + 120), 3)
        ):
            self.kiosk_button(
                "ui_about_" + key, rect, key.title(), selected=page == key
            )
        sections = {
            "overview": [
                ("CREATED & MAINTAINED BY", profile.maintainer_name),
                ("CONTACT & INTEGRATION HELP", profile.support_contact),
                ("PURPOSE", profile.product_tagline),
            ],
            "license": [
                (
                    "MIT OPEN-SOURCE LICENSE",
                    "You may use, copy, modify, merge, publish, distribute, sublicense and sell this software. Retain the copyright and MIT license notice in copies or substantial portions.",
                ),
                (
                    "NOT INCLUDED",
                    "External-service access, credentials, deployment data, trademarks and third-party rights.",
                ),
                ("COPYRIGHT", profile.copyright_notice),
                (
                    "NO WARRANTY",
                    "Provided as-is, without warranty. See LICENSE for the full terms and limitation of liability.",
                ),
            ],
            "safety": [
                (
                    "REPORTING, NOT MACHINE CONTROL",
                    "Trained people remain responsible for guarding, E-stops, lockout/tagout and permits. This console is not a machine safety controller.",
                ),
                (
                    "SECURE YOUR TERMINAL",
                    "Change the default password. Protect connector credentials, restrict physical and network access, and install only verified signed updates.",
                ),
                (
                    "DEPLOYMENT RESPONSIBILITY",
                    "Verify connectors and backups. Protect logs, personal data and retention according to your site's requirements.",
                ),
            ],
        }
        self.paragraph_page(
            (a, b + 128, c, d), sections.get(page, sections["overview"])
        )
        self.dialog_actions(footer, [("cancel", self.t("close"), None, self.TEXT)])
