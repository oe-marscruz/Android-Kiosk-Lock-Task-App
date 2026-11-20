"""Shared relay contracts (ARCHITECTURE.md v0.6 §2.1, §3.3, §3.4, §4). Frozen at P1a.

Types and closed registries only; no behaviour. The wire registries here must equal
the enums in docs/remote-control/protocol/v1.schema.json and http-v1.schema.json
(tests/test_protocol_fixtures.py enforces this). Changing anything needs lead review,
coordinated consumers and fixtures; an incompatible change needs a new protocol version.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Mapping, Protocol, get_args

PROTOCOL_VERSION: Literal[1] = 1

# ---------------------------------------------------------------- roles, modes, states

Role = Literal["viewer", "operator", "admin"]
ROLES: tuple[Role, ...] = get_args(Role)  # cumulative, lowest first (§3.3)

AttachMode = Literal["status", "kiosk"]
ATTACH_MODES: tuple[AttachMode, ...] = get_args(AttachMode)

AttachmentState = Literal["none", "status", "pending_approval", "granted", "released"]
ATTACHMENT_STATES: tuple[AttachmentState, ...] = get_args(AttachmentState)

# States an attach_result can report: a live attachment the caller now holds.
LiveAttachmentState = Literal["status", "pending_approval", "granted"]
LIVE_ATTACHMENT_STATES: tuple[LiveAttachmentState, ...] = get_args(LiveAttachmentState)

DeviceConnectionState = Literal["online", "offline"]
DEVICE_CONNECTION_STATES: tuple[DeviceConnectionState, ...] = get_args(DeviceConnectionState)

LockTaskState = Literal["NONE", "LOCKED", "PINNED"]  # ActivityManager.LOCK_TASK_MODE_*
LOCK_TASK_STATES: tuple[LockTaskState, ...] = get_args(LockTaskState)

# cmd_result.state. Ack mapping in §4: ok, RESERVATION_EXPIRED → rejected_expired,
# other negative → failed; only an attempted send with no definitive ack is outcome_unknown.
CommandOutcome = Literal["ok", "failed", "rejected_expired", "outcome_unknown"]
COMMAND_OUTCOMES: tuple[CommandOutcome, ...] = get_args(CommandOutcome)

EnrollmentState = Literal["pending", "approved", "active", "rejected", "expired", "revoked", "abandoned"]
ENROLLMENT_STATES: tuple[EnrollmentState, ...] = get_args(EnrollmentState)

SecurityLevel = Literal["strongbox", "tee", "software", "unknown"]
SECURITY_LEVELS: tuple[SecurityLevel, ...] = get_args(SecurityLevel)

# ---------------------------------------------------------------- ops

CoordinateOp = Literal["tap", "swipe", "long_press"]
COORDINATE_OPS: tuple[CoordinateOp, ...] = get_args(CoordinateOp)

# Ops the relay may forward to a tablet in a plain `cmd`. Never wipe (two-phase only).
DeviceCommandOp = Literal[
    "tap", "swipe", "long_press", "kiosk_back", "kiosk_home", "reload_kiosk", "lock_now", "reboot"]
DEVICE_COMMAND_OPS: tuple[DeviceCommandOp, ...] = get_args(DeviceCommandOp)

# Valid op names that v1 always denies with DISABLED_BY_POLICY (§1, §3.3, Appendix A).
ReservedOp = Literal["navigate", "enter_kiosk", "exit_kiosk"]
RESERVED_OPS: tuple[ReservedOp, ...] = get_args(ReservedOp)

# Every op name a staff `cmd` may carry on the wire.
CommandOp = Literal[
    "tap", "swipe", "long_press", "kiosk_back", "kiosk_home", "reload_kiosk", "lock_now", "reboot",
    "wipe", "navigate", "enter_kiosk", "exit_kiosk"]
COMMAND_OPS: tuple[CommandOp, ...] = get_args(CommandOp)

# Non-command ops passed to SecurityServices.authorize (§3.3 policy table rows, §3.4 routes).
SessionOp = Literal[
    "list_devices", "attach", "detach", "lease_renew", "frame", "frame_displayed", "logout",
    "enroll_list", "device_scope_set", "enroll_approve", "enroll_reject", "enroll_reconcile",
    "audit_read", "device_revoke", "session_revoke", "step_up_start", "step_up_redeem"]
SESSION_OPS: tuple[SessionOp, ...] = get_args(SessionOp)

AuthzOp = CommandOp | SessionOp
AUTHZ_OPS: tuple[str, ...] = COMMAND_OPS + SESSION_OPS

STEP_UP_OPS: tuple[CommandOp, ...] = ("wipe",)

# ---------------------------------------------------------------- terminal reasons (§4, closed)

TerminalReason = Literal[
    "local_stop", "grant_expired", "lease_expired", "focus_lost", "obscured", "sensitive_state",
    "geometry_changed", "banner_lost", "suspend", "screen_off", "service_failure",
    "enrollment_opened", "detached", "disconnected", "revoked", "policy_changed"]
TERMINAL_REASONS: tuple[TerminalReason, ...] = get_args(TerminalReason)

ReasonOrigin = Literal["tablet", "relay"]
TERMINAL_REASON_ORIGINS: Mapping[TerminalReason, frozenset[ReasonOrigin]] = MappingProxyType({
    "local_stop": frozenset({"tablet"}),
    "grant_expired": frozenset({"tablet", "relay"}),
    "lease_expired": frozenset({"tablet", "relay"}),
    "focus_lost": frozenset({"tablet"}),
    "obscured": frozenset({"tablet"}),
    "sensitive_state": frozenset({"tablet"}),
    "geometry_changed": frozenset({"tablet"}),
    "banner_lost": frozenset({"tablet"}),
    "suspend": frozenset({"tablet"}),
    "screen_off": frozenset({"tablet"}),
    "service_failure": frozenset({"tablet"}),
    "enrollment_opened": frozenset({"tablet"}),
    "detached": frozenset({"relay"}),
    "disconnected": frozenset({"relay"}),
    "revoked": frozenset({"relay"}),
    "policy_changed": frozenset({"relay"}),
})
TABLET_TERMINAL_REASONS: tuple[TerminalReason, ...] = tuple(
    r for r in TERMINAL_REASONS if "tablet" in TERMINAL_REASON_ORIGINS[r])

# ---------------------------------------------------------------- error codes

ErrorCode = Literal[
    # auth and policy
    "UNAUTHENTICATED", "FORBIDDEN", "SESSION_EXPIRED", "DISABLED_BY_POLICY", "DEVICE_AUTH_FAILED",
    # attachment and grant
    "LEASE_BUSY", "LEASE_REQUIRED", "GRANT_REQUIRED", "ATTACHMENT_STALE", "GRANT_STALE",
    # frame binding
    "FRAME_UNKNOWN", "FRAME_NOT_DISPLAYED", "FRAME_EXPIRED", "GENERATION_STALE", "GESTURE_OUT_OF_BOUNDS",
    # admission and delivery
    "OVERLOADED", "DEADLINE_EXCEEDED", "DUPLICATE_ID_CONFLICT", "OUTCOME_UNKNOWN", "DISCONNECTED",
    "RESERVATION_EXPIRED",
    # message validity
    "UNSUPPORTED", "INVALID_MESSAGE"]
ERROR_CODES: tuple[ErrorCode, ...] = get_args(ErrorCode)

# Codes a tablet may put in a negative `ack.err` (§4). Others are relay-only.
AckErrorCode = Literal[
    "DISABLED_BY_POLICY", "LEASE_REQUIRED", "GRANT_REQUIRED", "ATTACHMENT_STALE", "GRANT_STALE",
    "FRAME_UNKNOWN", "FRAME_NOT_DISPLAYED", "FRAME_EXPIRED", "GENERATION_STALE", "GESTURE_OUT_OF_BOUNDS",
    "OVERLOADED", "DEADLINE_EXCEEDED", "DUPLICATE_ID_CONFLICT", "OUTCOME_UNKNOWN", "RESERVATION_EXPIRED",
    "UNSUPPORTED"]
ACK_ERROR_CODES: tuple[AckErrorCode, ...] = get_args(AckErrorCode)

# Codes a relay may send in session_ended (§3.1 live expiry, §2.1 login gate).
SessionEndCode = Literal["SESSION_EXPIRED", "UNAUTHENTICATED", "DISABLED_BY_POLICY"]
SESSION_END_CODES: tuple[SessionEndCode, ...] = get_args(SessionEndCode)

HttpErrorCode = Literal[
    "INVALID_REQUEST", "UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND", "CONFLICT", "EXPIRED",
    "RATE_LIMITED", "UNAVAILABLE"]
HTTP_ERROR_CODES: tuple[HttpErrorCode, ...] = get_args(HttpErrorCode)
HTTP_ERROR_STATUS: Mapping[HttpErrorCode, int] = MappingProxyType({
    "INVALID_REQUEST": 400, "UNAUTHENTICATED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404,
    "CONFLICT": 409, "EXPIRED": 410, "RATE_LIMITED": 429, "UNAVAILABLE": 503,
})

# ---------------------------------------------------------------- §2.1 dataclasses


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str


@dataclass(frozen=True)
class StaffSession:
    session_id: str
    principal: Principal
    display_name: str
    expires_at: datetime


@dataclass(frozen=True)
class WsAttachContext:
    device_id: str
    socket_id: str
    attachment_id: str | None
    grant_id: str | None
    lease_deadline: float | None
    grant_deadline: float | None
    maintenance_active: bool
    policy_revision: int
    requested_mode: AttachMode


@dataclass(frozen=True)
class WsCommandContext:
    device_id: str
    socket_id: str
    attachment_id: str
    grant_id: str | None
    lease_deadline: float
    grant_deadline: float | None
    maintenance_active: bool
    policy_revision: int


@dataclass(frozen=True)
class HttpMgmtContext:
    device_id: str | None
    target_session_id: str | None
    from_group: str | None
    to_group: str | None
    policy_revision: int


@dataclass(frozen=True)
class StepUpContext:
    device_id: str
    socket_id: str
    attachment_id: str
    grant_id: str
    lease_deadline: float
    grant_deadline: float
    maintenance_active: bool
    policy_revision: int


Ctx = WsAttachContext | WsCommandContext | HttpMgmtContext | StepUpContext


# Unchanged from v0.3 (ARCHITECTURE.md §2.1 note).
@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    error_code: ErrorCode | None


@dataclass(frozen=True)
class AuditEvent:
    principal: Principal | None
    session_id: str | None
    device_id: str | None
    op: str
    decision: str
    reason: str | None
    command_id: str | None
    outcome: str | None


DATACLASSES: tuple[type, ...] = (
    Principal, StaffSession, WsAttachContext, WsCommandContext, HttpMgmtContext, StepUpContext,
    DeviceIdentity, Decision, AuditEvent)

# ---------------------------------------------------------------- §2.1 protocols


class SecurityServices(Protocol):
    async def authenticate_staff(self, token: str) -> StaffSession: ...
    # Returns (audience, nonce).
    async def start_device_challenge(self, device_id: str, socket_id: str) -> tuple[str, str]: ...
    async def verify_device_proof(self, device_id: str, socket_id: str, sig: bytes) -> DeviceIdentity: ...
    async def authorize(self, session_id: str, op: str, ctx: Ctx) -> Decision: ...
    async def consume_step_up(self, session_id: str, op: str, step_up_id: str, ctx: StepUpContext) -> Decision: ...
    async def revoke_session(self, session_id: str) -> None: ...
    async def revoke_device(self, device_id: str) -> None: ...
    # Raises on failure; the caller must not dispatch.
    async def audit(self, event: AuditEvent) -> None: ...


class ConnectionCloser(Protocol):
    async def close_session(self, session_id: str) -> None: ...
    async def close_device(self, device_id: str) -> None: ...
