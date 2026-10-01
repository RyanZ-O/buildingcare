"""Install a project-local Community DB, with independent loopback-only ports."""
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import urllib.request
import zipfile
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2026.09.0'
RUNTIME = ROOT / '.runtime'
NEO_DIRECTORY = RUNTIME / f'neo4j-community-{VERSION}'
URL = f'https://dist.neo4j.org/neo4j-community-{VERSION}-windows.zip'
EXPECTED_SHA256 = '020929aded4ba31a3b111918f4a4c85aa4dfb55a866d4bb8f6e593878335626e'

if __name__ == '__main__':
    values = dotenv_values(ROOT / '.env')
    if values.get('NEO4J_URI') and values['NEO4J_URI'] != 'bolt://127.0.0.1:17687':
        raise SystemExit('A different Neo4j connection is configured. Local installer will not overwrite it.')
    RUNTIME.mkdir(exist_ok=True)
    if not NEO_DIRECTORY.exists():
        archive = RUNTIME / f'neo4j-community-{VERSION}-windows.zip'
        if not archive.exists():
            print('Downloading official Neo4j Community distribution…', flush=True)
            with urllib.request.urlopen(URL, timeout=60) as response, archive.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        digest = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
        if digest != EXPECTED_SHA256:
            raise SystemExit('Archive checksum mismatch; installation stopped.')
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if not (RUNTIME / member.filename).resolve().is_relative_to(RUNTIME.resolve()):
                    raise SystemExit('Unsafe archive path')
            z.extractall(RUNTIME)
        print('Distribution extracted and SHA256 verified.', flush=True)
    config = NEO_DIRECTORY / 'conf' / 'neo4j.conf'
    if not (NEO_DIRECTORY / 'project-configured').exists():
        config.write_text('\n'.join([
            'server.default_listen_address=127.0.0.1',
            'server.default_advertised_address=127.0.0.1',
            'server.bolt.enabled=true', 'server.bolt.listen_address=:17687',
            'server.bolt.advertised_address=:17687',
            'server.http.enabled=true', 'server.http.listen_address=:17474',
            'server.http.advertised_address=:17474', 'server.https.enabled=false',
            'server.memory.heap.initial_size=256m', 'server.memory.heap.max_size=512m',
            'server.memory.pagecache.size=128m', 'dbms.usage_report.enabled=false',
        ]) + '\n', encoding='utf-8')
        password = secrets.token_urlsafe(30)
        env = {**os.environ, 'NEO4J_HOME': str(NEO_DIRECTORY)}
        process = subprocess.run([str(NEO_DIRECTORY / 'bin' / 'neo4j-admin.bat'), 'dbms', 'set-initial-password', password],
                                 cwd=NEO_DIRECTORY, env=env, capture_output=True, text=True)
        if process.returncode:
            raise SystemExit('Neo4j initial-password setup failed; no credentials were logged. Check Java installation.')
        for key, value in {'NEO4J_URI':'bolt://127.0.0.1:17687','NEO4J_USERNAME':'neo4j','NEO4J_PASSWORD':password,
                           'NEO4J_DATABASE':'neo4j','KNOWLEDGE_BACKEND':'neo4j'}.items():
            set_key(str(ROOT / '.env'), key, value)
        (NEO_DIRECTORY / 'project-configured').write_text('Independent project database. Credentials are in project .env.\n', encoding='utf-8')
    print('Local Neo4j configured: Bolt 17687 / Browser 17474 (loopback only). Credentials saved locally, not printed.')
