"""Rebuild the offline HTML and deployment ZIP using Python's standard library."""
from pathlib import Path
import base64
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'


def build():
    session = json.loads((SOURCE / 'session-data.json').read_text(encoding='utf-8'))
    css = (SOURCE / 'base.css').read_text(encoding='utf-8') + '\n' + (SOURCE / 'extra.css').read_text(encoding='utf-8')
    template = (SOURCE / 'index.template.html').read_text(encoding='utf-8')
    payload = json.dumps(session, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = (template.replace('/*__STYLES__*/', css)
            .replace('/*__APP__*/', (SOURCE / 'app.js').read_text(encoding='utf-8'))
            .replace('__VIDEO__', base64.b64encode((ROOT / 'session-atlas.mp4').read_bytes()).decode('ascii'))
            .replace('__DATA__', payload))
    if re.search(r'(src|href)=[\"\'](?:https?://|/api/|/stream/)', html):
        raise ValueError('The offline page must not depend on external assets or API routes')
    content = html.encode('utf-8')
    (ROOT / 'index.html').write_bytes(content)
    duration = len(session['frames']) / session['fps']
    manifest = {'file': 'index.html', 'size_mb': round(len(content) / 1024**2, 2), 'source': 'recorded_3d_session',
                'mission': session['mission'], 'frames': len(session['frames']), 'duration_seconds': duration,
                'default_playback_seconds': duration / 4, 'devices': len(session['devices']),
                'completed_tasks': session['frames'][-1]['completed'], 'evidence': len(session['evidence']),
                'external_requests': 0}
    (ROOT / 'build-manifest.json').write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    files = ('index.html', 'README.md', 'build-manifest.json', 'THIRD_PARTY_NOTICES.md')
    with zipfile.ZipFile(ROOT / 'airport-ops-html-demo.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 9, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / name).read_bytes())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
