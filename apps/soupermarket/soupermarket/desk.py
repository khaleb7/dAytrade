"""Three one-shot local Cursor agents. Each writes a single column and does not edit files."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

COLUMNS = (
    (
        "boomer",
        "The Boomer",
        "You are The Boomer, columnist for Souper Intelligence. "
        "Long horizon, suspicious of fads, plain speech. Dividends and staying power over slogans.",
    ),
    (
        "genx",
        "The Gen Xer",
        "You are The Gen Xer, columnist for Souper Intelligence. "
        "Dry, unimpressed, specific. You have seen this headline cycle before and you say so without performing cynicism.",
    ),
    (
        "millennial",
        "The Millennial",
        "You are The Millennial, columnist for Souper Intelligence. "
        "You read the wire for what it does to a paycheck and a brokerage account, not for a slogan.",
    ),
)


def column_prompt(name: str, voice: str, front: list[dict[str, Any]], week: dict[str, Any]) -> str:
    wire = [
        {
            "source": item.get("source_label") or item.get("source") or "",
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "published": item.get("published") or "",
        }
        for item in front
    ]
    return (
        f"{voice}\n\n"
        "Write the column for today's edition. Two to four short paragraphs of prose. "
        "No title line, no markdown, no JSON.\n"
        "Use only the headlines and summaries below. Quote a title when you refer to a story. "
        "Do not invent prices, filings, companies, or events that are not in this packet. "
        "If the packet is empty, say the wire was quiet and stop.\n\n"
        f"Column name: {name}\n\n"
        "Week note (counts only, already computed):\n"
        f"{week.get('blurb') or ''}\n\n"
        "Today's wire:\n"
        f"{json.dumps(wire, ensure_ascii=False)}\n"
    )


def _clean(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    return body[:6000]


def write_commentaries(
    front: list[dict[str, Any]],
    week: dict[str, Any],
    *,
    api_key: str,
    model: str,
    cwd: str,
    prompt_fn: Callable[..., Any] | None = None,
) -> list[dict[str, str]]:
    if not api_key:
        raise RuntimeError("Missing CURSOR_API_KEY")
    os.makedirs(cwd, exist_ok=True)
    send = prompt_fn or Agent.prompt
    columns: list[dict[str, str]] = []
    for column_id, name, voice in COLUMNS:
        prompt = column_prompt(name, voice, front, week)
        try:
            result = send(
                prompt,
                AgentOptions(
                    api_key=api_key,
                    model=model,
                    tools=[],
                    local=LocalAgentOptions(cwd=cwd),
                ),
            )
        except CursorAgentError as err:
            print(
                f"[souper] {column_id} did not start: {err.message} retryable={err.is_retryable}",
                flush=True,
            )
            raise
        status = str(getattr(result, "status", ""))
        run_id = str(getattr(result, "id", ""))
        print(f"[souper] {column_id} run={run_id} status={status}", flush=True)
        if status != "finished":
            raise RuntimeError(f"{name} run {run_id} status={status}")
        body = _clean(str(getattr(result, "result", "") or ""))
        if not body:
            raise RuntimeError(f"{name} run {run_id} returned empty copy")
        columns.append({"id": column_id, "name": name, "body": body})
    return columns
