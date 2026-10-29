from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

APP_ID = "nava-journal"
ALLOWED_SUFFIXES = {".py", ".json", ".qss", ".svg", ".png", ".webp", ".ico", ".txt"}


def eligible(relative: Path) -> bool:
    name = relative.as_posix()
    if name == "main.py":
        return True
    return name.startswith("nava_journal/") and relative.suffix.lower() in ALLOWED_SUFFIXES and "__pycache__" not in relative.parts


def make_patch(
    base: Path,
    target: Path,
    output: Path,
    base_version: str,
    version: str,
    notes: list[str],
    change_groups: list[dict] | None = None,
    always_apply_files: list[str] | None = None,
) -> int:
    changed: list[tuple[str, bytes]] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(target)
        if not eligible(relative):
            continue
        old = base / relative
        current_bytes = path.read_bytes()
        if not old.is_file() or old.read_bytes() != current_bytes:
            changed.append((relative.as_posix(), current_bytes))
    if not changed:
        raise SystemExit("No changed application files were found; no patch ZIP was created.")

    changed_names = {name for name, _ in changed}
    manifest = {
        "format_version": 1,
        "app_id": APP_ID,
        "base_version": base_version,
        "version": version,
        "release_notes": notes,
        "files": [
            {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in changed
        ],
    }
    if change_groups is not None or always_apply_files is not None:
        groups = list(change_groups or [])
        always = list(always_apply_files or [])
        if len(always) != len(set(always)):
            raise SystemExit("always_apply_files contains duplicate paths")
        if any(name not in changed_names for name in always):
            raise SystemExit("always_apply_files contains a file which is not in this patch")
        assigned = set(always)
        group_ids: set[str] = set()
        normalized_groups: list[dict] = []
        for group in groups:
            if not isinstance(group, dict):
                raise SystemExit("Each change group must be an object")
            group_id = group.get("id")
            title = group.get("title")
            description = group.get("description", "")
            files = group.get("files")
            if not isinstance(group_id, str) or not group_id or group_id in group_ids:
                raise SystemExit("Each change group needs a unique non-empty id")
            if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
                raise SystemExit(f"Invalid title/description for change group {group_id}")
            if not isinstance(files, list) or not files:
                raise SystemExit(f"Change group {group_id} needs at least one file")
            group_files: list[str] = []
            for name in files:
                if name not in changed_names:
                    raise SystemExit(f"Change group {group_id} refers to a file not included in patch: {name}")
                if name in assigned:
                    raise SystemExit(f"Patch file belongs to multiple groups or is duplicated: {name}")
                assigned.add(name)
                group_files.append(name)
            group_ids.add(group_id)
            normalized_groups.append({
                "id": group_id,
                "title": title.strip(),
                "description": description.strip(),
                "files": group_files,
            })
        if assigned != changed_names:
            unassigned = sorted(changed_names - assigned)
            raise SystemExit("Every changed file must be mandatory or belong to one group: " + ", ".join(unassigned))
        if not normalized_groups:
            raise SystemExit("A selective patch must contain at least one change group")
        manifest["always_apply_files"] = always
        manifest["change_groups"] = normalized_groups

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        for name, content in changed:
            archive.writestr(f"files/{name}", content)
    print(f"Patch created: {output}")
    print(f"Base: {base_version} -> Target: {version}")
    print(f"Only changed files included: {len(changed)}")
    for name, content in changed:
        print(f"  {name} ({len(content)} bytes)")
    if change_groups is not None:
        print(f"Selectable change groups: {len(change_groups)}; always applied files: {len(always_apply_files or [])}")
    return len(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a differential update ZIP for Nava Journal.")
    parser.add_argument("--base", required=True, type=Path, help="Folder containing the currently released version")
    parser.add_argument("--target", required=True, type=Path, help="Folder containing the next version")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--note", action="append", default=[], help="Release note; may be supplied more than once")
    parser.add_argument("--groups-json", type=Path, help="JSON file containing change_groups and always_apply_files")
    args = parser.parse_args()
    groups = None
    always = None
    if args.groups_json:
        config = json.loads(args.groups_json.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise SystemExit("groups-json must contain a JSON object")
        groups = config.get("change_groups")
        always = config.get("always_apply_files")
    make_patch(
        args.base.resolve(), args.target.resolve(), args.output.resolve(),
        args.base_version, args.version, args.note, groups, always,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
