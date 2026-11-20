"""P1a contract freeze: relay/contracts.py, protocol schemas, fixtures and registries agree."""
import dataclasses
import json
import os
import pathlib
import sys
import typing
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROTO = ROOT / "docs" / "remote-control" / "protocol"
FIXTURES = PROTO / "fixtures"
sys.path.insert(0, str(ROOT))

from relay import contracts as c  # noqa: E402

try:
    import jsonschema
except ImportError:  # CI sets REQUIRE_JSONSCHEMA=1, so this only skips locally
    if os.environ.get("REQUIRE_JSONSCHEMA") == "1":
        raise
    jsonschema = None
SKIP = "jsonschema is not installed: pip install --require-hashes -r requirements-dev.txt"

SCHEMAS = {name: json.loads((PROTO / f"{name}.schema.json").read_text()) for name in ("v1", "http-v1")}
DIRECTIONS = ("staff_to_relay", "relay_to_staff", "relay_to_device", "device_to_relay")
ABBR = {"staff_to_relay": "s2r", "relay_to_staff": "r2s", "relay_to_device": "r2d", "device_to_relay": "d2r"}
ACTORS = {"relay", "tablet", "desktop"}
REQUIRED_SCENARIOS = {
    "withheld-renewal", "delayed-detach-after-replacement", "reserved-op-denied", "wipe-expiry-during-audit",
    "release-between-reserve-and-execute", "late-ack-after-outcome-unknown", "invalidation-during-decode",
    "invalidation-between-frame_displayed-and-input-enable"}

# Every enum-valued $def is a contracts registry, and they must be equal.
REGISTRIES = {
    "v1": {
        "error_code": c.ERROR_CODES, "ack_error_code": c.ACK_ERROR_CODES, "session_end_code": c.SESSION_END_CODES,
        "terminal_reason": c.TERMINAL_REASONS, "tablet_terminal_reason": c.TABLET_TERMINAL_REASONS,
        "attach_mode": c.ATTACH_MODES, "live_attachment_state": c.LIVE_ATTACHMENT_STATES,
        "command_op": c.COMMAND_OPS, "device_command_op": c.DEVICE_COMMAND_OPS, "coordinate_op": c.COORDINATE_OPS,
        "command_outcome": c.COMMAND_OUTCOMES, "device_connection_state": c.DEVICE_CONNECTION_STATES,
        "lock_task_state": c.LOCK_TASK_STATES,
    },
    "http-v1": {
        "http_error_code": c.HTTP_ERROR_CODES, "enrollment_state": c.ENROLLMENT_STATES,
        "security_level": c.SECURITY_LEVELS,
    },
}


def load(path):
    return json.loads(path.read_text())


def walk(node, path=()):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (i,))


def message_defs(direction):
    return SCHEMAS["v1"]["$defs"][direction]["properties"]["type"]["enum"]


class Contracts(unittest.TestCase):
    def test_every_dataclass_is_frozen_and_listed(self):
        defined = {v for v in vars(c).values() if dataclasses.is_dataclass(v) and v.__module__ == c.__name__}
        self.assertEqual(defined, set(c.DATACLASSES))
        self.assertEqual({d.__name__ for d in defined}, {
            "Principal", "StaffSession", "WsAttachContext", "WsCommandContext", "HttpMgmtContext",
            "StepUpContext", "DeviceIdentity", "Decision", "AuditEvent"})
        for cls in defined:
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)
        p = c.Principal("https://issuer", "sub")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.subject = "other"

    def test_protocols(self):
        for proto in (c.SecurityServices, c.ConnectionCloser):
            self.assertTrue(getattr(proto, "_is_protocol", False), proto.__name__)
        self.assertEqual(set(typing.get_args(c.Ctx)),
                         {c.WsAttachContext, c.WsCommandContext, c.HttpMgmtContext, c.StepUpContext})

    def test_registries_are_closed_and_consistent(self):
        for name in dir(c):
            value = getattr(c, name)
            if name.isupper() and isinstance(value, tuple) and name != "DATACLASSES":
                self.assertEqual(len(value), len(set(value)), f"duplicate in {name}")
        self.assertEqual(set(c.TERMINAL_REASON_ORIGINS), set(c.TERMINAL_REASONS))
        self.assertEqual(set(c.HTTP_ERROR_STATUS), set(c.HTTP_ERROR_CODES))
        self.assertLessEqual(set(c.ACK_ERROR_CODES), set(c.ERROR_CODES))
        self.assertLessEqual(set(c.SESSION_END_CODES), set(c.ERROR_CODES))
        self.assertEqual(set(c.COMMAND_OPS), set(c.DEVICE_COMMAND_OPS) | {"wipe"} | set(c.RESERVED_OPS))
        self.assertFalse(set(c.DEVICE_COMMAND_OPS) & (set(c.RESERVED_OPS) | {"wipe"}))
        self.assertEqual(set(c.RESERVED_OPS), {"navigate", "enter_kiosk", "exit_kiosk"})
        self.assertLessEqual(set(c.COORDINATE_OPS), set(c.DEVICE_COMMAND_OPS))
        self.assertLessEqual(set(c.LIVE_ATTACHMENT_STATES), set(c.ATTACHMENT_STATES))
        self.assertFalse(set(c.COMMAND_OPS) & set(c.SESSION_OPS))
        self.assertEqual(c.ROLES, ("viewer", "operator", "admin"))

    def test_v1_md_documents_every_code_and_reason(self):
        doc = (PROTO / "v1.md").read_text()
        for code in c.ERROR_CODES + c.HTTP_ERROR_CODES + c.TERMINAL_REASONS:
            self.assertIn(f"| `{code}` |", doc, code)


