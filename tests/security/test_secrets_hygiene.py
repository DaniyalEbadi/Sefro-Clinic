import re
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent.parent

BURNED_SECRET = 'SefroClinic@2026'

SECRET_PATTERNS = {
    'private_key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'aws_access_key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'google_api_key': re.compile(r'AIza[0-9A-Za-z\-_]{35}'),
    'slack_token': re.compile(r'xox[baprs]-[0-9A-Za-z\-]{10,}'),
    'embedded_jwt': re.compile(r'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.'),
    'telegram_bot_token': re.compile(r'\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b'),
}

ALLOWED_FILES = {
    '.env.example',
}


def git_tracked_files():
    result = subprocess.run(
        ['git', 'ls-files'],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class SecretHygieneTests(SimpleTestCase):
    def test_env_file_is_not_tracked(self):
        tracked = git_tracked_files()
        self.assertNotIn('.env', tracked)

    def test_sqlite_database_is_not_tracked(self):
        self.assertNotIn('db.sqlite3', git_tracked_files())

    def test_burned_password_never_reappears_in_repository(self):
        scanner = 'tests/security/test_secrets_hygiene.py'
        for path in git_tracked_files():
            if path == scanner:
                continue
            file_path = BASE_DIR / path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            self.assertNotIn(BURNED_SECRET, content, f'{path} contains the burned password')

    def test_no_high_signal_secrets_in_tracked_files(self):
        findings = []
        for path in git_tracked_files():
            if path in ALLOWED_FILES:
                continue
            file_path = BASE_DIR / path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for label, pattern in SECRET_PATTERNS.items():
                match = pattern.search(content)
                if match:
                    findings.append(f'{path}: {label}')
        self.assertEqual(findings, [])

    def test_env_example_has_no_filled_values(self):
        example = (BASE_DIR / '.env.example').read_text(encoding='utf-8')
        for line in example.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, _, value = stripped.partition('=')
            if any(marker in key for marker in ['PASSWORD', 'SECRET_KEY']):
                self.assertEqual(value.strip(), '', f'.env.example must leave {key.strip()} empty')
