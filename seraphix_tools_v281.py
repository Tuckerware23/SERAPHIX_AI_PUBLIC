"""Bounded, read-only configured-workspace discovery and explicit research."""
from pathlib import Path
import os
import re
import time
from seraphix_tools_v28 import _research, _files, _read

from seraphix_config import WORKSPACE_ROOT

DRIVE = WORKSPACE_ROOT
SUFFIXES = {'.txt', '.md', '.py', '.json', '.csv', '.log', '.ps1', '.yaml', '.yml', '.toml', '.ini'}
DENIED_NAMES = {'.env', '.env.local', '.env.production', 'id_rsa', 'id_ed25519', 'credentials.json', 'secrets.json', 'token.json', 'key.pem', 'private.key', 'ntuser.dat'}
DENIED_DIRS = {'.git', '.venv', '.venv_kokoro', 'node_modules', '__pycache__', '$recycle.bin', 'system volume information', '.ssh', '.aws', '.azure', '.config', 'secrets', 'credentials'}
SENSITIVE_PARTS = ('password', 'secret', 'credential', 'private_key', 'api_key', 'apikey', 'access_token', 'refresh_token', 'oauth', 'wallet', 'recovery')
MAX_SCANNED = 6000
MAX_SECONDS = 8.0
MAX_MATCHES = 25
MAX_READ_BYTES = 100_000


def _allowed_file(path):
    name = path.name.lower()
    return (path.suffix.lower() in SUFFIXES and name not in DENIED_NAMES
            and not any(part in name for part in SENSITIVE_PARTS))


def _inside_drive(path):
    try:
        root = DRIVE.resolve(strict=True)
        resolved = path.resolve(strict=True)
        return resolved.is_relative_to(root) and resolved != root
    except (OSError, RuntimeError, ValueError):
        return False


def search_drive(term):
    term = term.strip().strip('"\'')
    if len(term) < 2 or len(term) > 100:
        return 'Please give a filename or project keyword (2–100 characters).'
    if not DRIVE.is_dir():
        return 'Configured workspace is not available. Confirm it is mounted in Windows.'
    results, scanned, start = [], 0, time.monotonic()
    truncated = False
    # Do not follow symlinks/junctions or reparse points.
    stack = [DRIVE]
    while stack:
        if scanned >= MAX_SCANNED or time.monotonic() - start >= MAX_SECONDS:
            truncated = True
            break
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned >= MAX_SCANNED or time.monotonic() - start >= MAX_SECONDS:
                        truncated = True
                        break
                    try:
                        if entry.is_symlink() or (getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
                            continue
                        name = entry.name
                        if entry.is_dir(follow_symlinks=False):
                            if name.lower() not in DENIED_DIRS and not any(x in name.lower() for x in SENSITIVE_PARTS):
                                stack.append(Path(entry.path))
                            if term.lower() in name.lower() and _inside_drive(Path(entry.path)):
                                results.append('[folder] ' + str(Path(entry.path)))
                        elif entry.is_file(follow_symlinks=False) and _allowed_file(Path(entry.path)) and term.lower() in name.lower():
                            if _inside_drive(Path(entry.path)):
                                results.append('[file] ' + str(Path(entry.path)))
                        if len(results) >= MAX_MATCHES:
                            truncated = True
                            break
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue
        if len(results) >= MAX_MATCHES:
            break
    return ('Workspace read-only filename search for: ' + term + '\n' + ('\n'.join(results) if results else 'No matches found in the scanned folders.')
            + f'\nScanned {scanned} entries.' + (' Search limited for performance; narrow your keyword if needed.' if truncated else '')
            + '\nNo files were changed. This searches names, not file contents.')


def read_drive(filename):
    if not filename or len(filename) > 600:
        return 'Provide a relative workspace path or a full path inside the configured workspace.'
    path = Path(filename.strip().strip('"\''))
    if not path.is_absolute():
        path = DRIVE / path
    if not _inside_drive(path) or not path.is_file():
        return 'Access denied or file not found in the configured workspace.'
    if any(part.lower() in DENIED_DIRS or any(x in part.lower() for x in SENSITIVE_PARTS) for part in path.parts):
        return 'Access denied: protected directory.'
    if not _allowed_file(path):
        return 'Access denied: unsupported or potentially sensitive filename.'
    try:
        if path.stat().st_size > MAX_READ_BYTES:
            return 'File is larger than 100 KB. Reading skipped.'
        content = path.read_text(encoding='utf-8-sig', errors='replace')
        # Redact common credential assignments even in otherwise permitted code files.
        content = re.sub(r'(?im)^(\s*[\w.-]*(?:password|secret|token|api[_-]?key)[\w.-]*\s*[:=]\s*).+$', r'\1[REDACTED]', content)
        return 'Read-only file preview: ' + str(path) + '\n\n' + content[:12000] + ('\n[Preview truncated]' if len(content) > 12000 else '')
    except (OSError, UnicodeError):
        return 'Unable to read this file.'


def handle_assistant_request(prompt, base):
    text = (prompt or '').strip()
    lower = text.lower()
    if lower in ('/help', '/agenthelp'):
        return ('Seraphix v2.8.1 read-only assistant tools:\n'
                '/research TOPIC — web search snippets and links\n'
                '/files — approved workspace listing\n'
                '/read FILE — read approved workspace file\n'
                '/searchdrive KEYWORD — search configured workspace filenames\n'
                '/readw relative/path/file.md - read a configured-workspace text file\n'
                '/plan GOAL — show a proposed plan (no execution)\n'
                'Natural language: "find files named project in workspace" or "research DNS records".\n'
                'No write, delete, rename, or shell execution is available.')
    if lower.startswith('/searchdrive '):
        return search_drive(text.split(' ', 1)[1])
    if lower.startswith('/readw '):
        return read_drive(text.split(' ', 1)[1])
    if lower.startswith('/plan '):
        goal = text[6:].strip()[:350]
        return ('Proposed task plan (not executed):\n1. Clarify desired outcome: ' + goal + '\n'
                '2. Discover relevant sources using approved read-only tools.\n'
                '3. Summarize findings and cite paths or links.\n'
                '4. Request explicit approval before any file creation, changes, or commands.\n'
                'Current release cannot perform write actions.')
    if lower.startswith('/research '):
        return _research(text.split(' ', 1)[1])
    if lower == '/files':
        return _files(base)
    if lower.startswith('/read '):
        try:
            return _read(base, text.split(' ', 1)[1].strip().strip('"'))
        except (OSError, ValueError) as exc:
            return 'Read denied: ' + str(exc)
    if lower.startswith('/'):
        return None
    # Conservative natural-language routing: don't accidentally run tools for ordinary questions.
    research = re.match(r'(?is)^(?:please\s+)?(?:research|search the (?:web|internet) for|look up online)\s+(.+)$', text)
    if research:
        return _research(research.group(1).strip()[:250])
    search = re.match(r'(?is)^(?:please\s+)?(?:find|search|locate|list)\s+(?:files?|folders?|projects?)\s+(?:named|called|matching|containing)\s+(.+?)\s+(?:on|in|across)\s+(?:my\s+)?workspace\s*[.!?]?$', text)
    if search:
        return search_drive(search.group(1).strip())
    return None
