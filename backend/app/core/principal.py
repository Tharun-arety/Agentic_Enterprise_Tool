"""Who is acting.

Every mutation in this system is attributable to a `Principal`, and a principal
is either a signed-in human or a named agent. Modelling both as one type is
what lets the audit log, the approval queue, and the ECM sign-off sheet share a
single "actor" concept instead of each growing its own nullable `user_id` /
`agent_name` pair.

Kept in its own module so `app.core.audit` can depend on it without depending on
FastAPI, which `app.core.deps` does.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from app.domains.identity.models import Role


class ActorType(str, enum.Enum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Principal:
    actor_type: ActorType
    # Set for humans; None for agents and for system tasks such as seeding.
    user_id: uuid.UUID | None = None
    email: str | None = None
    # Set for agents, e.g. "ECM Impact Analyst".
    agent_name: str | None = None
    roles: tuple[str, ...] = field(default_factory=tuple)
    token_id: str | None = None
    token_expires_at: int | None = None

    @property
    def label(self) -> str:
        """Human-readable actor, for log lines and UI."""
        if self.actor_type is ActorType.AGENT:
            return f"agent:{self.agent_name or 'unknown'}"
        if self.actor_type is ActorType.SYSTEM:
            return "system"
        return self.email or f"user:{self.user_id}"

    def has_role(self, role: Role) -> bool:
        return role.value in self.roles or Role.ADMIN.value in self.roles


def agent_principal(agent_name: str) -> Principal:
    """The actor recorded when an agent proposes a change.

    Agents carry no roles by construction. Nothing an agent proposes takes
    effect on its own authority — it waits for a human with the right role to
    approve it — so granting one a role would be a lie the audit log then tells
    forever.
    """
    return Principal(actor_type=ActorType.AGENT, agent_name=agent_name)


SYSTEM_PRINCIPAL = Principal(actor_type=ActorType.SYSTEM)