class Registries(unittest.TestCase):
    def test_schema_enums_equal_contracts(self):
        for schema, regs in REGISTRIES.items():
            defs = SCHEMAS[schema]["$defs"]
            enum_defs = {k for k, v in defs.items() if "enum" in v}
            self.assertEqual(enum_defs, set(regs), schema)
            for name, values in regs.items():
                self.assertEqual(defs[name]["enum"], list(values), f"{schema} $defs/{name}")

    def test_inline_enums_are_registry_subsets(self):
        for schema, regs in REGISTRIES.items():
            sets = [set(v) for v in regs.values()]
            if schema == "v1":
                sets += [set(message_defs(d)) for d in DIRECTIONS]
            for path, node in walk(SCHEMAS[schema]):
                if path and path[-1] == "enum" and isinstance(node, list):
                    self.assertTrue(any(set(node) <= s for s in sets), f"{schema} {path}: {node}")

    def test_closed_schemas(self):
        for schema in SCHEMAS.values():
            for path, node in walk(schema):
                if path in {("$defs", d) for d in DIRECTIONS}:
                    continue  # type dispatcher; each branch it selects is closed
                if isinstance(node, dict) and node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False, path)

    def test_every_message_has_a_def(self):
        defs = SCHEMAS["v1"]["$defs"]
        for direction in DIRECTIONS:
            for t in message_defs(direction):
                self.assertEqual(defs[f"{ABBR[direction]}.{t}"]["properties"]["type"], {"const": t})


@unittest.skipIf(jsonschema is None, SKIP)
class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for schema in SCHEMAS.values():
            jsonschema.Draft202012Validator.check_schema(schema)

    def validator(self, schema, definition=None):
        s = dict(SCHEMAS[schema])
        if definition is not None:
            s.pop("anyOf", None)
            s["$ref"] = f"#/$defs/{definition}"
        return jsonschema.Draft202012Validator(s)

    def fixtures(self, kind):
        files = sorted((FIXTURES / kind).glob("*.json"))
        self.assertTrue(files, kind)
        return files

    def test_valid(self):
        covered = set()
        for f in self.fixtures("valid"):
            with self.subTest(f.name):
                fx = load(f)
                self.assertEqual(set(fx), {"schema", "def", "instance"})
                errors = list(self.validator(fx["schema"], fx["def"]).iter_errors(fx["instance"]))
                self.assertEqual([e.message for e in errors], [])
                if fx["def"] in DIRECTIONS:
                    self.assertTrue(self.validator("v1").is_valid(fx["instance"]))
                    covered.add(f"{ABBR[fx['def']]}.{fx['instance']['type']}")
                else:
                    covered.add(fx["def"])
        expected = {f"{ABBR[d]}.{t}" for d in DIRECTIONS for t in message_defs(d)} | {"frame_header"}
        expected |= {k for k, v in SCHEMAS["http-v1"]["$defs"].items() if "." in k or k == "error_body"}
        self.assertEqual(expected - covered, set(), "message types without a valid fixture")

    def test_invalid(self):
        for f in self.fixtures("invalid"):
            with self.subTest(f.name):
                fx = load(f)
                self.assertEqual(set(fx), {"schema", "def", "defect", "instance"})
                errors = list(self.validator(fx["schema"], fx["def"]).iter_errors(fx["instance"]))
                self.assertTrue(errors, "fixture unexpectedly valid")
                if fx["def"] in DIRECTIONS:
                    self.assertFalse(self.validator("v1").is_valid(fx["instance"]), "valid in another direction")
                d = fx["defect"]
                leaves, stack = [], list(errors)
                while stack:
                    e = stack.pop()
                    leaves.append(e)
                    stack.extend(e.context or ())
                hit = [e for e in leaves if e.validator == d["keyword"] and list(e.absolute_path) == d["path"]
                       and d.get("missing", "") in e.message]
                seen = [(e.validator, list(e.absolute_path), e.message) for e in leaves]
                self.assertTrue(hit, f"expected {d}, got {seen}")

    def test_scenarios(self):
        files = self.fixtures("scenarios")
        self.assertEqual({f.stem for f in files}, REQUIRED_SCENARIOS)
        header = self.validator("v1", "frame_header")
        by_dir = {d: self.validator("v1", d) for d in DIRECTIONS}
        for f in files:
            with self.subTest(f.name):
                sc = load(f)
                self.assertEqual(set(sc), {"name", "title", "spec", "description", "steps"})
                self.assertEqual(sc["name"], f.stem)
                self.assertTrue(sc["steps"])
                for i, step in enumerate(sc["steps"]):
                    kind = (set(step) & {"send", "frame", "local", "expect", "absent"})
                    self.assertEqual(len(kind), 1, (i, step))
                    kind = kind.pop()
                    if kind == "send":
                        self.assertEqual(set(step), {"send", "message"})
                        errors = [e.message for e in by_dir[step["send"]].iter_errors(step["message"])]
                        self.assertEqual(errors, [], (i, step))
                    elif kind == "frame":
                        self.assertEqual(set(step), {"frame", "header"})
                        self.assertIn(step["frame"], ("device_to_relay", "relay_to_staff"))
                        self.assertTrue(header.is_valid(step["header"]), (i, step))
                    elif kind == "absent":
                        self.assertEqual(set(step), {"absent", "type", "why"})
                        self.assertIn(step["type"], message_defs(step["absent"]), (i, step))
                    else:
                        self.assertEqual(set(step), {kind, "event" if kind == "local" else "assert"})
                        self.assertIn(step[kind], ACTORS, (i, step))


if __name__ == "__main__":
    unittest.main()
