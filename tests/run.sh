#!/usr/bin/env bash
# Isolated fictional fixtures; no real user settings.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec python3 - "$ROOT" <<'PYTEST'
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(sys.argv[1])
passed = 0

def merge(base, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base

with tempfile.TemporaryDirectory(prefix=".fixtures-", dir=repo / "tests") as tmp:
    root = Path(tmp)
    (root / "home").mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(root / "home"),
           "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    config_path = root / "config.json"
    env["REMINDER_HOOKS_CONFIG"] = str(config_path)
    def invoke(hook, data, want, contains=None, override_env=None, diagnostic=False):
        global passed
        p = subprocess.run(["bash", str(repo / "hooks" / hook)],
                           input=data, text=True, capture_output=True,
                           cwd=root, env=dict(env, **(override_env or {})), timeout=10)
        assert p.returncode == 0, (hook, p.returncode, p.stderr)
        output = json.loads(p.stdout) if p.stdout.strip() else None
        assert bool(output) == want, (hook, data, p.stdout, p.stderr)
        if output:
            if hook == "filesize-reminder.sh":
                assert output["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
                context = output["hookSpecificOutput"]["additionalContext"]
                assert context
            else:
                assert output["decision"] == "block" and output["reason"]
                context = output["reason"]
            if contains:
                assert contains in context, (contains, context)
        assert bool(p.stderr.strip()) == diagnostic, p.stderr
        passed += 1

    for kind, hook in [("idea", "idea-to-backlog-reminder.sh"),
                       ("discussion", "discussion-drift-reminder.sh"),
                       ("filesize", "filesize-reminder.sh")]:
        for c in json.loads((repo / "tests/fixtures" / (kind + ".json")).read_text()):
            config = {"idea": {"backlog_paths": [str(root / "notes/tasks.md")]},
                      "discussion": {"record_paths": [str(root / "notes/tasks.md")]},
                      "filesize": {"rules": [{"pattern": "RULES.md", "max_lines": 2,
                                               "max_chars": 4, "max_line_chars": 4,
                                               "max_long_lines": 0}]}}
            merge(config, c.get("config", {}))
            config_path.write_text(json.dumps(config))
            if kind == "filesize":
                target = root / c["file"]
                if not c.get("missing"):
                    target.write_text(c["text"])
                event = {"hook_event_name": "PostToolUse", "cwd": str(root), "tool_name": "Write",
                         "tool_input": {"file_path": str(target)}, "tool_response": {"filePath": str(target)}}
                if c.get("response_only"):
                    event["tool_input"] = {}
            else:
                transcript = root / "fictional.jsonl"
                entries = json.loads(json.dumps(c["transcript"]).replace("__ROOT__", str(root)))
                transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
                event = {"hook_event_name": "Stop", "cwd": str(root),
                         "transcript_path": str(transcript), "stop_hook_active": False,
                         "last_assistant_message": c.get("reply", "虚构回答。")}
                event.update(c.get("event", {}))
            invoke(hook, json.dumps(event), c["want"], c.get("contains"))
            print("PASS", kind, c["name"])
        invoke(hook, "not json", False, diagnostic=True)
        invoke(hook, "[]", False, diagnostic=True)
        invoke(hook, json.dumps(event), False, override_env={"REMINDER_HOOKS_DISABLE": "all"})
        event["hook_event_name"] = "UnrelatedEvent"
        invoke(hook, json.dumps(event), False)
    config_path.write_text('{"idea":{"user_terms":42}}')
    invoke("idea-to-backlog-reminder.sh", '{}', False, diagnostic=True)
    config_path.write_text('{broken')
    invoke("idea-to-backlog-reminder.sh", '{}', False, diagnostic=True)
    config_path.write_text('{}')
    event = {"hook_event_name": "Stop", "cwd": str(root), "transcript_path": str(root / "absent.jsonl"),
             "last_assistant_message": "虚构回答", "stop_hook_active": False}
    invoke("idea-to-backlog-reminder.sh", json.dumps(event), False, diagnostic=True)
    config_path.write_text('{"filesize":{"rules":[{"pattern":"*.md","max_lines":0,"max_chars":4,"max_line_chars":4,"max_long_lines":0}]}}')
    invoke("filesize-reminder.sh", '{}', False, diagnostic=True)
    config_path.write_text('{}')
    # Execute the shipped settings commands, including shell quoting for the package path.
    settings = json.loads((repo / "settings.snippet.json").read_text())
    for event_name, matchers in settings["hooks"].items():
        for matcher in matchers:
            for hook in matcher["hooks"]:
                command = hook["command"].replace("/ABSOLUTE/PATH/claude-code-reminder-hooks", str(repo))
                p = subprocess.run(["bash", "-c", command], input=json.dumps({"hook_event_name": event_name,
                                   "stop_hook_active": True, "tool_name": "Read"}),
                                   text=True, capture_output=True, cwd=root, env=env, timeout=10)
                assert p.returncode == 0 and not p.stdout and not p.stderr, (p.stdout, p.stderr)
                passed += 1
    assert not (root / "home/.claude").exists()
print("PASS: %d checks; temporary HOME, no real user settings or transcripts." % passed)
PYTEST
