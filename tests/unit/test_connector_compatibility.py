"""Neutral wire-contract fixtures. No service endpoints, credentials or sockets."""

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from floorterminal.integration import DefinitionError, IntegrationDefinition
from floorterminal.integration.discovery import ConnectorCandidate, test_connector
from floorterminal.integration.runtime import (
    IntegrationClient,
    IntegrationError,
    TransportResponse,
)
from floorterminal.integration.workflow import ConfiguredIntegration
from floorterminal.services.delivery import retry_safe

ROOT = Path(__file__).resolve().parents[2]


class Wire:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def send(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(data, status=200, headers=None):
    return TransportResponse(status, headers or {}, json.dumps(data).encode())


class ConnectorCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "connector.json"
        self.data = json.loads((ROOT / "connector.example.json").read_text())
        self.data["enabled"] = True
        self.data["connection"]["base_url"] = "https://operations.example.test/api"
        self.data["credentials"]["access_token"] = "offline-fixture-only"
        self.data["connection"]["requests_per_minute"] = 1000
        guard = mock.patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def definition(self):
        self.path.write_text(json.dumps(self.data))
        return IntegrationDefinition(self.path)

    def provider(self, wire, **config):
        return ConfiguredIntegration(
            config, definition=self.definition(), transport=wire
        )

    def hold(self, operation):
        raw = self.data["operations"][operation]
        raw.pop("idempotency", None)
        raw["delivery"] = {"ambiguous_result": "hold"}

    def test_keyed_assignees_match_declared_create_and_crew_update_shapes(self):
        self.data["workflow"]["fields"].update(
            team_assignee_id="teamId", user_assignee_id="userId"
        )
        self.data["workflow"]["field_types"]["assignee_id"] = "integer"
        wire = Wire(response({"id": 19}, 201), response({}), response({}))
        app = self.provider(wire)
        app.create_response_record(
            "Stop",
            "Fault",
            "31",
            participant_ids=["32", "33"],
            idempotency_key="crew-event",
        )
        app.assign_participants(19, "31", ["33", "34"])
        app.assign_participants(19, None, [])
        self.assertEqual(
            json.loads(wire.requests[0].body)["assignees"],
            [
                {"teamId": 31},
                {"userId": 32},
                {"userId": 33},
            ],
        )
        self.assertEqual(
            json.loads(wire.requests[1].body)["assignees"],
            [
                {"teamId": 31},
                {"userId": 33},
                {"userId": 34},
            ],
        )
        self.assertEqual(json.loads(wire.requests[2].body)["assignees"], [])

    def test_partial_or_ambiguous_keyed_assignments_are_rejected(self):
        for fields in (
            {"team_assignee_id": "teamId"},
            {"team_assignee_id": "id", "user_assignee_id": "id"},
            {"team_assignee_id": "", "user_assignee_id": "userId"},
        ):
            self.data["workflow"]["fields"].pop("team_assignee_id", None)
            self.data["workflow"]["fields"].pop("user_assignee_id", None)
            self.data["workflow"]["fields"].update(fields)
            with self.subTest(fields=fields), self.assertRaises(DefinitionError):
                self.definition()

    def test_structured_failure_metadata_keeps_arbitrary_station_names_literal(self):
        self.data["workflow"]["fields"].update(
            failure_details="externalData.failures",
            asset_ids="externalData.assets",
            location_ids="externalData.locations",
        )
        self.data["workflow"]["field_types"].update(
            asset_ids="integer", location_ids="integer"
        )
        details = [
            {
                "station": "OP.10 / A",
                "reasons": ["Pressure.low", "Others"],
                "note": "Guard checked",
            }
        ]
        wire = Wire(response({"id": 19}, 201))
        app = self.provider(
            wire,
            asset_id="",
            location_id="",
            asset_ids=["1", "2"],
            location_ids=["3", "4"],
            failure_details=details,
        )
        app.create_response_record(
            "Two cells", "Independent impact", None, idempotency_key="multi-cell-event"
        )
        body = json.loads(wire.requests[0].body)
        self.assertEqual(
            body["externalData"],
            {"failures": details, "assets": [1, 2], "locations": [3, 4]},
        )
        self.assertNotIn("assetId", body)
        self.assertNotIn("locationId", body)

    def test_structured_details_cannot_be_coerced_to_an_invalid_scalar(self):
        self.data["workflow"]["field_types"]["failure_details"] = "string"
        with self.assertRaisesRegex(DefinitionError, "structured"):
            self.definition()

    def test_external_reference_upsert_stable_path_and_nested_result(self):
        raw = self.data["operations"]["response_record.create"]
        raw.update(
            method="PATCH",
            path="/tickets/by-reference/{event_key}",
            idempotency={
                "location": "path",
                "name": "event_key",
                "remote_guarantee": True,
            },
        )
        self.data["workflow"]["objects"]["created_response_record"] = "ticket"
        self.data["workflow"]["field_types"].update(
            asset_id="integer", location_id="integer", assignee_id="integer"
        )
        wire = Wire(
            response({"ticket": {"id": 17}}, 201), response({"ticket": {"id": 17}})
        )
        app = self.provider(wire, asset_id="21", location_id="22")
        for _ in range(2):
            result = app.create_response_record(
                "Stopped",
                "Zone A",
                "31",
                participant_ids=["32"],
                idempotency_key="fixed-event",
            )
            self.assertEqual(result["id"], 17)
        self.assertEqual(wire.requests[0], wire.requests[1])
        request = wire.requests[0]
        self.assertTrue(request.url.endswith("/tickets/by-reference/fixed-event"))
        self.assertNotIn("Idempotency-Key", request.headers)
        body = json.loads(request.body)
        self.assertEqual([item["id"] for item in body["assignees"]], [31, 32])
        self.assertEqual(body["assetId"], 21)
        self.assertTrue(retry_safe(app, "create_response_record"))

    def test_native_creation_and_asset_history_can_explicitly_hold_uncertainty(self):
        for operation in ("response_record.create", "asset.status"):
            self.hold(operation)
        wire = Wire(
            response({"id": 17}, 200), response({"stateEvent": {"id": 18}}, 201)
        )
        app = self.provider(wire, asset_id="21")
        self.assertEqual(
            app.create_response_record("Stopped", "Zone A", "31")["id"], 17
        )
        app.set_asset_status(
            "OFFLINE", "UNPLANNED", "Affected station: A", "2026-01-01T10:00:00Z"
        )
        self.assertFalse(retry_safe(app, "create_response_record"))
        self.assertFalse(retry_safe(app, "set_asset_status"))
        self.assertNotIn("Idempotency-Key", wire.requests[-1].headers)
        self.assertEqual(
            json.loads(wire.requests[-1].body)["startedAt"], "2026-01-01T10:00:00Z"
        )

    def test_optional_message_idempotency_is_validated(self):
        raw = self.data["operations"]["user.message"]
        for policy in (
            {"location": "header", "name": "X-Event", "remote_guarantee": False},
            {
                "location": "header",
                "name": "Transfer-Encoding",
                "remote_guarantee": True,
            },
            {"location": "path", "name": "missing", "remote_guarantee": True},
        ):
            with self.subTest(policy=policy):
                raw["idempotency"] = policy
                with self.assertRaises(DefinitionError):
                    self.definition()

    def test_hold_cannot_claim_safe_retry_or_idempotency(self):
        self.hold("asset.status")
        self.data["operations"]["asset.status"]["retry"] = {"safe": True}
        with self.assertRaises(DefinitionError):
            self.definition()

    def test_idempotency_cannot_replace_the_target_asset(self):
        self.data["operations"]["asset.status"]["idempotency"] = {
            "location": "path",
            "name": "assetId",
            "remote_guarantee": True,
        }
        with self.assertRaises(DefinitionError):
            self.provider(Wire(), asset_id="21").set_asset_status(
                "OFFLINE", idempotency_key="event-1"
            )

    def test_schema_version_boolean_is_not_version_one(self):
        self.data["schema_version"] = True
        with self.assertRaises(DefinitionError):
            self.definition()

    def test_malformed_url_cannot_crash_connector_discovery(self):
        from floorterminal.integration.discovery import discover_connectors

        for url in (
            "https://[invalid",
            "https://service.example.test:wrong",
            "https://:credential@service.example.test",
        ):
            with self.subTest(url=url):
                self.data["connection"]["base_url"] = url
                self.path.write_text(json.dumps(self.data))
                inventory = discover_connectors(self.path.parent)
                self.assertEqual(len(inventory.candidates), 1)
                self.assertFalse(inventory.candidates[0].valid)

    def test_directory_page_limit_never_resolves_a_partial_unique_name(self):
        wire = Wire(
            response({"teams": [{"id": 1, "name": "Crew"}], "nextCursor": "more"})
        )
        app = self.provider(wire, directory_max_pages=1)
        for _ in range(2):
            with self.assertRaisesRegex(IntegrationError, "incomplete"):
                app.resolve_name("team", "Crew")
        self.assertEqual(len(wire.requests), 1)
        self.assertNotIn("crew", app.name_cache["team"])

    def test_directory_repeated_cursor_is_not_a_complete_directory(self):
        wire = Wire(
            response({"teams": [], "nextCursor": "same"}),
            response({"teams": [], "nextCursor": "same"}),
        )
        with self.assertRaisesRegex(IntegrationError, "repeated"):
            self.provider(wire)._paged_collection("teams", "list_teams")

    def test_directory_page_size_alias_and_no_undeclared_filter(self):
        self.data["operations"]["conversation.list"].update(
            query_parameters=["count", "after"],
            query_aliases={"limit": "count", "cursor": "after"},
            directory={"page_size": 50},
        )
        wire = Wire(response({"conversations": [{"id": 4, "name": "Support"}]}))
        self.assertEqual(self.provider(wire).resolve_name("conversation", "Support"), 4)
        self.assertTrue(wire.requests[0].url.endswith("?count=50"))

    def test_directory_without_paging_accepts_root_array(self):
        self.data["operations"]["team.list"]["query_parameters"] = []
        self.data["workflow"]["collections"]["teams"] = ""
        wire = Wire(response([{"id": 3, "name": "Crew"}]))
        self.assertEqual(self.provider(wire).resolve_name("team", "Crew"), 3)
        self.assertNotIn("?", wire.requests[0].url)

    def test_missing_collection_and_invalid_id_fail_closed(self):
        for data in (
            {"wrong": []},
            {"teams": [None]},
            {"teams": [{"name": "Crew"}]},
            {"teams": [{"id": True, "name": "Crew"}]},
        ):
            with self.subTest(data=data), self.assertRaises(IntegrationError):
                self.provider(Wire(response(data))).resolve_name("team", "Crew")

    def test_null_name_falls_back_to_real_name(self):
        app = self.provider(
            Wire(
                response(
                    {
                        "members": [
                            {
                                "id": 4,
                                "name": None,
                                "firstName": "Alex",
                                "lastName": "Smith",
                            }
                        ]
                    }
                )
            )
        )
        self.assertEqual(
            app.team_members("1"), [{"id": 4, "displayName": "Alex Smith"}]
        )

    def test_group_only_or_person_only_messaging(self):
        for kind, other in (("conversation", "user"), ("user", "conversation")):
            with self.subTest(kind=kind):
                original = dict(self.data["workflow"]["operations"])
                self.data["workflow"]["operations"].pop(f"send_{other}_message")
                wire = Wire(
                    response({kind + "s": [{"id": 9, "name": "Support"}]}),
                    response({}, 201),
                )
                self.provider(wire).send_message("Support", "Please attend Zone A")
                self.assertEqual(wire.requests[-1].operation_id, kind + ".message")
                self.data["workflow"]["operations"] = original

    def test_cross_directory_collision_requires_explicit_recipient(self):
        wire = Wire(
            response({"conversations": [{"id": 4, "name": "Support"}]}),
            response({"users": [{"id": 5, "name": "SUPPORT"}]}),
            response({}, 201),
        )
        app = self.provider(wire)
        with self.assertRaisesRegex(RuntimeError, "both"):
            app.send_message("Support", "Do not misroute")
        self.assertEqual(len(wire.requests), 2)
        app.send_message("user:Support", "Verified recipient")
        self.assertTrue(wire.requests[-1].url.endswith("/users/5/messages"))

    def test_corrected_directory_replaces_stale_ambiguous_recipient(self):
        wire = Wire(
            response({"conversations": [{"id": 4, "name": "Support"}]}),
            response({}, 201),
        )
        app = self.provider(wire)
        app.name_cache["conversation"]["support"] = None
        app.send_message("conversation:Support", "Verified recipient")
        self.assertTrue(wire.requests[-1].url.endswith("/conversations/4/messages"))

    def test_unexpected_success_is_not_a_retryable_message_failure(self):
        wire = Wire(
            response({"conversations": [{"id": 4, "name": "Support"}]}),
            response({"private_response": "must not appear in error"}, 202),
        )
        app = self.provider(wire)
        with self.assertRaises(IntegrationError) as raised:
            app.send_message("conversation:Support", "Verify once")
        self.assertEqual(raised.exception.code, "INVALID_RESPONSE")
        self.assertEqual(raised.exception.status, 202)
        self.assertNotIn("private_response", str(raised.exception))
        self.assertEqual(len(wire.requests), 2)

    def test_strict_numeric_coercion(self):
        app = self.provider(Wire())
        app.field_types.update(asset_id="integer", assignee_id="number")
        for field, value in (
            ("asset_id", 1.5),
            ("asset_id", True),
            ("asset_id", float("inf")),
            ("assignee_id", "NaN"),
            ("assignee_id", "Infinity"),
        ):
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(RuntimeError),
            ):
                app._typed(field, value)

    def test_wrong_create_mapping_cannot_fall_back_to_an_unrelated_id(self):
        self.data["workflow"]["fields"]["response_record_id"] = "ticketId"
        app = self.provider(Wire(response({"id": 4}, 201)))
        with self.assertRaisesRegex(IntegrationError, "mapped record identifier"):
            app.create_response_record(
                "Stopped", "Zone A", "1", idempotency_key="event-1"
            )

    def test_asset_event_response_is_mapped_before_controller_receives_it(self):
        self.data["workflow"]["objects"]["created_asset_status"] = "event"
        self.data["workflow"]["fields"]["asset_status_id"] = "sequence"
        app = self.provider(
            Wire(response({"event": {"sequence": 9}}, 201)), asset_id="21"
        )
        result = app.set_asset_status("ONLINE", idempotency_key="event-1")
        self.assertEqual(result, {"id": 9})

    def test_positive_name_cache_does_not_outlive_directory_ttl(self):
        wire = Wire(
            response({"teams": [{"id": 1, "name": "Crew"}]}),
            response({"teams": [{"id": 2, "name": "Crew"}]}),
        )
        app = self.provider(wire)
        self.assertEqual(app.resolve_name("team", "Crew"), 1)
        for value in app.directory_progress.values():
            value["expires"] = 0
        self.assertEqual(app.resolve_name("team", "Crew"), 2)

    def test_nested_request_metadata_and_directory_leaves(self):
        fields = self.data["workflow"]["fields"]
        fields.update(
            group_ids="metadata.groups",
            affected_stations="metadata.stations",
            id="subject.id",
            name="subject.name",
            next_cursor="paging.next",
        )
        wire = Wire(
            response({"id": 7}, 201),
            response(
                {
                    "teams": [
                        {"subject": {"id": 3, "name": "Crew", "private": "not cached"}}
                    ],
                    "paging": {"next": None},
                }
            ),
        )
        app = self.provider(wire, group_ids=["cell-a"], affected_stations=["A", "B"])
        app.create_response_record("Stopped", "Zone A", "1", idempotency_key="event-1")
        self.assertEqual(
            json.loads(wire.requests[0].body)["metadata"],
            {"groups": ["cell-a"], "stations": ["A", "B"]},
        )
        self.assertEqual(app.resolve_name("team", "Crew"), 3)
        self.assertNotIn("private", json.dumps(app.directory_progress))

    def test_url_templates_dot_segments_fragments_and_error_success_codes_rejected(
        self,
    ):
        original = self.data["operations"]["team.list"]["path"]
        for path in ("/../teams", "/%2e%2e/teams", "/teams#hidden", "/teams\n"):
            self.data["operations"]["team.list"]["path"] = path
            with self.subTest(path=path), self.assertRaises(DefinitionError):
                self.definition()
        self.data["operations"]["team.list"]["path"] = original
        self.data["operations"]["team.list"]["success_codes"] = [401]
        with self.assertRaises(DefinitionError):
            self.definition()
        self.data["operations"]["team.list"]["success_codes"] = [200]
        self.data["connection"]["base_url"] = "https://${access_token}.example.test"
        with self.assertRaises(DefinitionError):
            self.definition()

    def test_path_values_cannot_escape_the_resource(self):
        client = IntegrationClient(self.definition())
        for value in (".", "..", "hidden\x00"):
            with self.subTest(value=value), self.assertRaises(DefinitionError):
                client.prepare("identity.get", path={"id": value})

    def test_query_authentication_cannot_be_overwritten(self):
        self.data["authentication"]["query"] = {"token": "${access_token}"}
        self.data["operations"]["team.list"]["query_parameters"].append("token")
        with self.assertRaises(DefinitionError):
            IntegrationClient(self.definition()).prepare(
                "team.list", query={"token": "different"}
            )

    def test_remote_errors_redact_literal_and_url_encoded_authentication(self):
        self.data["authentication"]["headers"] = {
            "Authorization": "Bearer literal-sensitive"
        }
        self.data["authentication"]["query"] = {"auth": "query-sensitive"}
        self.data["authentication"]["body"] = {"auth": "body-sensitive"}
        self.data["operations"]["team.list"]["query_parameters"].append("auth")
        self.data["credentials"]["access_token"] = "fixture/secret+value"
        wire = Wire(
            response(
                {
                    "message": "literal-sensitive query-sensitive body-sensitive fixture%2Fsecret%2Bvalue"
                },
                401,
            )
        )
        with self.assertRaises(IntegrationError) as caught:
            IntegrationClient(self.definition(), transport=wire).execute("team.list")
        for value in (
            "literal-sensitive",
            "query-sensitive",
            "body-sensitive",
            "fixture%2Fsecret%2Bvalue",
        ):
            self.assertNotIn(value, str(caught.exception))

    def test_bad_shapes_are_readable_validation_errors(self):
        for section in ("retry", "body", "query_aliases", "idempotency", "delivery"):
            for value in (None, [], "wrong"):
                with self.subTest(section=section, value=value):
                    self.data["operations"]["user.message"][section] = value
                    with self.assertRaises(DefinitionError):
                        self.definition()
                    del self.data["operations"]["user.message"][section]

    def test_request_schema_enforces_bounds_and_rejects_unsupported_rules(self):
        raw = self.data["operations"]["user.message"]
        raw["body_schema"] = {
            "type": "object",
            "properties": {"content": {"type": "string", "maxLength": 3}},
        }
        with self.assertRaises(DefinitionError):
            IntegrationClient(self.definition()).prepare(
                "user.message", path={"id": 5}, body={"content": "long"}
            )
        raw["body_schema"]["pattern"] = ".*"
        with self.assertRaises(DefinitionError):
            self.definition()

    def test_json_response_duplicate_keys_and_nonfinite_numbers_rejected(self):
        for payload in (
            b'{"id":1,"id":2}',
            b'{"value":NaN}',
            b'{"value":1e999}',
            b"[" * 1100,
        ):
            with (
                self.subTest(payload=payload[:40]),
                self.assertRaises(IntegrationError),
            ):
                IntegrationClient(
                    self.definition(),
                    transport=Wire(TransportResponse(200, {}, payload)),
                ).execute("team.list")

    def test_lowercase_quota_headers_pause_before_next_request(self):
        wire = Wire(
            response(
                {},
                headers={
                    "x-rate-limit-limit": "100",
                    "x-rate-limit-remaining": "0",
                    "x-rate-limit-reset": "60",
                },
            )
        )
        client = IntegrationClient(self.definition(), transport=wire)
        client.execute("team.list")
        with self.assertRaises(IntegrationError) as caught:
            client.execute("team.list")
        self.assertEqual(caught.exception.code, "RATE_LIMITED")
        self.assertEqual(len(wire.requests), 1)

    def test_diagnostic_never_retries_or_claims_write_verification(self):
        self.data["operations"]["user.list"]["retry"] = {
            "safe": True,
            "retry_on": [503],
            "network_errors": True,
            "max_attempts": 3,
        }
        definition = self.definition()
        wire = Wire(response({"error": "Unavailable"}, 503))
        candidate = ConnectorCandidate(self.path, definition)
        result = test_connector(candidate, transport=wire)
        self.assertFalse(result.success)
        self.assertEqual(len(wire.requests), 1)
        result = test_connector(candidate, transport=Wire(response({"users": []})))
        self.assertTrue(result.success)
        self.assertIn("still require commissioning", result.message)


if __name__ == "__main__":
    unittest.main()
