"""Ingestion CLI.

    takam-ingest fetch   # site API -> data/raw (manifest.json + DOCX files)
    takam-ingest build   # data/raw -> data/index.db (offline, deterministic)

The two stages are separate so the index can be rebuilt (and tested) without the
site, and so a failed fetch never touches a working index.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from .client import TakamAPIError, TakamClient
from .config import Settings, get_settings
from .validity import current_version

log = logging.getLogger("takam_search.ingest")

SITE_DOC_URL = "https://takam.mof.gov.il/document/{code}"
INSTRUCTION_TYPES = {"Instruction"}
# Children that change or extend an instruction. Forms are out of scope for the POC.
CHILD_TYPES = {"Message", "Temporary Instruction"}
METADATA_FIELDS = (
    "sfid", "name", "documentcodetext", "documenttype", "mainchaptercode", "subchaptercode",
    "firstnamechapter", "secondnamechapter", "keywords", "description", "parentdocument",
    "datevalidfrom", "datevalidto",
)


def select_documents(all_docs: list[dict[str, Any]], chapters: list[int]) -> list[dict[str, Any]]:
    """Instructions of the given chapters plus their messages / temporary instructions.

    Children carry no chapter code (mainchaptercode is null), so they are found only
    through `parentdocument`.
    """
    instructions = [
        d for d in all_docs
        if d.get("documenttype") in INSTRUCTION_TYPES
        and d.get("mainchaptercode") in chapters
        and d.get("documentcodetext")
    ]
    parent_ids = {d["sfid"] for d in instructions}
    children = [
        d for d in all_docs
        if d.get("documenttype") in CHILD_TYPES
        and d.get("parentdocument") in parent_ids
        and d.get("documentcodetext")
    ]
    return instructions + children


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def fetch(settings: Settings, client: TakamClient, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    all_docs = client.documents()
    selected = select_documents(all_docs, settings.chapters)
    by_sfid = {d["sfid"]: d for d in all_docs}
    log.info("selected %d documents (chapters=%s)", len(selected), settings.chapters)

    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    entries, failures = [], 0
    for doc in selected:
        code = doc["documentcodetext"]
        entry = {k: doc.get(k) for k in METADATA_FIELDS}
        entry["code"] = code
        entry["url"] = SITE_DOC_URL.format(code=code)
        parent = by_sfid.get(doc.get("parentdocument") or "")
        entry["parent_code"] = parent.get("documentcodetext") if parent else None
        try:
            version = current_version(client.versions(doc["sfid"]), today)
            if version is None:
                raise TakamAPIError(f"{code}: no downloadable version")
            content = client.download(version["rtn_contentversionid__c"], code)
            (settings.docs_dir / f"{code}.docx").write_bytes(content)
            entry.update(
                file=f"docs/{code}.docx",
                version_number=version.get("rtn_versionnumber__c"),
                version_valid_from=version.get("rtn_validfrom__c"),
                version_valid_to=version.get("rtn_validto__c"),
                content_version_id=version["rtn_contentversionid__c"],
                error=None,
            )
            log.info("fetched %s (%d bytes)", code, len(content))
        except TakamAPIError as exc:
            failures += 1
            entry.update(file=None, error=str(exc))
            log.error("failed %s: %s", code, exc)
        entries.append(entry)
        time.sleep(settings.request_delay)

    manifest = {
        "fetched_at": today.isoformat(),
        "source": settings.base_url,
        "chapters": settings.chapters,
        "documents": entries,
    }
    _write_json_atomic(settings.manifest_path, manifest)
    log.info("manifest written: %d documents, %d failures", len(entries), failures)
    return manifest


def load_manifest(settings: Settings) -> dict[str, Any]:
    return json.loads(settings.manifest_path.read_text(encoding="utf-8"))


def build(settings: Settings, min_chunks_ratio: float = 0.5) -> dict[str, Any]:
    from .index import build_index, read_stats  # local import keeps `fetch` light

    manifest = load_manifest(settings)
    previous = read_stats(settings.db_path) if settings.db_path.exists() else None
    stats = build_index(manifest, settings.raw_dir, settings.db_path, previous_stats=previous,
                        min_chunks_ratio=min_chunks_ratio)
    log.info("index built: %s", stats)
    return stats


def _configure_logging() -> None:
    # Hebrew in logs: force UTF-8 so Windows consoles (cp1255/cp437) don't garble or crash.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="takam-ingest")
    parser.add_argument("command", choices=["fetch", "build", "all"])
    args = parser.parse_args(argv)
    _configure_logging()
    settings = get_settings()
    try:
        if args.command in ("fetch", "all"):
            with TakamClient(settings.base_url, settings.request_timeout, settings.max_retries) as client:
                fetch(settings, client)
        if args.command in ("build", "all"):
            build(settings)
    except Exception as exc:  # CLI boundary: report and exit non-zero for schedulers/CI
        log.exception("ingest %s failed: %s", args.command, exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
