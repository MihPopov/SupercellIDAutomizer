from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from supabase import Client, create_client

from players_search.config import Settings


@dataclass(frozen=True)
class PlayerRow:
    raw: Dict[str, Any]
    name: str
    club_tag: str
    row_id: Any


class PlayersInProgressRepo:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    def fetch_missing_supercell_id(self, limit: int) -> List[PlayerRow]:
        t = self._settings.supabase_table
        col_id = self._settings.col_id
        col_name = self._settings.col_name
        col_scid = self._settings.col_supercell_id
        col_tag = self._settings.col_club_tag

        res = (
            self._client.table(t)
            .select("*")
            .is_(col_scid, "null")
            .limit(limit)
            .execute()
        )

        rows: List[PlayerRow] = []
        for raw in (res.data or []):
            if col_name not in raw:
                continue
            if col_tag not in raw or not raw[col_tag]:
                continue
            rows.append(
                PlayerRow(
                    raw=raw,
                    name=str(raw[col_name]),
                    club_tag=str(raw[col_tag]),
                    row_id=raw.get(col_id),
                )
            )
        return rows

    def set_supercell_id(self, row_id: Any, supercell_id: str) -> None:
        t = self._settings.supabase_table
        col_id = self._settings.col_id
        col_scid = self._settings.col_supercell_id

        if row_id is None:
            raise ValueError(f"Row id is missing; set COL_ID (current: {col_id!r}).")

        self._client.table(t).update({col_scid: supercell_id}).eq(col_id, row_id).execute()
