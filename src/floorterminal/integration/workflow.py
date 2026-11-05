"""Vendor-neutral downtime workflow backed by one external integration file."""

from __future__ import annotations

import math

from ..core.config import DEFAULT_CONFIG
from .definition import IntegrationDefinition
from .mapping import expand_fields, read_field
from .runtime import IntegrationClient, IntegrationError


class ConfiguredIntegration:
    """Translate the terminal contract using connector.json only."""

    def __init__(self, config=None, logger=None, transport=None, definition=None):
        self.config, self.logger = config or DEFAULT_CONFIG, logger
        self.definition = (
            definition
            if isinstance(definition, IntegrationDefinition)
            else IntegrationDefinition(definition)
        )
        self._load_workflow()
        self.client = IntegrationClient(
            self.definition, self.config, self.logger, transport
        )
        self.api_user_name = ""
        self.api_user_id = self.definition.data["identity"].get(
            "authenticated_subject_id", ""
        )
        self.name_cache = {"team": {}, "conversation": {}, "user": {}}
        self.directory_progress = {}

    @property
    def connected(self):
        required = self.definition.data["authentication"].get(
            "required_credentials", []
        )
        return self.definition.enabled and all(
            self.definition.credentials.get(key, "").strip() for key in required
        )

    @property
    def display_name(self):
        return self.definition.display_name

    @property
    def identity_name(self):
        return self.api_user_name

    @property
    def app_window_used(self):
        return self.client.app_window_used

    @property
    def limit(self):
        return self.client.limit

    @property
    def remaining(self):
        return self.client.remaining

    @property
    def reset(self):
        return self.client.reset

    @property
    def window_resets_at(self):
        return self.client.window_resets_at

    @property
    def session_used(self):
        return self.client.session_used

    @classmethod
    def validate_configuration(cls, config):
        return None

    @classmethod
    def validate_credential(cls, credential):
        return None

    def reconfigure(self, config, logger=None):
        self.definition = IntegrationDefinition(self.definition.path)
        self.config, self.logger = config, logger or self.logger
        self._load_workflow()
        self.client.reconfigure(self.definition, config, self.logger)
        self.api_user_id = self.definition.data["identity"].get(
            "authenticated_subject_id", ""
        )
        self.api_user_name = ""
        self.name_cache = {"team": {}, "conversation": {}, "user": {}}
        self.directory_progress = {}

    def _load_workflow(self):
        extension = self.definition.workflow
        self.operations = extension.get("operations", {})
        self.collections = extension.get("collections", {})
        self.objects = extension.get("objects", {})
        self.fields = extension.get("fields", {})
        self.field_types = extension.get("field_types", {})
        self.values = extension.get("values", {})

    def _operation(self, semantic_name):
        try:
            return self.operations[semantic_name]
        except KeyError as exc:
            raise RuntimeError(
                f"connector.json lacks workflow operation: {semantic_name}"
            ) from exc

    def _execute(self, semantic_name, **kwargs):
        if "body" in kwargs:
            kwargs["body"] = expand_fields(kwargs["body"])
        return self.client.execute(self._operation(semantic_name), **kwargs)

    def _collection(self, semantic_name, data):
        value = data
        for key in filter(
            None, self.collections.get(semantic_name, semantic_name).split(".")
        ):
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, list) or any(
            not isinstance(item, dict) for item in value
        ):
            raise IntegrationError(
                f"Directory {semantic_name} is missing or is not a list of objects",
                "INVALID_RESPONSE",
            )
        return value

    def _field(self, semantic_name, default):
        return str(self.fields.get(semantic_name, default))

    def _object(self, semantic_name, data):
        value = data
        path = str(self.objects.get(semantic_name, "")).strip()
        for key in filter(None, path.split(".")):
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, dict):
            raise IntegrationError(
                f"Response is missing its configured {semantic_name} object",
                "INVALID_RESPONSE",
            )
        return value

    def _value(self, group, value):
        return self.values.get(group, {}).get(str(value).upper(), value)

    def _typed(self, semantic_name, value):
        """Coerce a canonical field only when connector.json explicitly requires it."""
        kind = self.field_types.get(semantic_name)
        if not kind:
            return value
        try:
            if kind == "string":
                return str(value)
            if kind == "integer":
                if (
                    isinstance(value, bool)
                    or isinstance(value, float)
                    and (not math.isfinite(value) or not value.is_integer())
                ):
                    raise ValueError
                return int(value)
            if kind == "number":
                if isinstance(value, bool):
                    raise ValueError
                result = float(value)
                if not math.isfinite(result):
                    raise ValueError
                return result
            if kind == "boolean":
                if isinstance(value, bool):
                    return value
                if str(value).strip().casefold() in {"true", "1"}:
                    return True
                if str(value).strip().casefold() in {"false", "0"}:
                    return False
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(
                f"Connector cannot convert {semantic_name} to {kind}"
            ) from exc
        return value

    def _record_name(self, record):
        direct = str(read_field(record, self._field("name", "name")) or "").strip()
        if direct:
            return direct
        return f"{read_field(record, self._field('first_name', 'firstName')) or ''} {read_field(record, self._field('last_name', 'lastName')) or ''}".strip()

    def load_identity(self):
        if not self.api_user_id:
            return ""
        data = self._execute("load_user", path={"id": self.api_user_id})
        user = self._object("loaded_identity", data)
        name = self._record_name(user)
        self.api_user_name = name
        if name:
            self.name_cache["user"][name.casefold()] = self.api_user_id
        return name

    def _assignee(self, kind, identifier):
        """Support explicitly declared keyed IDs as well as typed ID objects."""
        keyed = "team_assignee_id" if kind == "TEAM" else "user_assignee_id"
        if keyed in self.fields:
            return {
                self.fields[keyed]: self._typed(
                    keyed if keyed in self.field_types else "assignee_id", identifier
                )
            }
        return {
            self._field("assignee_type", "type"): self._value("assignee_type", kind),
            self._field("assignee_id", "id"): self._typed("assignee_id", identifier),
        }

    def create_response_record(
        self,
        title,
        description,
        team_id,
        priority="HIGH",
        work_type=None,
        participant_ids=None,
        idempotency_key=None,
    ):
        if not self.definition.capabilities.get("response_records"):
            raise RuntimeError(
                "The connector does not provide response-record creation"
            )
        body = {
            self._field("title", "title"): title,
            self._field("description", "description"): description,
            self._field("priority", "priority"): self._value("priority", priority),
            self._field("work_type", "type"): self._value(
                "work_type",
                work_type or self.config.get("response_record_type", "REACTIVE"),
            ),
        }
        if team_id:
            body[self._field("assignees", "assignees")] = [
                self._assignee("TEAM", team_id)
            ]
        for user_id in participant_ids or []:
            body.setdefault(self._field("assignees", "assignees"), []).append(
                self._assignee("USER", user_id)
            )
        if self.config.get("asset_id"):
            body[self._field("asset_id", "assetId")] = self._typed(
                "asset_id", self.config["asset_id"]
            )
        if self.config.get("location_id"):
            body[self._field("location_id", "locationId")] = self._typed(
                "location_id", self.config["location_id"]
            )
        # Optional structured metadata: never guess unsupported provider fields.
        for key in (
            "asset_ids",
            "location_ids",
            "group_ids",
            "group_names",
            "affected_stations",
            "reported_stations",
            "impact_scope",
            "incident_id",
            "failure_details",
        ):
            if key in self.fields and key in self.config:
                value = self.config[key]
                body[self.fields[key]] = (
                    [self._typed(key, item) for item in value]
                    if isinstance(value, list)
                    else self._typed(key, value)
                )
        response = self._execute(
            "create_response_record", body=body, idempotency_key=idempotency_key
        )
        record = self._object("created_response_record", response)
        result = {}
        identifier = read_field(record, self._field("response_record_id", "id"))
        number = read_field(
            record, self._field("response_record_reference", "reference")
        )
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, (str, int))
            or not str(identifier).strip()
            or len(str(identifier)) > 200
            or not str(identifier).isprintable()
        ):
            raise IntegrationError(
                "Creation returned no usable mapped record identifier",
                "INVALID_RESPONSE",
            )
        result["id"] = identifier
        if number is not None:
            result["reference"] = number
        return result

    def set_asset_status(
        self,
        status,
        downtime_type=None,
        description=None,
        started_at=None,
        idempotency_key=None,
    ):
        if not self.definition.capabilities.get("asset_status"):
            return {}
        asset_id = str(self.config.get("asset_id", "")).strip()
        if not asset_id:
            raise RuntimeError(
                "Configure the asset identifier before tracking line status"
            )
        normalized = str(status).strip().upper()
        if normalized not in {"ONLINE", "OFFLINE", "IGNORE"}:
            raise ValueError(f"Unsupported asset status: {status}")
        body = {
            self._field("asset_status", "status"): self._value(
                "asset_status", normalized
            )
        }
        if downtime_type is not None:
            kind = str(downtime_type).strip().upper()
            if kind not in {"PLANNED", "UNPLANNED"}:
                raise ValueError(f"Unsupported downtime type: {downtime_type}")
            body[self._field("downtime_type", "downtimeType")] = self._value(
                "downtime_type", kind
            )
        if description:
            body[self._field("status_description", "description")] = str(description)
        if started_at:
            body[self._field("started_at", "startedAt")] = str(started_at)
        response = self._execute(
            "create_asset_status",
            path={"assetId": asset_id},
            body=body,
            idempotency_key=idempotency_key,
        )
        # Asset-event IDs are optional; only an explicitly mapped response object
        # is inspected. No external envelope names belong in the controller.
        if "created_asset_status" not in self.objects:
            return {}
        record = self._object("created_asset_status", response)
        identifier = read_field(record, self._field("asset_status_id", "id"))
        if identifier is None:
            return {}
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, (str, int))
            or not str(identifier).strip()
            or len(str(identifier)) > 200
        ):
            raise IntegrationError(
                "Asset event returned an invalid mapped identifier", "INVALID_RESPONSE"
            )
        return {"id": identifier}

    def set_response_record_status(self, response_record_id, status):
        if not self.definition.capabilities.get("response_record_status"):
            return {}
        return self._execute(
            "update_response_record_status",
            path={"id": response_record_id},
            body={
                self._field("response_record_status", "status"): self._value(
                    "response_record_status", status
                )
            },
        )

    def assign_participants(self, response_record_id, team_id, user_ids):
        if not self.definition.capabilities.get("response_record_assignments"):
            return {}
        assignees = [self._assignee("TEAM", team_id)] if team_id is not None else []
        assignees.extend(self._assignee("USER", user_id) for user_id in user_ids)
        return self._execute(
            "update_response_record",
            path={"id": response_record_id},
            body={self._field("assignees", "assignees"): assignees},
        )

    def team_members(self, team_id):
        if not self.definition.capabilities.get("team_directory"):
            return []
        records = self._paged_collection(
            "members", "list_team_members", path={"id": team_id}
        )
        result = []
        for record in records:
            identifier = read_field(record, self._field("id", "id"))
            if identifier is None:
                continue
            result.append(
                {
                    "id": identifier,
                    "displayName": self._record_name(record) or f"User #{identifier}",
                }
            )
        return result

    def _paged_collection(self, collection, operation, path=None, query=None):
        """Read a bounded cursor-paginated directory without looping on bad cursors."""
        from .directory import read_directory

        return read_directory(self, collection, operation, path, query)

    def _cache_directory(self, teams, conversations, users):
        for resource, items in (
            ("team", teams),
            ("conversation", conversations),
            ("user", users),
        ):
            if items is None:
                continue
            resolved = {}
            for item in items:
                name, identifier = (
                    self._record_name(item),
                    read_field(item, self._field("id", "id")),
                )
                if name and identifier is not None:
                    key = name.casefold()
                    # None marks an ambiguous name. Never silently choose the
                    # last person/group returned by an external directory.
                    if key in resolved and resolved[key] != identifier:
                        resolved[key] = None
                    else:
                        resolved[key] = identifier
            # Replace this bounded snapshot instead of accumulating stale names
            # for the lifetime of an unattended kiosk.
            self.name_cache[resource] = resolved

    def _cached_identifier(self, resource, wanted):
        identifier = self.name_cache[resource][wanted]
        if identifier is None:
            raise RuntimeError(
                f'Multiple configured {resource}s are named "{wanted}"; make the name unique'
            )
        return identifier

    def directory(self):
        teams = (
            self._paged_collection("teams", "list_teams")
            if self.definition.capabilities.get("team_directory")
            else []
        )
        conversations = (
            self._paged_collection("conversations", "list_conversations")
            if self._message_route("conversation")
            else []
        )
        users = (
            self._paged_collection("users", "list_users")
            if self.definition.capabilities.get("team_directory")
            or self._message_route("user")
            else []
        )
        self._cache_directory(teams, conversations, users)
        group_names = {
            self._record_name(item) for item in conversations if self._record_name(item)
        }
        user_names = {
            self._record_name(user) for user in users if self._message_route("user")
        }
        collisions = {name.casefold() for name in group_names} & {
            name.casefold() for name in user_names
        }
        targets = {
            ("conversation:" if name.casefold() in collisions else "") + name
            for name in group_names
        } | {
            ("user:" if name.casefold() in collisions else "") + name
            for name in user_names
            if name
        }
        return {
            "teams": sorted(
                {self._record_name(item) for item in teams if self._record_name(item)}
            ),
            "conversations": sorted(name for name in targets if name),
        }

    def add_response_record_comment(self, response_record_id, content):
        if not self.definition.capabilities.get("response_record_comments"):
            return {}
        return self._execute(
            "create_response_record_comment",
            path={"id": response_record_id},
            body={self._field("content", "content"): str(content)},
        )

    def _send_conversation(self, conversation_id, content):
        return self._execute(
            "send_conversation_message",
            path={"id": conversation_id},
            body={self._field("content", "content"): str(content)},
        )

    def _send_user(self, user_id, content):
        return self._execute(
            "send_user_message",
            path={"id": user_id},
            body={self._field("content", "content"): str(content)},
        )

    def send_message(self, target_name, content):
        if not self.definition.capabilities.get("messaging"):
            return {}
        wanted = str(target_name).strip().casefold()
        route, separator, unqualified = wanted.partition(":")
        explicit = route if separator and route in {"conversation", "user"} else None
        if explicit:
            wanted = unqualified.strip()
        if not wanted:
            raise RuntimeError("Configure a conversation or person name first")
        routes = [
            kind
            for kind in ("conversation", "user")
            if self._message_route(kind) and (not explicit or explicit == kind)
        ]
        if not routes:
            raise RuntimeError("The connector does not provide that messaging route")
        # Resolve all applicable directories before choosing. A group and person
        # with the same display name must never silently select the wrong target.
        for kind in routes:
            items = self._paged_collection(kind + "s", "list_" + kind + "s")
            self._cache_directory(
                None,
                items if kind == "conversation" else None,
                items if kind == "user" else None,
            )
        matches = [kind for kind in routes if wanted in self.name_cache[kind]]
        if len(matches) > 1:
            raise RuntimeError(
                "Recipient name matches both a group and a person; use conversation:Name or user:Name"
            )
        if matches == ["conversation"]:
            return self._send_conversation(
                self._cached_identifier("conversation", wanted), content
            )
        if matches == ["user"]:
            return self._send_user(self._cached_identifier("user", wanted), content)
        raise RuntimeError(
            f'No configured conversation or user named "{target_name}" was found'
        )

    def _message_route(self, kind):
        return (
            self.definition.capabilities.get("messaging")
            and f"send_{kind}_message" in self.operations
        )

    def resolve_name(self, resource, name):
        wanted = str(name).strip().casefold()
        if not wanted:
            raise RuntimeError(f"Configure a {resource} name first")
        if resource not in {"team", "conversation"}:
            raise RuntimeError(f"Unsupported lookup resource: {resource}")
        semantic = "list_teams" if resource == "team" else "list_conversations"
        items = self._paged_collection(resource + "s", semantic)
        matches = [
            item for item in items if self._record_name(item).casefold() == wanted
        ]
        if not matches:
            raise RuntimeError(f'No configured {resource} named "{name}" was found')
        if len(matches) > 1:
            raise RuntimeError(
                f'Multiple configured {resource}s are named "{name}"; make the name unique'
            )
        result = read_field(matches[0], self._field("id", "id"))
        self.name_cache[resource][wanted] = result
        return result
