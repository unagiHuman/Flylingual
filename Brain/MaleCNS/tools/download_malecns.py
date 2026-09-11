#!/usr/bin/env python3
"""Download only the small, named MaleCNS inputs linked by the official page.

Python 3.10+, standard library only. No API token or Google Cloud SDK is needed
for the public links. This is a downloader, not a neural simulator.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen

PAGE = 'https://male-cns.janelia.org/download/'
FILES = {
    'annotations': 'body-annotations-male-cns-v1.0-minconf-0.5.feather',
    'neurotransmitters': 'body-neurotransmitters-male-cns-v1.0.feather',
    'weights': 'connectome-weights-male-cns-v1.0-minconf-0.5.feather',
}

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)

def resolve_links(html: str) -> dict[str, str]:
    parser = LinkParser()
    parser.feed(html)
    found: dict[str, str] = {}
    for href in parser.links:
        url = urljoin(PAGE, href)
        parsed = urlparse(url)
        if parsed.scheme == 'gs':
            url = 'https://storage.googleapis.com/' + parsed.netloc + parsed.path
            parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'storage.googleapis.com':
            continue
        name = Path(unquote(parsed.path)).name
        for key, expected in FILES.items():
            if name == expected:
                found[key] = url
    return found

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def check_feather_magic(path: Path) -> None:
    with path.open('rb') as stream:
        head = stream.read(6)
        if path.stat().st_size < 12:
            raise ValueError(f'{path.name}: too small to be Feather')
        stream.seek(-6, os.SEEK_END)
        tail = stream.read(6)
    valid = (head == b'ARROW1' and tail == b'ARROW1') or (
        head[:4] == b'FEA1' and tail[-4:] == b'FEA1')
    if not valid:
        raise ValueError(f'{path.name}: invalid Arrow/Feather signature (HTML/error response?)')

def atomic_json(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--only', choices=['metadata', 'all'], default='metadata')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max-file-gib', type=float, default=2.0)
    args = ap.parse_args()
    if args.max_file_gib <= 0:
        ap.error('--max-file-gib must be positive')
    keys = ['annotations', 'neurotransmitters'] + (['weights'] if args.only == 'all' else [])
    req = Request(PAGE, headers={'User-Agent': 'FlyBrain-MaleCNS-Download/1.0'})
    with urlopen(req, timeout=45) as response:
        html = response.read(4 * 1024 * 1024).decode('utf-8')
    links = resolve_links(html)
    for key in keys:
        if key not in links:
            raise RuntimeError(f'Official link not found: {FILES[key]}. Inspect {PAGE}; do not guess a replacement.')
        print(f'{key}: {links[key]}', flush=True)
    if args.dry_run:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / 'download_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
        'dataset': 'male-cns:v1.0', 'sourcePage': PAGE,
        'licenseNotice': 'CC-BY; consult the license linked from the official source page.',
        'files': {},
    }
    if manifest.get('dataset') != 'male-cns:v1.0':
        raise RuntimeError('Output directory contains a different dataset manifest')
    (args.out / 'source_download_page.html').write_text(html, encoding='utf-8')
    limit = int(args.max_file_gib * (1024 ** 3))
    for key in keys:
        target = args.out / FILES[key]
        prior = manifest['files'].get(key)
        if target.exists():
            check_feather_magic(target)
            if prior and prior.get('sha256') == digest(target) and prior.get('url') == links[key]:
                print(f'Validated existing file: {target.name}', flush=True)
                continue
            raise RuntimeError(f'{target} exists without a matching manifest. Move it aside; no automatic overwrite.')
        partial = target.with_suffix(target.suffix + '.part')
        if partial.exists():
            raise RuntimeError(f'{partial} exists from a previous attempt. Inspect/remove that partial file before retrying.')
        req = Request(links[key], headers={'User-Agent': 'FlyBrain-MaleCNS-Download/1.0', 'Accept-Encoding': 'identity'})
        with urlopen(req, timeout=90) as response:
            final_url = response.geturl()
            parsed = urlparse(final_url)
            if parsed.scheme != 'https' or parsed.hostname != 'storage.googleapis.com':
                raise RuntimeError(f'Unexpected download redirect: {final_url}')
            length = int(response.headers.get('Content-Length', '0'))
            if length > limit:
                raise RuntimeError(f'{target.name}: size exceeds configured limit')
            required_space = (length or limit) + 1024 ** 3
            if shutil.disk_usage(args.out).free < required_space:
                raise RuntimeError('Insufficient free disk space for file plus 1 GiB reserve')
            size, last_report = 0, 0
            h = hashlib.sha256()
            with partial.open('xb') as stream:
                while block := response.read(4 * 1024 * 1024):
                    size += len(block)
                    if size > limit:
                        raise RuntimeError('Streaming download exceeded configured size limit')
                    stream.write(block)
                    h.update(block)
                    if size - last_report >= 64 * 1024 * 1024:
                        print(f'  {target.name}: {size / (1024 ** 2):.0f} MiB', flush=True)
                        last_report = size
            if length and size != length:
                raise RuntimeError(f'Size mismatch: expected {length}, received {size}')
            headers = {k: response.headers.get(k) for k in ('ETag', 'Last-Modified', 'Content-Length', 'Content-Type', 'x-goog-hash')}
        check_feather_magic(partial)
        os.replace(partial, target)
        manifest['files'][key] = {
            'filename': target.name, 'url': links[key], 'bytes': size,
            'sha256': h.hexdigest(), 'publisherChecksumVerified': False,
            'downloadedAtUtc': datetime.now(timezone.utc).isoformat(), 'headers': headers,
        }
        # The SHA is a local reproducibility checksum, not a verified publisher SHA.
        atomic_json(manifest_path, manifest)
        print(f'Saved: {target.name} ({size} bytes)', flush=True)
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
