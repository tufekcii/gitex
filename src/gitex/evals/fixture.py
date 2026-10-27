"""Testler ve değerlendirme seti için deterministik örnek git deposu kurucu.

Senaryo: küçük bir ödeme/kimlik doğrulama uygulaması. Birkaç yazar, rename, merge,
silinen dosya, eklenip sonra kaldırılan bir fonksiyon ve sonradan değişen bir sabit içerir.
Tarihler ve yazarlar sabit olduğundan SHA'lar her makinede aynıdır.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

AYSE = ("Ayşe Yılmaz", "ayse@example.com")
MEHMET = ("Mehmet Demir", "mehmet@example.com")
ZEYNEP = ("Zeynep Kaya", "zeynep@example.com")

# Gizli bilgi kalıpları sahte ve parçalı üretilir; kaynak kodda gerçek bir anahtar yoktur.
FAKE_API_KEY = "sk-" + "test" + "FAKE" * 6
FAKE_DB_URL = "postgres://app:" + "s3cr3t-" + "pass" + "@db.internal:5432/app"


@dataclass
class FixtureRepo:
    path: Path
    shas: dict[str, str] = field(default_factory=dict)  # senaryo adımı -> tam SHA

    def sha(self, key: str) -> str:
        return self.shas[key]


class _Builder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.shas: dict[str, str] = {}
        cfg = tempfile.NamedTemporaryFile(prefix="gitex-gitconfig-", delete=False)  # noqa: SIM115
        cfg.close()
        self._global_cfg = cfg.name
        self.git("init", "-q", "-b", "main")

    def env(self, who: tuple[str, str], when: str) -> dict[str, str]:
        name, email = who
        return {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": self._global_cfg,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": f"{when}T10:00:00+03:00",
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": f"{when}T10:00:00+03:00",
        }

    def git(self, *args: str, who: tuple[str, str] = AYSE, when: str = "2026-01-01") -> str:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                *args,
            ],
            cwd=self.path,
            env=self.env(who, when),
            capture_output=True,
            check=True,
        )
        return proc.stdout.decode("utf-8", "replace").strip()

    def write(self, rel: str, content: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    def commit(self, key: str, message: str, who: tuple[str, str], when: str) -> str:
        self.git("add", "-A", who=who, when=when)
        self.git("commit", "-q", "-m", message, who=who, when=when)
        sha = self.git("rev-parse", "HEAD")
        self.shas[key] = sha
        return sha

    def cleanup(self) -> None:
        Path(self._global_cfg).unlink(missing_ok=True)


LOGIN_V1 = '''"""Login endpoint'i."""

from users.service import find_user


def login(username: str, password: str) -> bool:
    user = find_user(username)
    return user is not None and user.check_password(password)
'''

LOGIN_V2 = '''"""Login endpoint'i."""

from users.service import find_user

RATE_LIMIT = 5  # dakikada izin verilen deneme sayısı


class TooManyAttempts(Exception):
    pass


def check_rate_limit(ip: str, attempts: dict[str, int]) -> bool:
    return attempts.get(ip, 0) < RATE_LIMIT


def login(username: str, password: str, ip: str, attempts: dict[str, int]) -> bool:
    if not check_rate_limit(ip, attempts):
        raise TooManyAttempts(ip)
    user = find_user(username)
    return user is not None and user.check_password(password)
'''

PAYMENT_V1 = '''"""Ödeme servisi."""


def charge(user_id: int, amount: int) -> dict[str, int]:
    if amount <= 0:
        raise ValueError("tutar pozitif olmalı")
    return {"user_id": user_id, "amount": amount}
'''

REFUND = '''

def refund(charge_id: int, amount: int) -> dict[str, int]:
    """Tahsil edilen tutarın iadesi."""
    return {"charge_id": charge_id, "refunded": amount}
'''

DEBUG_DUMP = """

def debug_dump(payload: dict[str, int]) -> None:
    print("DEBUG", payload)
"""

RETRY = '''

def charge_with_retry(user_id: int, amount: int, attempts: int = 3) -> dict[str, int]:
    """Ödeme sağlayıcısı zaman aşımına uğrarsa yeniden dener."""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return charge(user_id, amount)
        except TimeoutError as exc:
            last = exc
    raise RuntimeError("ödeme başarısız") from last
'''

USERS_V1 = '''"""Kullanıcı servisi."""

_DB: dict[str, dict[str, str]] = {}


def find_user(username: str) -> dict[str, str] | None:
    return _DB.get(username)


def delete_user(username: str) -> None:
    _DB.pop(username, None)
'''

USERS_V2 = '''"""Kullanıcı servisi."""

from datetime import datetime

_DB: dict[str, dict[str, str]] = {}


def find_user(username: str) -> dict[str, str] | None:
    user = _DB.get(username)
    if user and user.get("deleted_at"):
        return None
    return user


def delete_user(username: str) -> None:
    """Soft-delete: kayıt silinmez, deleted_at işaretlenir (KVKK denetim izi için)."""
    if username in _DB:
        _DB[username]["deleted_at"] = datetime.now().isoformat()
