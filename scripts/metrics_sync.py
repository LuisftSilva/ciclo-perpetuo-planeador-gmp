#!/usr/bin/env python3
"""Sync webhook.site requests and publish encrypted metrics data for GitHub Pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from metrics_crypto import DEFAULT_ITERATIONS, encrypt_json

API_BASE = "https://webhook.site"
INDEX_COLLECTOR_RE = re.compile(
    r"(const\s+TELEMETRY_COLLECTOR_URL\s*=\s*['\"])https://webhook\.site/[^'\"]+(['\"]\s*;)"
)
INDEX_COLLECTOR_TOKEN_RE = re.compile(
    r"const\s+TELEMETRY_COLLECTOR_URL\s*=\s*['\"]https://webhook\.site/([0-9a-fA-F-]{36})['\"]\s*;"
)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def parse_webhook_dt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return to_iso(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC))
    except ValueError:
        return value


def default_state(ttl_hours: int, rotate_before_hours: int, retention_days: int) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "token_ttl_hours": ttl_hours,
        "rotate_before_hours": rotate_before_hours,
        "token_retention_days": retention_days,
        "current_token": None,
        "tokens": [],
        "last_dataset_sha256": None,
    }


def load_state(path: Path, ttl_hours: int, rotate_before_hours: int, retention_days: int) -> Dict[str, Any]:
    if not path.exists():
        return default_state(ttl_hours, rotate_before_hours, retention_days)
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    baseline = default_state(ttl_hours, rotate_before_hours, retention_days)
    baseline.update(state)
    return baseline


def create_token(session: requests.Session, ttl_hours: int, now: datetime) -> Dict[str, Any]:
    response = session.post(f"{API_BASE}/token", headers={"Accept": "application/json"}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    token_uuid = payload["uuid"]
    expires_at = now + timedelta(hours=ttl_hours)
    return {
        "uuid": token_uuid,
        "collector_url": f"{API_BASE}/{token_uuid}",
        "created_at": to_iso(now),
        "expires_at": to_iso(expires_at),
        "archived": False,
    }


def discover_token_from_index(index_path: Path) -> str | None:
    text = index_path.read_text(encoding="utf-8")
    match = INDEX_COLLECTOR_TOKEN_RE.search(text)
    if not match:
        return None
    token = match.group(1)
    if token == "00000000-0000-0000-0000-000000000000":
        return None
    return token


def ensure_token_rotation(state: Dict[str, Any], session: requests.Session, now: datetime) -> Tuple[bool, bool]:
    ttl_hours = int(state["token_ttl_hours"])
    rotate_before_hours = int(state["rotate_before_hours"])
    retention_days = int(state["token_retention_days"])

    changed = False
    created = False

    for token in state["tokens"]:
        expires = parse_iso(token.get("expires_at"))
        if expires is None:
            expires = now + timedelta(hours=ttl_hours)
            token["expires_at"] = to_iso(expires)
            changed = True
        retention_cutoff = expires + timedelta(days=retention_days)
        archived = now > retention_cutoff
        if token.get("archived") != archived:
            token["archived"] = archived
            changed = True

    current_uuid = state.get("current_token")
    current = next((t for t in state["tokens"] if t["uuid"] == current_uuid), None)

    rotate = current is None
    if current is not None:
        expires = parse_iso(current.get("expires_at"))
        if expires is None or (expires - now) <= timedelta(hours=rotate_before_hours):
            rotate = True

    if rotate:
        new_token = create_token(session=session, ttl_hours=ttl_hours, now=now)
        state["tokens"].append(new_token)
        state["current_token"] = new_token["uuid"]
        changed = True
        created = True

    return changed, created


def update_index_collector(index_path: Path, collector_url: str) -> bool:
    text = index_path.read_text(encoding="utf-8")
    replaced, count = INDEX_COLLECTOR_RE.subn(rf"\1{collector_url}\2", text, count=1)
    if count == 0:
        raise RuntimeError(
            "Could not find TELEMETRY_COLLECTOR_URL constant in index.html for automatic rotation"
        )
    if replaced != text:
        index_path.write_text(replaced, encoding="utf-8")
        return True
    return False


def parse_request_content(content: Any) -> Dict[str, Any]:
    if content is None:
        return {}
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {"rawContent": str(content)}
    content = content.strip()
    if not content:
        return {}
    try:
        value = json.loads(content)
        if isinstance(value, dict):
            return value
        return {"rawContent": value}
    except json.JSONDecodeError:
        return {"rawContent": content}


def fetch_token_requests(session: requests.Session, token_uuid: str, max_pages: int) -> List[Dict[str, Any]]:
    page = 1
    all_rows: List[Dict[str, Any]] = []

    while page <= max_pages:
        response = session.get(
            f"{API_BASE}/token/{token_uuid}/requests",
            params={"page": page, "sorting": "oldest"},
            headers={"Accept": "application/json"},
            timeout=45,
        )
        if response.status_code == 404:
            return all_rows
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            break
        all_rows.extend(rows)
        if payload.get("is_last_page", True):
            break
        page += 1

    return all_rows


def normalize_events(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        request_id = row.get("uuid")
        if not request_id or request_id in seen:
            continue
        seen.add(request_id)

        payload = parse_request_content(row.get("content"))
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        visitor = payload.get("visitor") if isinstance(payload.get("visitor"), dict) else {}
        display = payload.get("display") if isinstance(payload.get("display"), dict) else {}
        languages = payload.get("languages") if isinstance(payload.get("languages"), list) else None
        click_payload = payload.get("click") if isinstance(payload.get("click"), dict) else None
        event_name = payload.get("event") or payload.get("eventType") or payload.get("type")
        method = str(row.get("method") or "").upper()

        if not event_name and method in {"OPTIONS", "HEAD"}:
            continue
        if not event_name and not payload:
            continue
        if not event_name and payload.get("source") == "openclaw":
            event_name = "system_test"
        if not event_name:
            event_name = "unknown"

        screen = payload.get("screen") if isinstance(payload.get("screen"), dict) else {
            "width": display.get("screenWidth"),
            "height": display.get("screenHeight"),
            "colorDepth": None,
            "pixelRatio": None,
        }
        viewport = payload.get("viewport") if isinstance(payload.get("viewport"), dict) else {
            "width": display.get("viewportWidth"),
            "height": display.get("viewportHeight"),
        }

        event = {
            "id": request_id,
            "event": event_name,
            "receivedAt": parse_webhook_dt(row.get("created_at")),
            "url": payload.get("url") or page.get("href") or row.get("url"),
            "title": payload.get("title") or page.get("title"),
            "referrer": payload.get("referrer") or page.get("referrer"),
            "visitorId": payload.get("visitorId"),
            "sessionId": payload.get("sessionId"),
            "timezone": payload.get("timezone") or visitor.get("timezone"),
            "language": payload.get("language") or visitor.get("language") or (languages[0] if languages else None),
            "platform": payload.get("platform") or visitor.get("platform"),
            "device": payload.get("deviceType") or payload.get("device") or visitor.get("platform"),
            "userAgent": payload.get("userAgent") or row.get("user_agent"),
            "requestIp": row.get("ip"),
            "country": row.get("country"),
            "city": row.get("city"),
            "tokenId": row.get("token_id"),
            "durationMs": payload.get("durationMs") or payload.get("timeOnPageMs"),
            "hardwareConcurrency": payload.get("hardwareConcurrency") or visitor.get("hardwareConcurrency"),
            "deviceMemory": payload.get("deviceMemory") or visitor.get("deviceMemory"),
            "screen": screen,
            "viewport": viewport,
            "click": click_payload,
            "payload": payload,
        }
        events.append(event)

    events.sort(key=lambda item: (item.get("receivedAt") or "", item["id"]), reverse=True)
    return events


def build_dataset(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schemaVersion": 1,
        "events": events,
    }


def stable_hash(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json_if_changed(path: Path, payload: Dict[str, Any], compact: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def sync(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).resolve()
    state_path = repo_root / args.state_path
    index_path = repo_root / args.index_path
    output_path = repo_root / args.output_path

    password = os.environ.get(args.password_env)
    if not password:
        raise SystemExit(f"Missing required environment variable: {args.password_env}")

    now = datetime.now(UTC)
    state = load_state(
        path=state_path,
        ttl_hours=args.token_ttl_hours,
        rotate_before_hours=args.rotate_before_hours,
        retention_days=args.token_retention_days,
    )

    session = requests.Session()

    state_changed = False
    discovered = discover_token_from_index(index_path)
    if discovered and not any(t.get("uuid") == discovered for t in state.get("tokens", [])):
        state.setdefault("tokens", []).append(
            {
                "uuid": discovered,
                "collector_url": f"{API_BASE}/{discovered}",
                "created_at": to_iso(now),
                "expires_at": to_iso(now + timedelta(hours=args.token_ttl_hours)),
                "archived": False,
            }
        )
        state["current_token"] = discovered
        state_changed = True

    rotated_state_changed, token_created = ensure_token_rotation(state=state, session=session, now=now)
    state_changed = state_changed or rotated_state_changed

    current_uuid = state.get("current_token")
    current = next((t for t in state["tokens"] if t["uuid"] == current_uuid), None)
    if not current:
        raise RuntimeError("Current token missing after rotation step")

    index_changed = update_index_collector(index_path=index_path, collector_url=current["collector_url"])

    sync_tokens = [t for t in state["tokens"] if not t.get("archived")]
    all_rows: List[Dict[str, Any]] = []
    for token in sync_tokens:
        all_rows.extend(fetch_token_requests(session=session, token_uuid=token["uuid"], max_pages=args.max_pages))

    events = normalize_events(all_rows)
    dataset = build_dataset(events)
    dataset_hash = stable_hash(dataset)

    encrypted_changed = False
    if dataset_hash != state.get("last_dataset_sha256") or not output_path.exists():
        encrypted_payload = encrypt_json(dataset, password=password, iterations=args.iterations)
        encrypted_changed = write_json_if_changed(output_path, encrypted_payload, compact=True)
        state["last_dataset_sha256"] = dataset_hash
        state_changed = True

    state_written = write_json_if_changed(state_path, state, compact=False) if state_changed else False

    print(
        json.dumps(
            {
                "token_created": token_created,
                "index_changed": index_changed,
                "state_changed": state_written,
                "encrypted_changed": encrypted_changed,
                "events": len(events),
                "tokens_synced": len(sync_tokens),
                "current_token": current_uuid,
            }
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state-path", default="metrics/state.json")
    parser.add_argument("--index-path", default="index.html")
    parser.add_argument("--output-path", default="metrics/data/metrics.enc.json")
    parser.add_argument("--password-env", default="METRICS_PASSWORD")
    parser.add_argument("--token-ttl-hours", type=int, default=72)
    parser.add_argument("--rotate-before-hours", type=int, default=6)
    parser.add_argument("--token-retention-days", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sync(args)


if __name__ == "__main__":
    main()
