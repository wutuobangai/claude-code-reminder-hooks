#!/usr/bin/env python3
"""Read-only Claude Code reminders. MIT."""
import fnmatch
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
MAX_INPUT = 1024 * 1024
MAX_TRANSCRIPT = 16 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024


def diagnostic():
    # Never echo input, transcript text, file paths, or exception details.
    print("reminder-hooks: input/config/file unavailable or unsupported; check locally.", file=sys.stderr)


def load_config():
    defaults = json.loads((ROOT / "config.example").read_text(encoding="utf-8"))
    explicit = os.environ.get("REMINDER_HOOKS_CONFIG")
    path = Path(explicit).expanduser() if explicit else ROOT / "config.json"
    if explicit or path.exists():
        patch = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(patch, dict):
            raise ValueError("config object required")
        for section, values in patch.items():
            if section not in defaults or not isinstance(values, dict):
                raise ValueError("unknown section")
            if any(k not in defaults[section] for k in values):
                raise ValueError("unknown option")
            defaults[section].update(values)
    for section, values in defaults.items():
        if type(values["enabled"]) is not bool:
            raise ValueError("enabled must be boolean")
        for key, value in values.items():
            if key == "enabled":
                continue
            if not isinstance(value, list):
                raise ValueError("list required")
            if key != "rules" and not all(isinstance(x, str) and x for x in value):
                raise ValueError("nonempty strings required")
        if section == "filesize":
            for rule in values["rules"]:
                if not isinstance(rule, dict) or set(rule) != {
                    "pattern", "max_lines", "max_chars", "max_line_chars", "max_long_lines"
                }:
                    raise ValueError("invalid rule")
                if not isinstance(rule["pattern"], str) or not rule["pattern"]:
                    raise ValueError("pattern required")
                for key in ("max_lines", "max_chars", "max_line_chars", "max_long_lines"):
                    if type(rule[key]) is not int or rule[key] < (0 if key == "max_long_lines" else 1):
                        raise ValueError("invalid threshold")
    return defaults


def blocks(entry):
    message = entry.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []


def user_text(entry):
    if entry.get("type") != "user" or entry.get("isMeta"):
        return None
    message = entry.get("message") or {}
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    else:
        text = content if isinstance(content, str) else ""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S).strip()
    if not text or "<task-notification>" in text[:300] or text.startswith(
        ("Stop hook feedback", "<local-command", "<command-")
    ):
        return None
    return text


def has(text, terms):
    return any(term in text for term in terms)


def path_at(value, cwd):
    p = Path(value).expanduser()
    return (p if p.is_absolute() else cwd / p).resolve()


def tool_calls(entries):
    for e in entries:
        if e.get("type") == "assistant":
            for b in blocks(e):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input")
                    yield b, inp if isinstance(inp, dict) else {}