'''

UTILS = """def slugify(text: str) -> str:
    return "-".join(text.lower().split())
"""


def build_fixture_repo(path: Path) -> FixtureRepo:
    """`path` altında senaryo deposunu kurar (dizin boş olmalı)."""
    path.mkdir(parents=True, exist_ok=True)
    b = _Builder(path)
    try:
        b.write("README.md", "# Örnek Uygulama\n\nÖdeme ve kimlik doğrulama servisi.\n")
        b.write("app/__init__.py", "")
        b.write("app/utils.py", UTILS)
        b.write("legacy/old.py", "def old_handler() -> None:\n    pass\n")
        b.commit("init", "İlk commit: proje iskeleti", AYSE, "2026-01-05")

        b.write("payment/__init__.py", "")
        b.write("payment/service.py", PAYMENT_V1)
        b.commit(
            "payment",
            "Ödeme servisi eklendi\n\nKart ile tahsilat için charge() fonksiyonu.",
            AYSE,
            "2026-01-10",
        )

        b.write("users/__init__.py", "")
        b.write("users/service.py", USERS_V1)
        b.write("auth/__init__.py", "")
        b.write("auth/login.py", LOGIN_V1)
        b.commit("login", "Login endpoint'i eklendi", MEHMET, "2026-01-15")

        b.write("auth/login.py", LOGIN_V2)
        b.commit(
            "rate_limit",
            "Login'e rate limit eklendi\n\nBrute-force denemelerine karşı IP başına "
            "dakikada 5 deneme sınırı. Güvenlik denetimindeki bulgu üzerine.",
            MEHMET,
            "2026-01-20",
        )

        # feature/refund dalı: ana dalla paralel ilerler, sonra --no-ff ile birleşir.
        b.git("checkout", "-q", "-b", "feature/refund", who=ZEYNEP, when="2026-02-03")
        b.write("payment/service.py", PAYMENT_V1 + REFUND)
        b.commit(
            "refund",
            "İade (refund) desteği eklendi\n\nMüşteri hizmetlerinin manuel iade talebi.",
            ZEYNEP,
            "2026-02-05",
        )
        b.git("checkout", "-q", "main", who=AYSE, when="2026-02-06")

        b.write(
            "users/service.py",
            USERS_V1.replace('"""Kullanıcı servisi."""', '"""Kullanıcı servisi (hard delete)."""'),
        )
        b.commit("hard_delete_doc", "Kullanıcı silme davranışı belgelendi", AYSE, "2026-02-06")

        b.git(
            "merge",
            "-q",
            "--no-ff",
            "feature/refund",
            "-m",
            "Merge branch 'feature/refund' into 'main'",
            who=ZEYNEP,
            when="2026-02-07",
        )
        b.shas["merge_refund"] = b.git("rev-parse", "HEAD")

        b.write("payment/service.py", PAYMENT_V1 + REFUND + DEBUG_DUMP)
        b.commit("debug_add", "Geçici debug_dump fonksiyonu eklendi", MEHMET, "2026-02-10")

        b.write("payment/service.py", PAYMENT_V1 + REFUND)
        b.commit("debug_remove", "debug_dump kaldırıldı", MEHMET, "2026-02-20")

        b.write("users/service.py", USERS_V2)
        b.commit(
            "soft_delete",
            "Kullanıcı silme soft-delete'e çevrildi\n\nKVKK denetim izi gereği kayıtlar "
            "fiziksel olarak silinmiyor, deleted_at alanı işaretleniyor.",
            ZEYNEP,
            "2026-03-01",
        )
        b.git("tag", "v1.0", who=ZEYNEP, when="2026-03-01")

        b.git("mv", "app/utils.py", "app/helpers.py", who=AYSE, when="2026-03-05")
        b.commit("rename", "utils.py helpers.py olarak yeniden adlandırıldı", AYSE, "2026-03-05")

        b.git("rm", "-q", "-r", "legacy", who=AYSE, when="2026-03-10")
        b.commit("legacy_delete", "Kullanılmayan legacy modülü silindi", AYSE, "2026-03-10")

        b.write("auth/login.py", LOGIN_V2.replace("RATE_LIMIT = 5", "RATE_LIMIT = 10"))
        b.commit(
            "rate_limit_10",
            "Rate limit 5'ten 10'a çıkarıldı\n\nKurumsal ofislerde NAT arkasındaki "
            "kullanıcılar yanlışlıkla engelleniyordu.",
            MEHMET,
            "2026-03-15",
        )

        b.write("payment/service.py", PAYMENT_V1 + REFUND + RETRY)
        b.commit(
            "retry",
            "Add retry on payment gateway timeout",
            ZEYNEP,
            "2026-04-02",
        )

        b.write(
            "config/settings.py",
            f'API_KEY = "{FAKE_API_KEY}"\nDATABASE_URL = "{FAKE_DB_URL}"\nDEBUG = False\n',
        )
        b.write("config/prod.env", f"SECRET_TOKEN={FAKE_API_KEY}\n")
        b.commit("settings", "Ayarlar dosyası eklendi", AYSE, "2026-04-10")
        b.git("tag", "v1.1", who=AYSE, when="2026-04-10")
    finally:
        b.cleanup()
    return FixtureRepo(path=path, shas=dict(b.shas))


def empty_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    b = _Builder(path)
    b.cleanup()
    return path
