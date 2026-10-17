"""Seraphix v2.8: intentionally narrow, read-only, opt-in tools.

No shell execution, file writes, credential access, or arbitrary URL fetching.
Commands are explicit to prevent model text from triggering computer actions.
"""
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
import re
import html

MAX_FILE_BYTES = 120_000
MAX_ENTRIES = 60
ALLOWED_SUFFIXES = {'.txt', '.md', '.py', '.json', '.csv', '.log'}


def _workspace(base):
    workspace = (Path(base) / 'Assistant_Workspace').resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _safe_path(root, name):
    if not name or '\x00' in name or name.startswith(('\\', '//')):
        raise ValueError('Provide a relative path inside Assistant_Workspace.')
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('Access denied: file is outside Assistant_Workspace.')
    return candidate


def _files(base):
    root = _workspace(base)
    items = []
    for path in sorted(root.rglob('*')):
        if len(items) >= MAX_ENTRIES:
            break
        if path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_dir():
                items.append('[folder] ' + relative + '/')
            elif path.suffix.lower() in ALLOWED_SUFFIXES:
                items.append('[file] ' + relative)
        except OSError:
            continue
    return ('Approved workspace: ' + str(root) + '\n' +
            ('\n'.join(items) if items else 'The workspace is empty. Copy a non-sensitive document into it to test /read.') +
            '\n\nUse /read filename.md to inspect a document.')


def _read(base, name):
    root = _workspace(base)
    path = _safe_path(root, name)
    if not path.is_file() or path.is_symlink():
        return 'File not found inside the approved workspace.'
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return 'This file type is not enabled for reading.'
    if path.stat().st_size > MAX_FILE_BYTES:
        return 'File exceeds the 120 KB read limit.'
    data = path.read_text(encoding='utf-8-sig', errors='replace')
    return 'Local file: ' + path.relative_to(root).as_posix() + '\n\n' + data[:12000] + ('\n[Preview truncated]' if len(data)>12000 else '')


def _research(query):
    if not query or len(query) > 250:
        return 'Use /research followed by a topic (up to 250 characters).'
    # Fixed endpoint: user cannot choose a URL or access local network hosts.
    url = 'https://www.bing.com/search?' + urlencode({'q': query, 'format': 'rss'})
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (Seraphix/2.8)'})
    try:
        with urlopen(request, timeout=12) as response:
            payload = response.read(350_000)
        root = ET.fromstring(payload)
        results = root.findall('./channel/item')[:5]
        if not results:
            return 'Search returned no results. Try a more specific query.'
        lines = ['Web research results for: ' + query, 'Source: Bing RSS search (live retrieval; not independently verified).', '']
        for index, item in enumerate(results, 1):
            title = html.unescape(item.findtext('title') or 'Untitled')
            link = item.findtext('link') or ''
            description = html.unescape(re.sub(r'<[^>]+>', '', item.findtext('description') or ''))
            lines.extend([f'{index}. {title[:180]}', f'   {link[:500]}', f'   {description[:450]}', ''])
        lines.append('These are search snippets, not a verified research report. Open sources to confirm important claims.')
        return '\n'.join(lines)
    except (URLError, HTTPError, ET.ParseError, TimeoutError, OSError) as exc:
        return 'Internet research is unavailable right now (' + type(exc).__name__ + '). Check your connection or try later.'


def handle_tool_command(prompt, base):
    text = (prompt or '').strip()
    if not text.startswith('/'):
        return None
    command, _, argument = text.partition(' ')
    command = command.lower()
    argument = argument.strip().strip('"')
    if command == '/help':
        return ('Seraphix v2.8 read-only tools:\n'
                '/research TOPIC — live web search with links\n'
                '/files — list approved workspace\n'
                '/read FILE — read a text document in that workspace\n'
                '/help — show commands\n\n'
                'No files are modified and no programs are executed.')
    if command == '/files':
        return _files(base)
    if command == '/read':
        try:
            return _read(base, argument)
        except (OSError, ValueError) as exc:
            return 'Read denied: ' + str(exc)
    if command == '/research':
        return _research(argument)
    return None
