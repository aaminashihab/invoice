"""Simulated (unauthenticated) identities for local development only (clarification C3).

These users are fictitious. They exist so that role-dependent behaviour (for example, the
``can_review`` permission required by decision D6) can be exercised locally. They are **not**
a security control and are disabled outside ``APP_ENV=development``.
"""

from __future__ import annotations

from dataclasses import dataclass

SIMULATED_USER_HEADER = "X-Simulated-User"


@dataclass(frozen=True)
class SimulatedUser:
    id: str
    display_name: str
    role: str
    can_review: bool
    email: str
    simulated: bool = True


SIMULATED_USERS: tuple[SimulatedUser, ...] = (
    SimulatedUser("sim-engineer", "Sim Site Engineer (simulated)", "ENGINEER", False,
                  "sim-engineer@example.invalid"),
    SimulatedUser("sim-qs", "Sim Quantity Surveyor (simulated)", "QS", False,
                  "sim-qs@example.invalid"),
    SimulatedUser("sim-accounts", "Sim Accounts Officer (simulated)", "ACCOUNTS", False,
                  "sim-accounts@example.invalid"),
    SimulatedUser("sim-reviewer", "Sim Reviewer (simulated)", "REVIEWER", True,
                  "sim-reviewer@example.invalid"),
    SimulatedUser("sim-admin", "Sim Administrator (simulated)", "ADMIN", False,
                  "sim-admin@example.invalid"),
)

DEFAULT_SIMULATED_USER_ID = "sim-engineer"

_BY_ID = {user.id: user for user in SIMULATED_USERS}


def get_simulated_user(user_id: str) -> SimulatedUser | None:
    return _BY_ID.get(user_id)
