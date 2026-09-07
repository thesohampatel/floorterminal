import json
import tempfile
import unittest
from pathlib import Path

from floorterminal.integration import (
    DefinitionError,
    IntegrationDefinition,
    write_connector,
)
from floorterminal.integration.runtime import (
    IntegrationClient,
    IntegrationError,
    TransportResponse,
)
from floorterminal.integration.workflow import ConfiguredIntegration

ROOT = Path(__file__).resolve().parents[2]


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def send(self, prepared, timeout):
        self.requests.append(prepared)
        return self.responses.pop(0)


class IntegrationContractTests(unittest.TestCase):
    def definition(self, enabled=True):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["enabled"] = enabled
        data["connection"]["base_url"] = "https://service.example.test/v1"
        data["credentials"]["access_token"] = "offline-secret"
        data["credentials"]["tenant_id"] = "plant-a"
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "connector.json"
        path.write_text(json.dumps(data))
        return directory, IntegrationDefinition(path)

    def test_http_errors_accept_non_object_json_without_crashing(self):
        directory, definition = self.definition()
        try:
            for body in (
                b'["unavailable"]',
                b'"unavailable"',
                b"null",
                b"42",
                b"not JSON",
            ):
                with self.subTest(body=body):
                    client = IntegrationClient(
                        definition,
                        transport=FakeTransport([TransportResponse(400, {}, body)]),
                    )
                    with self.assertRaises(IntegrationError) as raised:
                        client.execute("user.list")
                    self.assertEqual(raised.exception.status, 400)
        finally:
            directory.cleanup()

    def test_error_details_redact_credentials_and_terminal_controls(self):
        directory, definition = self.definition()
        try:
            for body in (
                b'{"error":"Rejected offline-secret at plant-a"}',
                b'["Rejected offline-secret"]',
                b"Rejected offline-secret at plant-a\x1b[31m\x7f",
            ):
                with self.subTest(body=body):
                    client = IntegrationClient(
                        definition,
                        transport=FakeTransport([TransportResponse(400, {}, body)]),
                    )
                    with self.assertRaises(IntegrationError) as raised:
                        client.execute("user.list")
                    detail = str(raised.exception)
                    self.assertNotIn("offline-secret", detail)
                    self.assertNotIn("plant-a", detail)
                    self.assertNotIn(chr(27), detail)
                    self.assertNotIn(chr(127), detail)
        finally:
            directory.cleanup()

    def test_tracked_template_is_disabled_and_has_no_credentials(self):
        definition = IntegrationDefinition(ROOT / "connector.example.json")
        self.assertFalse(definition.enabled)
        self.assertFalse(any(definition.credentials.values()))

    def test_connector_write_is_atomic_private_and_validated(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "connector.json"
            path.write_text("{}")
            path.chmod(0o644)
            write_connector(data, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(root.glob("*.tmp")))
            self.assertEqual(
                IntegrationDefinition(path).display_name,
                data["identity"]["display_name"],
            )
            original = path.read_bytes()
            invalid = dict(data)
            invalid["schema_version"] = 999
            with self.assertRaises(DefinitionError):
                write_connector(invalid, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(root.glob("*.tmp")))

    def test_enabled_contract_requires_https(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["enabled"] = True
        data["connection"]["base_url"] = "http://unsafe.example.test"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(DefinitionError):
                IntegrationDefinition(path)

    def test_reserved_or_multiline_headers_are_rejected(self):
        for name, value in (("Host", "evil.test"), ("X-Test", "safe\r\ninjected")):
            data = json.loads((ROOT / "connector.example.json").read_text())
            data["operations"]["user.list"]["headers"] = {name: value}
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "connector.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(DefinitionError):
                    IntegrationDefinition(path)

    def test_incomplete_workflow_is_rejected_at_startup(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        del data["workflow"]["operations"]["create_response_record"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(DefinitionError):
                IntegrationDefinition(path)

    def test_response_record_capability_requires_remote_idempotency_guarantee(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        del data["operations"]["response_record.create"]["idempotency"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(DefinitionError, "idempotency"):
                IntegrationDefinition(path)

    def test_asset_status_capability_requires_remote_idempotency_guarantee(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        del data["operations"]["asset.status"]["idempotency"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(DefinitionError, "idempotency"):
                IntegrationDefinition(path)

    def test_asset_status_passes_idempotency_key_to_transport(self):
        directory, definition = self.definition()
        try:
            transport = FakeTransport([TransportResponse(201, {}, b'{"id":"as-1"}')])
            provider = ConfiguredIntegration(
                {"asset_id": "asset-1"}, transport=transport, definition=definition
            )
            provider.set_asset_status(
                "OFFLINE", "UNPLANNED", "Stopped", idempotency_key="asset-event-1"
            )
            self.assertEqual(
                transport.requests[0].headers["Idempotency-Key"], "asset-event-1"
            )
        finally:
            directory.cleanup()

    def test_idempotency_can_be_mapped_to_body_or_query(self):
        directory, definition = self.definition()
        try:
            operation = definition.data["operations"]["response_record.create"]
            operation["idempotency"] = {
                "location": "body",
                "name": "metadata.eventKey",
                "remote_guarantee": True,
            }
            request = IntegrationClient(definition).prepare(
                "response_record.create",
                body={"title": "Stopped"},
                idempotency_key="event-body-1",
            )
            self.assertEqual(
                json.loads(request.body)["metadata"]["eventKey"], "event-body-1"
            )
            operation["query_parameters"].append("request_key")
            operation["idempotency"] = {
                "location": "query",
                "name": "request_key",
                "remote_guarantee": True,
            }
            request = IntegrationClient(definition).prepare(
                "response_record.create",
                body={"title": "Stopped"},
                idempotency_key="event-query-1",
            )
            self.assertIn("request_key=event-query-1", request.url)
        finally:
            directory.cleanup()

    def test_disabled_capabilities_do_not_require_unrelated_operations(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["capabilities"].update(
            {
                "response_record_status": False,
                "response_record_comments": False,
                "response_record_assignments": False,
                "asset_status": False,
                "messaging": False,
                "team_directory": False,
            }
        )
        keep = {"create_response_record"}
        data["workflow"]["operations"] = {
            key: value
            for key, value in data["workflow"]["operations"].items()
            if key in keep
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            definition = IntegrationDefinition(path)
            self.assertTrue(definition.capabilities["response_records"])
            self.assertFalse(definition.capabilities["messaging"])

    def test_capability_values_must_be_boolean(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["capabilities"]["messaging"] = "yes"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(DefinitionError):
                IntegrationDefinition(path)

    def test_invalid_retry_policy_is_rejected(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["operations"]["team.list"]["retry"] = {
            "safe": False,
            "retry_on": [503],
            "max_attempts": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(DefinitionError, "retry.safe"):
                IntegrationDefinition(path)

    def test_request_uses_contract_auth_path_and_query(self):
        directory, definition = self.definition()
        transport = FakeTransport([TransportResponse(200, {}, b'{"teams":[]}')])
        try:
            client = IntegrationClient(definition, transport=transport)
            self.assertEqual(
                client.execute(
                    "team.members", path={"id": "A/B"}, query={"limit": 200}
                ),
                {"teams": []},
            )
            request = transport.requests[0]
            self.assertEqual(
                request.url,
                "https://service.example.test/v1/teams/A%2FB/members?limit=200",
            )
            self.assertEqual(request.headers["Authorization"], "Bearer offline-secret")
            self.assertEqual(request.headers["X-Tenant-Id"], "plant-a")
        finally:
            directory.cleanup()

    def test_declared_safe_retry_counts_every_transport_attempt(self):
        directory, definition = self.definition()
        definition.data["operations"]["team.list"]["retry"] = {
            "safe": True,
            "retry_on": [503],
            "network_errors": False,
            "max_attempts": 2,
            "backoff_seconds": 0,
        }
        transport = FakeTransport(
            [
                TransportResponse(503, {}, b'{"message":"busy"}'),
                TransportResponse(200, {}, b'{"teams":[]}'),
            ]
        )
        try:
            client = IntegrationClient(definition, transport=transport)
            result = client.execute("team.list", query={"limit": 1})
            self.assertEqual(result, {"teams": []})
            self.assertEqual(len(transport.requests), 2)
            self.assertEqual(client.app_window_used, 2)
        finally:
            directory.cleanup()

    def test_v2_derived_basic_auth_and_operation_headers(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["enabled"] = True
        data["connection"]["base_url"] = "https://service.example.test/v1"
        data["credentials"] = {"username": "tech", "password": "safe-pass"}
        data["authentication"] = {
            "type": "basic",
            "required_credentials": ["username", "password"],
            "optional_headers": [],
            "derived_credentials": {
                "basic_token": {
                    "template": "${username}:${password}",
                    "transform": "base64",
                }
            },
            "headers": {"Authorization": "Basic ${basic_token}"},
            "query": {},
            "body": {},
        }
        data["operations"]["team.list"]["headers"] = {"X-Method-Mode": "READ"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            definition = IntegrationDefinition(path)
            request = IntegrationClient(
                definition, transport=FakeTransport([])
            ).prepare("team.list", query={"limit": 5})
            self.assertEqual(
                request.headers["Authorization"], "Basic dGVjaDpzYWZlLXBhc3M="
            )
            self.assertEqual(request.headers["X-Method-Mode"], "READ")

    def test_disabled_template_allows_empty_derived_credential_sources(self):
        data = json.loads((ROOT / "connector.example.json").read_text())
        data["credentials"] = {"username": "", "password": ""}
        data["authentication"] = {
            "type": "basic",
            "required_credentials": ["username", "password"],
            "optional_headers": [],
            "derived_credentials": {
                "basic_token": {
                    "template": "${username}:${password}",
                    "transform": "base64",
                }
            },
            "headers": {"Authorization": "Basic ${basic_token}"},
            "query": {},
            "body": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connector.json"
            path.write_text(json.dumps(data))
            definition = IntegrationDefinition(path)
            client = IntegrationClient(definition, transport=FakeTransport([]))
            self.assertEqual(client.authentication_values["basic_token"], "")

    def test_v2_rpc_json_envelope_and_response_extraction(self):
        directory, definition = self.definition()
        operation = definition.data["operations"]["response_record.create"]
        operation["body"] = {
            "encoding": "json",
            "static": {"service": "work", "action": "create"},
            "payload_path": "parameters.record",
        }
        operation["response_body_path"] = "result"
        transport = FakeTransport(
            [TransportResponse(200, {}, b'{"result":{"id":"RECORD-RPC"}}')]
        )
        try:
            client = IntegrationClient(definition, transport=transport)
            result = client.execute(
                "response_record.create",
                body={"title": "Stopped"},
                idempotency_key="report-rpc-1",
            )
            payload = json.loads(transport.requests[0].body)
            self.assertEqual(payload["service"], "work")
            self.assertEqual(payload["parameters"]["record"]["title"], "Stopped")
            self.assertEqual(result, {"id": "RECORD-RPC"})
        finally:
            directory.cleanup()

    def test_v2_form_body_and_authentication_query(self):
        directory, definition = self.definition()
        definition.data["authentication"]["query"] = {"api_token": "${access_token}"}
        operation = definition.data["operations"]["response_record.create"]
        operation["query_parameters"].append("api_token")
        operation["body"] = {"encoding": "form"}
        try:
            request = IntegrationClient(
                definition, transport=FakeTransport([])
            ).prepare(
                "response_record.create",
                body={"title": "Line stopped", "priority": "HIGH"},
                idempotency_key="report-form-1",
            )
            self.assertIn("api_token=offline-secret", request.url)
            self.assertEqual(
                request.headers["Content-Type"], "application/x-www-form-urlencoded"
            )
            self.assertEqual(request.body, b"title=Line+stopped&priority=HIGH")
        finally:
            directory.cleanup()

    def test_v2_odata_query_aliases_and_collection_mapping(self):
        directory, definition = self.definition()
        operation = definition.data["operations"]["team.list"]
        operation["query_parameters"] = ["$top", "$skiptoken"]
        operation["query_aliases"] = {"limit": "$top", "cursor": "$skiptoken"}
        definition.data["workflow"]["collections"]["teams"] = "value"
        transport = FakeTransport(
            [
                TransportResponse(
                    200, {}, b'{"value":[{"id":"T1","name":"Engineering"}]}'
                )
            ]
        )
        try:
            workflow = ConfiguredIntegration(
                {}, transport=transport, definition=definition
            )
            result = workflow._collection(
                "teams",
                workflow._execute("list_teams", query={"limit": 25, "cursor": "abc"}),
            )
            self.assertEqual(result[0]["id"], "T1")
            self.assertIn("%24top=25", transport.requests[0].url)
            self.assertIn("%24skiptoken=abc", transport.requests[0].url)
        finally:
            directory.cleanup()

    def test_disabled_contract_never_reaches_transport(self):
        directory, definition = self.definition(False)
        transport = FakeTransport([])
        try:
            with self.assertRaises(IntegrationError):
                IntegrationClient(definition, transport=transport).execute(
                    "team.list", query={"limit": 1}
                )
            self.assertEqual(transport.requests, [])
        finally:
            directory.cleanup()

    def test_response_record_lifecycle_uses_semantic_operations(self):
        directory, definition = self.definition()
        transport = FakeTransport(
            [
                TransportResponse(201, {}, b'{"id":"RECORD-7"}'),
                TransportResponse(200, {}, b"{}"),
                TransportResponse(201, {}, b"{}"),
            ]
        )
        try:
            workflow = ConfiguredIntegration(
                {
                    "response_record_type": "REACTIVE",
                    "asset_id": "ASSET-1",
                    "location_id": "LOC-1",
                },
                transport=transport,
                definition=definition,
            )
            result = workflow.create_response_record(
                "Stopped",
                "Zone A",
                "TEAM-1",
                participant_ids=["USER-2"],
                idempotency_key="report-lifecycle-1",
            )
            workflow.set_response_record_status(result["id"], "IN_PROGRESS")
            workflow.add_response_record_comment(result["id"], "Engineer joined")
            self.assertEqual(
                [r.operation_id for r in transport.requests],
                [
                    "response_record.create",
                    "response_record.status",
                    "response_record.comment",
                ],
            )
            body = json.loads(transport.requests[0].body)
            self.assertEqual(body["assetId"], "ASSET-1")
            self.assertEqual(len(body["assignees"]), 2)
            self.assertEqual(
                transport.requests[0].headers["Idempotency-Key"],
                "report-lifecycle-1",
            )
        finally:
            directory.cleanup()

    def test_connector_controls_identifier_wire_types(self):
        directory, definition = self.definition()
        definition.data["workflow"]["field_types"] = {
            "asset_id": "integer",
            "location_id": "integer",
            "assignee_id": "integer",
        }
        transport = FakeTransport([TransportResponse(201, {}, b'{"id":17}')])
        try:
            workflow = ConfiguredIntegration(
                {
                    "response_record_type": "REACTIVE",
                    "asset_id": "41",
                    "location_id": "42",
                },
                transport=transport,
                definition=definition,
            )
            workflow.create_response_record(
                "Stopped",
                "Station A",
                "7",
                participant_ids=["8"],
                idempotency_key="numeric-identifiers-1",
            )
            body = json.loads(transport.requests[0].body)
            self.assertEqual(body["assetId"], 41)
            self.assertEqual(body["locationId"], 42)
            self.assertEqual([item["id"] for item in body["assignees"]], [7, 8])
        finally:
            directory.cleanup()

    def test_directory_lookup_searches_bounded_later_pages(self):
        directory, definition = self.definition()
        transport = FakeTransport(
            [
                TransportResponse(
                    200,
                    {},
                    b'{"teams":[{"id":1,"name":"Other"}],"nextCursor":"page-2"}',
                ),
                TransportResponse(
                    200, {}, b'{"teams":[{"id":2,"name":"Engineering"}]}'
                ),
            ]
        )
        try:
            workflow = ConfiguredIntegration(
                {"directory_max_pages": 3},
                transport=transport,
                definition=definition,
            )
            self.assertEqual(workflow.resolve_name("team", "Engineering"), 2)
            self.assertIn("cursor=page-2", transport.requests[1].url)
        finally:
            directory.cleanup()

    def test_optional_connector_identity_uses_mapped_object(self):
        directory, definition = self.definition()
        definition.data["identity"]["authenticated_subject_id"] = "22"
        definition.data["workflow"]["objects"]["loaded_identity"] = "user"
        transport = FakeTransport(
            [TransportResponse(200, {}, b'{"user":{"id":22,"name":"API Account"}}')]
        )
        try:
            workflow = ConfiguredIntegration(
                {}, transport=transport, definition=definition
            )
            self.assertEqual(workflow.load_identity(), "API Account")
            self.assertTrue(transport.requests[0].url.endswith("/users/22"))
        finally:
            directory.cleanup()

    def test_team_members_are_normalized_through_connector_name_fields(self):
        directory, definition = self.definition()
        definition.data["workflow"]["fields"].update(
            id="subjectId", first_name="given", last_name="family"
        )
        transport = FakeTransport(
            [
                TransportResponse(
                    200,
                    {},
                    b'{"members":[{"subjectId":9,"given":"Alex","family":"Morgan"}]}',
                )
            ]
        )
        try:
            workflow = ConfiguredIntegration(
                {"directory_max_pages": 1},
                transport=transport,
                definition=definition,
            )
            self.assertEqual(
                workflow.team_members("team-1"),
                [{"id": 9, "displayName": "Alex Morgan"}],
            )
        finally:
            directory.cleanup()

    def test_connector_controls_external_fields_values_and_query_names(self):
        directory, definition = self.definition()
        definition.data["workflow"]["fields"]["title"] = "subject"
        definition.data["workflow"]["fields"]["response_record_id"] = "workId"
        definition.data["workflow"]["objects"]["created_response_record"] = "result"
        definition.data["workflow"]["fields"]["response_record_status"] = "state"
        definition.data["workflow"]["values"]["response_record_status"][
            "IN_PROGRESS"
        ] = "ACTIVE"
        definition.data["operations"]["team.list"]["query_parameters"] = ["page_size"]
        definition.data["operations"]["team.list"]["query_aliases"] = {
            "limit": "page_size"
        }
        transport = FakeTransport(
            [
                TransportResponse(201, {}, b'{"result":{"workId":"RECORD-8"}}'),
                TransportResponse(200, {}, b"{}"),
                TransportResponse(200, {}, b'{"teams":[]}'),
            ]
        )
        try:
            workflow = ConfiguredIntegration(
                {}, transport=transport, definition=definition
            )
            created = workflow.create_response_record(
                "Stopped", "Zone A", "TEAM-1", idempotency_key="report-fields-1"
            )
            workflow.set_response_record_status("RECORD-8", "IN_PROGRESS")
            workflow._execute("list_teams", query={"limit": 50})
            self.assertEqual(
                json.loads(transport.requests[0].body)["subject"], "Stopped"
            )
            self.assertEqual(created["id"], "RECORD-8")
            self.assertEqual(
                json.loads(transport.requests[1].body), {"state": "ACTIVE"}
            )
            self.assertTrue(transport.requests[2].url.endswith("?page_size=50"))
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
