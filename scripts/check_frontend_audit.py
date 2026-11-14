"""Fail-closed npm audit policy for the user-approved private usability pilot."""

import argparse
import hashlib
import json
from pathlib import Path


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected.split()), "Missing/unknown schema fields")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def bind_review(root, policy):
    require(policy["phase"] == "private-usability-pilot", "Unreviewed policy phase")
    reviewed = policy["reviewed_files"]
    source_root = root / "frontend/src"
    paths = list(source_root.rglob("*"))
    require(
        not source_root.is_symlink() and not any(p.is_symlink() for p in paths), "Linked source requires fresh review"
    )
    source = {str(p.relative_to(root)) for p in paths if p.is_file()}
    expected = {p for p in reviewed if p.startswith("frontend/src/")}
    require(source == expected, "Source inventory changed; fresh review required")
    for name, digest in reviewed.items():
        path = root / name
        require(path.is_file() and not path.is_symlink(), f"Missing/linked review input: {name}")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"Fresh review required: {name}")
    lock = load(root / "frontend/package-lock.json")
    for package, version in policy["packages"].items():
        require(
            lock["packages"]["node_modules/" + package]["version"] == version, f"Unreviewed package version: {package}"
        )


def evaluate(report, npm_exit, root):
    policy = load(root / "docs/frontend-audit-policy.json")
    keys(report, "auditReportVersion vulnerabilities metadata")
    require(type(report["auditReportVersion"]) is int and report["auditReportVersion"] == 2, "Unsupported audit format")
    require(npm_exit in (0, 1), "Audit transport/process failure")
    nodes = report["vulnerabilities"]
    require(isinstance(nodes, dict), "Malformed vulnerability map")
    keys(report["metadata"], "vulnerabilities dependencies")
    counts = report["metadata"]["vulnerabilities"]
    keys(counts, "info low moderate high critical total")
    require(all(type(v) is int and v >= 0 for v in counts.values()), "Invalid counts")
    actual = dict.fromkeys(counts, 0)
    for name, node in nodes.items():
        keys(node, "name severity isDirect via effects range nodes fixAvailable")
        require(node["name"] == name, "Package identity mismatch")
        severity = node["severity"]
        require(severity in counts and severity != "total", "Invalid severity")
        actual[severity] += 1
        actual["total"] += 1
    require(counts == actual, "Audit counts do not reconcile")
    dependencies = report["metadata"]["dependencies"]
    keys(dependencies, "prod dev optional peer peerOptional total")
    require(all(type(v) is int and v >= 0 for v in dependencies.values()), "Invalid dependency counts")
    require(dependencies["total"] > 0, "Empty dependency audit")
    if nodes:
        bind_review(root, policy)
    lock = load(root / "frontend/package-lock.json")
    require(dependencies["total"] == len(lock["packages"]) - 1, "Audit dependency total differs from lock inventory")
    if not nodes:
        require(npm_exit == 0, "Empty failed audit is not evidence")
        return "ZERO FINDINGS: npm audit exited 0 (no exceptions used)"
    require(npm_exit == 1, "Findings require npm exit 1")
    require(dependencies == policy["dependencies"], "Reviewed dependency inventory changed")
    accepted = set()
    resolved = {}

    def visit(name, visiting):
        require(name in nodes, f"Dangling advisory link: {name}")
        require(name not in visiting, "Cyclic advisory graph")
        if name in resolved:
            return resolved[name]
        require(name in policy["packages"], f"Unreviewed affected package: {name}")
        node = nodes[name]
        require(node["severity"] == "low", f"Unapproved severity for {name}: {node['severity']}")
        require(type(node["isDirect"]) is bool, "Malformed direct flag")
        require(isinstance(node["range"], str) and node["range"], "Missing affected range")
        require(node["nodes"] == ["node_modules/" + name], "Unreviewed package location")
        effects = node["effects"]
        require(
            isinstance(effects, list) and all(isinstance(e, str) and e in nodes for e in effects),
            "Malformed/dangling effects",
        )
        require(len(effects) == len(set(effects)), "Duplicate effects")
        fix = node["fixAvailable"]
        if type(fix) is not bool:
            keys(fix, "name version isSemVerMajor")
            require(
                isinstance(fix["name"], str) and isinstance(fix["version"], str) and type(fix["isSemVerMajor"]) is bool,
                "Malformed fix metadata",
            )
        via = node["via"]
        require(isinstance(via, list) and via, "Missing advisory causes")
        seen = set()
        causes = set()
        for advisory in via:
            marker = json.dumps(advisory, sort_keys=True)
            require(marker not in seen, "Duplicate advisory cause")
            seen.add(marker)
            if isinstance(advisory, str):
                causes.update(visit(advisory, visiting | {name}))
            else:
                require(isinstance(advisory, dict), "Malformed advisory")
                url = advisory.get("url")
                require(
                    isinstance(url, str) and marker == json.dumps(policy["advisories"].get(url), sort_keys=True),
                    f"Unreviewed advisory identity: {url}",
                )
                require(
                    advisory["name"] == name and advisory["dependency"] == name, "Advisory attached to wrong package"
                )
                accepted.add(url)
                causes.add(url)
        require(bool(causes), "Unresolved advisory causes")
        resolved[name] = causes
        return causes

    for name in nodes:
        visit(name, set())
    lines = ["ACCEPTED USER-APPROVED EXCEPTIONS (private-usability-pilot); NOT a clean raw audit."]
    lines.extend(sorted(accepted))
    lines.extend(
        f"{name}@{policy['packages'][name]}: {', '.join(sorted(causes))}" for name, causes in sorted(resolved.items())
    )
    lines.append("Rationale, sources and review triggers: docs/security-audit-exceptions.md")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--npm-exit", type=int, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(evaluate(load(args.report), args.npm_exit, args.root))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"BLOCKED: {error}\n")


if __name__ == "__main__":
    main()
