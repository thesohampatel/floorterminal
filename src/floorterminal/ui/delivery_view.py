"""Operator-readable delivery centre with protected message-only dismissal."""

import math
import time
from datetime import datetime


class DeliveryViewMixin:
    def delivery_dialog(self):
        entries = sorted(
            self.state.get("delivery_outbox", []),
            key=lambda item: (item["phase"] != "attention", item["created_at"]),
        )
        index = min(self.modal.get("item", 0), max(0, len(entries) - 1))
        item = entries[index] if entries else None
        self.modal["selected_id"] = item["id"] if item else None
        actions = []
        if len(entries) > 1:
            actions += [
                ("ui_delivery_prev", "Previous", None, self.TEXT),
                ("ui_delivery_next", "Next", None, self.TEXT),
            ]
        held = bool(item and item["phase"] == "attention")
        expired = bool(
            item
            and item["expires_at"] is not None
            and item["expires_at"] <= time.time()
        )
        if held:
            if not expired:
                actions.append(
                    ("ui_delivery_retry", "Review / retry", self.PALE_BLUE, self.BLUE)
                )
            if item["method"] == "send_message":
                actions.append(
                    ("ui_delivery_dismiss", "Dismiss notice", None, self.TEXT)
                )
            elif item["method"] == "create_response_record":
                actions.append(
                    (
                        "ui_delivery_link",
                        "Link existing record",
                        self.PALE_BLUE,
                        self.BLUE,
                    )
                )
            elif item["method"] == "set_asset_status":
                actions.append(
                    (
                        "ui_delivery_asset_confirm",
                        "Verify existing event",
                        self.PALE_BLUE,
                        self.BLUE,
                    )
                )
        actions.append(("cancel", "Close", None, self.TEXT))
        columns = (
            2
            if min(1100, self.viewport().width - 8) - 32 < 560
            else min(4, len(actions))
        )
        body, footer = self.dialog_shell(
            "DELIVERY CENTRE",
            f"{len(entries)} saved • reporting continues while updates are delivered"
            if entries
            else "No external updates are waiting in this queue",
            footer_rows=math.ceil(len(actions) / columns),
        )
        if item:
            phase = {
                "attention": "Review required",
                "queued": "Waiting to send",
                "sending": "Sending now",
            }[item["phase"]]
            message = item["method"] == "send_message"
            sections = [
                (
                    f"{index + 1} of {len(entries)} · {phase}",
                    ("Message to " + str(item["args"][0]))
                    if message
                    else item["method"].replace("_", " ").capitalize(),
                ),
                ("What happens next", self.delivery.explanation(item)),
            ]
            if item["error"] and item["error"] != self.delivery.explanation(item):
                sections.insert(1, ("Last delivery result", item["error"]))
            if message:
                sections.append(("Saved message", item["args"][1]))
            sections.append(
                (
                    "Saved on this terminal",
                    datetime.fromtimestamp(item["created_at"])
                    .astimezone()
                    .strftime("%d %b %Y · %H:%M:%S")
                    + f" · {item['attempts']} attempts",
                )
            )
            if held:
                sections.append(
                    (
                        "Before taking action",
                        "Check the connected system first. Retry may duplicate an accepted message. Dismiss removes this notice from the queue without sending it or claiming delivery; its audit record is retained."
                        if message
                        else "Verify the external system before retrying. Production records and equipment updates cannot be dismissed here.",
                    )
                )
        else:
            sections = [
                (
                    "Queue empty",
                    "There are no pending external updates on this terminal.",
                ),
                (
                    "Automatic delivery",
                    "New reports and messages are saved first, then sent in the background. Connection interruptions and request limits do not block the operator.",
                ),
            ]
        self.content_cards(body, sections)
        self.dialog_actions(footer, actions)
