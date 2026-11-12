"""Hermetic tests for the deployment contract — what a host must get right.

A deployment is only as good as the assumptions baked into it, so this suite asserts the
things that silently break on someone else's machine:

  * **The uploads mount follows the setting.** The app writes to ``UPLOAD_DIR`` and serves
    ``/uploads`` from it. When the mount was hard-coded to ``"uploads"``, every published
    picture 404'd on a deployment that pointed ``UPLOAD_DIR`` at a volume — and Instagram
    fetches exactly those URLs before it publishes.
  * **A deploy package is complete.** ``requirements.txt`` exists and names every direct
    third-party import, ``DEPLOY.md``/``Dockerfile``/``docker-compose.yml`` exist, and the
    compose file wires a database, a persistent uploads volume and a healthcheck.
  * **Secrets cannot ride along.** The handoff tar excludes ``.env``, the database, uploads
    and ``venv/``; ``.dockerignore`` does the same for the image.
  * **A fresh database boots.** Importing ``app.main`` against an empty sqlite file must
    create the schema and serve the API, with no operator account invented along the way.
  * **The verifier and the first-operator script exist and are runnable**, because a
    deployment with no way to create its first admin, or to check itself afterwards, is a
    dead end.

Run:  cd /Users/dan/resmara && PYTHONPATH=$PWD python3 tests/test_packaging_contract.py
Writes only to a temp sqlite DB; no network.
"""
import ast
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASSED = 0
FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))


STDLIB = set(sys.stdlib_module_names)


