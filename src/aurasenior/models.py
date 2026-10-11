"""Household records as plain dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Person:
    household_id: str
    person_id: str
    role: str  # elder, family, neighbour, doctor, pharmacy
    display_name: str
    country: str
    language: str
    preferred_channel: str
    fallback_channel: str = "none"
    relation_label: str | None = None
    addresses: dict[str, str] = field(default_factory=dict)
    consent: dict[str, dict[str, Any]] = field(default_factory=dict)
    wa_last_inbound_at: str | None = None
    simulated: bool = False

    def consent_status(self, channel: str) -> str:
        return self.consent.get(channel, {}).get("status", "pending")

    @property
    def is_elder(self) -> bool:
        return self.role == "elder"

    @property
    def audience(self) -> str:
        return "elder" if self.is_elder else "family"


@dataclass
class Household:
    household_id: str
    name: str
    timezone: str
    checkin_time: str
    elder_person_id: str
    admin_person_id: str
    escalation_order: list[str]
    share_transcripts: bool = False


@dataclass
class Medicine:
    household_id: str
    medicine_id: str
    name: str
    display_label: str
    time_of_day: str
    stock: str
    pharmacy_person_id: str


@dataclass
class Approval:
    household_id: str
    approval_id: str
    kind: str
    medicine_id: str
    status: str
    ask_person_id: str
    created_at: str
    handled_at: str | None = None
    ran_out_at: str | None = None
    ordered_at: str | None = None
    handled_cid: str | None = None  # tap event that handled it, so a retry of that tap can finish


@dataclass
class Escalation:
    household_id: str
    escalation_id: str
    reason: str
    quote: str
    status: str
    created_at: str
    recheck_run: int = 0
    acknowledged_by: str | None = None
    acknowledged_at: str | None = None
    resolved_cid: str | None = None  # inbound event that closed it, so a retry of that event can finish
    fall_cid: str | None = None  # event that raised the fall alert, so a retry of it knows the elder was told