def stop_reminder(mode, event, config, cwd):
    if event.get("stop_hook_active"):
        return None
    reply = event.get("last_assistant_message") or ""
    if not isinstance(reply, str):
        raise ValueError("reply must be text")
    if has(reply, config["skip_markers"]):
        return None
    transcript_path = event.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        raise ValueError("missing transcript")
    path = path_at(transcript_path, cwd)
    with path.open("rb") as stream:
        raw = stream.read(MAX_TRANSCRIPT + 1)
    if len(raw) > MAX_TRANSCRIPT:
        raise ValueError("transcript too large")
    entries = []
    for line in raw.decode("utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # Interrupted JSONL writes can leave a partial last line.
        if isinstance(entry, dict):
            entries.append(entry)
    users = [(i, text) for i, e in enumerate(entries) for text in [user_text(e)] if text]
    if not users:
        return None
    last_i, text = users[-1]
    turn = entries[last_i + 1:]
    if mode == "idea":
        if not (has(text, config["user_terms"]) or has(reply, config["reply_terms"])):
            return None
        paths = {path_at(p, cwd) for p in config["backlog_paths"]}
        successful = {b.get("tool_use_id") for e in turn for b in blocks(e)
                      if e.get("type") == "user" and isinstance(b, dict)
                      and b.get("type") == "tool_result" and not b.get("is_error")
                      and isinstance(b.get("tool_use_id"), str) and b.get("tool_use_id")}
        for b, inp in tool_calls(turn):
            target = inp.get("file_path")
            if b.get("name") in ("Write", "Edit") and b.get("id") in successful and isinstance(target, str):
                if path_at(target, cwd) in paths:
                    return None
        return ("待办提醒：本轮出现想法或待定事项，尚未看到配置的待办文件有成功写入记录。"
                "请核对是否需要记录，并遵守用户给定的写入范围；没有授权就只在回复中提醒。"
                "已另记或无需记录时，可用配置中的文字标记说明原因。")
    discussion = False
    for _, text in reversed(users[-8:]):
        # Discussion wins within a mixed message; phrases are still only heuristics.
        if has(text, config["discussion_terms"]):
            discussion = True
            break
        if has(text, config["go_terms"]):
            break
    if not discussion:
        return None
    record_paths = {path_at(p, cwd) for p in config["record_paths"]}
    for b, inp in tool_calls(turn):
        name = b.get("name")
        action = name in config["action_tools"]
        if name in ("Write", "Edit", "NotebookEdit"):
            target = inp.get("file_path") or inp.get("notebook_path")
            action = not isinstance(target, str) or path_at(target, cwd) not in record_paths
        elif name == "Bash":
            command = inp.get("command", "")
            action = isinstance(command, str) and has(command, config["shell_action_terms"])
        if action:
            return ("讨论提醒：最近的用户文字仍像是在讨论，本轮却出现了改文件、联网或委派等工具调用。"
                    "动作可能已经发生，请说明做了什么并核对用户授权；本提醒不能撤销动作。"
                    "用户本轮已明确要求时，可用配置的文字标记说明原话。")
    return None


def filesize_reminder(event, config, cwd):
    if event.get("tool_name") not in ("Write", "Edit"):
        return None
    inp = event.get("tool_input") or {}
    response = event.get("tool_response") or {}
    target = (inp.get("file_path") if isinstance(inp, dict) else None) or (
        response.get("filePath") if isinstance(response, dict) else None)
    if not isinstance(target, str) or not target:
        return None
    path = path_at(target, cwd)
    try:
        relative = path.relative_to(cwd).as_posix()
    except ValueError:
        relative = path.as_posix()
    rules = [r for r in config["rules"] if fnmatch.fnmatchcase(
        relative if "/" in r["pattern"] else path.name, r["pattern"])]
    if not rules or not path.is_file():
        return None
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("watched file too large")
    text = raw.decode("utf-8")
    lines = text.splitlines()
    warnings = []
    for r in rules:
        if len(lines) > r["max_lines"]:
            warnings.append(f"{len(lines)} 行（经验阈值 {r['max_lines']}）")
        if len(text) > r["max_chars"]:
            warnings.append(f"{len(text)} 字符（经验阈值 {r['max_chars']}）")
        long_lines = sum(len(line) > r["max_line_chars"] for line in lines)
        if long_lines > r["max_long_lines"]:
            warnings.append(f"{long_lines} 行超过 {r['max_line_chars']} 字符（容许 {r['max_long_lines']} 行）")
    if not warnings:
        return None
    return "文件长度提醒：刚写入的受关注文件有 " + "；".join(dict.fromkeys(warnings)) + "。可考虑精简或拆分，保留必要索引；本提醒不会自动改文件。"


def main():
    mode = sys.argv[1]
    disabled = os.environ.get("REMINDER_HOOKS_DISABLE", "").split(",")
    if "all" in disabled or mode in disabled:
        return
    configs = load_config()
    config = configs[mode]
    if not config["enabled"]:
        return
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("input too large")
    event = json.loads(raw)
    if not isinstance(event, dict):
        raise ValueError("object required")
    expected = "PostToolUse" if mode == "filesize" else "Stop"
    if event.get("hook_event_name") != expected:
        return
    cwd = Path(event.get("cwd") or os.getcwd()).expanduser().resolve()
    message = (filesize_reminder(event, config, cwd) if mode == "filesize"
               else stop_reminder(mode, event, config, cwd))
    if message:
        output = ({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}
                  if mode == "filesize" else {"decision": "block", "reason": message})
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, OSError, UnicodeError, KeyError, IndexError):
        diagnostic()
    # Reminder failures deliberately never interrupt the user's tool execution.