def direct_imports(*roots):
    """Top-level module names imported by the given source trees."""
    names = set()
    for root in roots:
        for path in (ROOT / root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
    return names


def test_uploads_mount_follows_the_setting():
    print("uploads")
    main_src = (ROOT / "app/main.py").read_text()
    check("app/main.py mounts /uploads", '/uploads' in main_src)
    check("the mount uses settings.UPLOAD_DIR, not a hard-coded directory",
          "settings.UPLOAD_DIR" in main_src and 'directory="uploads"' not in main_src)
    check("settings is actually imported", "from app.core.config import settings" in main_src)

    db = tempfile.mkdtemp(prefix="resmara_contract_")
    up = Path(db) / "volume-uploads"
    os.environ["DATABASE_URL"] = f"sqlite:///{db}/app.db"
    os.environ["UPLOAD_DIR"] = str(up)
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        del sys.modules[mod]

    from fastapi.testclient import TestClient

    from app.main import app

    check("a fresh database boots the app", any(r.path == "/openapi.json" for r in app.routes))
    check("the uploads directory is created where UPLOAD_DIR says", up.is_dir())

    mounted = [r for r in app.routes if getattr(r, "path", "") == "/uploads"]
    check("the /uploads route is served from UPLOAD_DIR",
          bool(mounted) and Path(mounted[0].app.directory).resolve() == up.resolve(),
          f"mounted={[getattr(r, 'app', {}).directory for r in mounted]}")

    with TestClient(app) as client:
        check("the API answers", client.get("/openapi.json").status_code == 200)
        check("the frontend is served at the root", client.get("/").status_code == 200)

    conn = sqlite3.connect(f"{db}/app.db")
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    conn.close()
    check("the schema is created on boot", {"users", "boosts", "posts"} <= tables, str(sorted(tables)))
    check("no operator account is invented at boot", "admin@resmara.local" not in
          (ROOT / "app/db/session.py").read_text())
    return db


def test_deploy_package_is_complete():
    print("package")
    for name in ["requirements.txt", ".env.example", "Dockerfile", "docker-compose.yml",
                 "docker-entrypoint.sh", ".dockerignore", ".gitignore", "DEPLOY.md",
                 "scripts/create_operator.py", "scripts/selfcheck.py",
                 "scripts/make_deploy_bundle.sh", "scripts/run_tests.sh"]:
        check(f"{name} exists", (ROOT / name).is_file())

    reqs = (ROOT / "requirements.txt").read_text()
    # Import name -> distribution name, for the few that differ. Extras ([bcrypt]) come off.
    alias = {"dotenv": "python_dotenv", "jose": "python_jose", "multipart": "python_multipart",
             "PIL": "pillow"}
    pinned = set()
    for line in reqs.splitlines():
        line = line.split("#")[0].strip()
        if line:
            pinned.add(re.split(r"[<>=\[!~]", line)[0].strip().lower().replace("-", "_"))
    third_party = {n for n in direct_imports("app", "workers")
                   if n not in STDLIB and not n.startswith("app") and n != "__future__"}
    missing = {n for n in third_party if alias.get(n, n).replace("-", "_") not in pinned}
    check("requirements.txt names every direct third-party import", not missing, str(sorted(missing)))

    compose = (ROOT / "docker-compose.yml").read_text()
    check("compose brings a database", "postgres" in compose)
    check("compose gives uploads a persistent volume", "uploads" in compose and "volumes:" in compose)
    check("compose healthchecks the app", "healthcheck" in compose.lower())

    ignore = (ROOT / ".dockerignore").read_text() + (ROOT / ".gitignore").read_text()
    check(".env never enters an image or a repo", ".env" in ignore)
    check("local databases never enter an image or a repo", ".db" in ignore or "resmara.db" in ignore)

    docker = (ROOT / "Dockerfile").read_text()
    check("the image sets no USER directive (the entrypoint drops privileges itself)",
          not re.search(r"^\s*USER\s", docker, re.M))
    check("the entrypoint drops privileges with gosu",
          "gosu" in (ROOT / "docker-entrypoint.sh").read_text())

    env = (ROOT / ".env.example").read_text()
    for key in ["SECRET_KEY", "DATABASE_URL", "UPLOAD_DIR", "RESMARA_PUBLISH_TOKEN",
                "RESMARA_TOKEN_KEY", "RESMARA_PUBLIC_BASE_URL", "RESMARA_ENGINE_BASE_URL"]:
        check(f".env.example documents {key}", key in env)
    check("the hosted values are flagged", env.count("HOSTED") >= 4)


def test_scripts_run():
    """The helper scripts must parse and offer the flags the docs tell a host to use.

    They are compiled, not executed: create_operator.py and selfcheck.py open a database on
    import, and a test must never touch the install's real one.
    """
    print("scripts")
    for script, needles in [("scripts/create_operator.py", ("--email", "--no-admin", "DATABASE_URL")),
                            ("scripts/selfcheck.py", ("--base", "--full", "--system-token")),
                            ("scripts/make_deploy_bundle.sh", ("tar czf", "exit 1")),
                            ("scripts/run_tests.sh", ("PYTHONPATH", "ALL SUITES PASSED"))]:
        path = ROOT / script
        if script.endswith(".py"):
            proc = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                                  capture_output=True, text=True, timeout=60)
        else:
            proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        body = path.read_text()
        check(f"{script} parses", proc.returncode == 0, (proc.stderr or proc.stdout)[-200:])
        for needle in needles:
            check(f"{script} handles {needle!r}", needle in body)


def test_bundle_excludes_secrets():
    print("handoff bundle")
    script = (ROOT / "scripts/make_deploy_bundle.sh").read_text()
    check("the bundle script refuses to ship .env", ".env" in script)
    check("the bundle script refuses a database file", ".db" in script)
    check("the bundle script refuses the shared venv", "venv" in script)
    check("the bundle script fails the moment a secret slips in", "exit 1" in script)


def test_managed_host_database_urls():
    """Render/Fly hand out a bare postgresql:// URL; the image ships psycopg 3, not psycopg2."""
    print("managed database urls")
    from app.db.urls import normalize_database_url
    for given, want in [("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
                        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
                        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
                        ("sqlite:///./resmara.db", "sqlite:///./resmara.db")]:
        check(f"{given.split('//')[0]}// resolves to {want.split('//')[0]}//",
              normalize_database_url(given) == want, normalize_database_url(given))
    check("session.py asks for driver normalization",
          "normalize_database_url(" in (ROOT / "app/db/session.py").read_text())


def main():
    db = test_uploads_mount_follows_the_setting()
    test_managed_host_database_urls()
    test_deploy_package_is_complete()
    test_scripts_run()
    test_bundle_excludes_secrets()
    print(f"\n{PASSED + FAILED} checks, {FAILED} failed. "
          f"{'ALL PACKAGING CONTRACT TESTS PASSED' if FAILED == 0 else 'FAILURES'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
