"""Local Python lab. Files live in a folder on the machine that runs the API."""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_SOURCE_CHARS = 32_000
MAX_OUTPUT_BYTES = 64_000
STARTUP_SECONDS = 2
PIP_TIMEOUT_SECONDS = 120
VENV_TIMEOUT_SECONDS = 120
STARTER = 'print("Hello from Lab")\n'
_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}(==[A-Za-z0-9.*+]{1,20})?$")
_SKIP_DIRS = {"node_modules", ".git", "__pycache__"}
_NEED_VENV = "Choose or create a Python environment first"
_jobs: dict[str, tuple[subprocess.Popen, "_Output"]] = {}
_lab_python_version_cache: str | None = None


class LabNotFound(Exception):
    pass


class LabBadRequest(Exception):
    pass


class LabUnavailable(Exception):
    pass


def lab_dir() -> Path:
    configured = os.environ.get("EDUCATION_LAB_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "education-lab"


def browse(path: str) -> dict:
    root = _allowed_dir(path) if path.strip() else Path.home().resolve()
    parent = _parent(root)
    if _is_venv(root):
        return {
            "path": str(root),
            "parent": parent,
            "dirs": [],
            "venvs": [],
            "files": [],
            "isVenv": True,
        }
    dirs: list[str] = []
    venvs: list[str] = []
    files: list[str] = []
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        raise LabBadRequest("Could not read that folder") from exc
    for child in children:
        if child.is_file() and child.suffix == ".py" and not child.name.startswith("."):
            files.append(child.name)
            continue
        if not child.is_dir() or child.name in _SKIP_DIRS:
            continue
        if _is_venv(child):
            venvs.append(child.name)
            continue
        if child.name.startswith("."):
            continue
        dirs.append(child.name)
    return {
        "path": str(root),
        "parent": parent,
        "dirs": dirs,
        "venvs": venvs,
        "files": files,
        "isVenv": False,
    }


def open_folder(user_id: str, path: str) -> dict:
    root = _allowed_dir(path)
    if _ready_venv(root):
        chosen = str(root)
    else:
        dot = (root / ".venv").resolve()
        chosen = str(dot) if _ready_venv(dot) else ""
    _save_state(user_id, root, chosen)
    return list_files(user_id)


def choose_venv(user_id: str, path: str, create: bool, name: str = ".venv") -> dict:
    root, _current = ensure_workspace(user_id)
    if create:
        parent = _allowed_dir(path) if path.strip() else root
        folder_name = _venv_dir_name(name)
        _create_venv(parent, folder_name)
        chosen = str((parent / folder_name).resolve())
    else:
        if not path.strip():
            raise LabBadRequest("Choose an environment")
        target = _allowed_dir(path)
        if not _ready_venv(target):
            raise LabBadRequest("That folder is not a Python environment")
        chosen = str(target)
    _save_state(user_id, root, chosen)
    return list_files(user_id)


def list_files(user_id: str) -> dict:
    root, venv_path = ensure_workspace(user_id)
    names = sorted(path.name for path in root.glob("*.py") if path.is_file())
    return {
        "root": str(root),
        "python": str(_interpreter(venv_path)) if venv_path else "",
        "labPython": _resolve_lab_python(validate=False),
        "labPythonVersion": _lab_python_version(),
        "venv": _venv_label(root, venv_path),
        "venvs": _venv_names(root),
        "files": names,
    }


def read_file(user_id: str, name: str) -> dict:
    path = _file_path(user_id, name)
    if not path.is_file():
        raise LabNotFound("File not found")
    return {"name": path.name, "source": path.read_text(encoding="utf-8")}


def write_file(user_id: str, name: str, source: str) -> dict:
    if len(source) > MAX_SOURCE_CHARS:
        raise LabBadRequest("Program is too long")
    path = _file_path(user_id, name)
    path.write_text(source, encoding="utf-8")
    return {"name": path.name}


def run_file(user_id: str, name: str, source: str | None = None) -> dict:
    if source is not None:
        write_file(user_id, name, source)
    path = _file_path(user_id, name)
    if not path.is_file():
        raise LabNotFound("File not found")
    root, venv_path = _require_venv(user_id)
    python = _interpreter(venv_path)
    stop_program(user_id)
    proc = subprocess.Popen(
        [str(python), "-u", path.name],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_run_env(root, venv_path),
        start_new_session=True,
        preexec_fn=_limit_resources,
    )
    output = _Output(proc)
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    if proc.poll() is None:
        _jobs[user_id] = (proc, output)
        stdout, stderr = output.text()
        return {"stdout": stdout, "stderr": stderr, "exitCode": None, "timedOut": False, "running": True}
    output.finish()
    stdout, stderr = output.text()
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": proc.returncode,
        "timedOut": False,
        "running": False,
    }


def program_output(user_id: str) -> dict:
    job = _jobs.get(user_id)
    if job is None:
        return {"stdout": "", "stderr": "", "exitCode": None, "timedOut": False, "running": False}
    proc, output = job
    stdout, stderr = output.text()
    if proc.poll() is None:
        return {"stdout": stdout, "stderr": stderr, "exitCode": None, "timedOut": False, "running": True}
    _jobs.pop(user_id, None)
    output.finish()
    stdout, stderr = output.text()
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": proc.returncode,
        "timedOut": False,
        "running": False,
    }


def stop_program(user_id: str) -> dict:
    job = _jobs.pop(user_id, None)
    if job is None:
        return {"stdout": "", "stderr": "", "exitCode": None, "timedOut": False, "running": False}
    proc, output = job
    if proc.poll() is None:
        _end_process(proc)
    output.finish()
    stdout, stderr = output.text()
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": None,
        "timedOut": False,
        "running": False,
    }


class _Output:
    def __init__(self, proc: subprocess.Popen):
        self._lock = threading.Lock()
        self._out = bytearray()
        self._err = bytearray()
        self._threads = [
            threading.Thread(target=self._pump, args=(proc.stdout, self._out), daemon=True),
            threading.Thread(target=self._pump, args=(proc.stderr, self._err), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _pump(self, pipe, sink: bytearray):
        if pipe is None:
            return
        while True:
            chunk = pipe.read1(4096)
            if not chunk:
                break
            with self._lock:
                sink.extend(chunk)

    def finish(self):
        for thread in self._threads:
            thread.join(timeout=1)

    def text(self) -> tuple[str, str]:
        with self._lock:
            return _clip(bytes(self._out)), _clip(bytes(self._err))


def _end_process(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        proc.wait(timeout=1)


def list_packages(user_id: str) -> list[dict]:
    root, venv_path = _require_venv(user_id)
    python = _interpreter(venv_path)
    _ensure_pip(python)
    completed = subprocess.run(
        [str(python), "-m", "pip", "list", "--format=json"],
        cwd=root,
        capture_output=True,
        timeout=30,
        env=_run_env(root, venv_path),
    )
    if completed.returncode != 0:
        raise LabUnavailable("Could not list installed libraries")
    raw = json.loads(completed.stdout.decode() or "[]")
    packages = [
        {"name": item["name"], "version": item["version"]}
        for item in raw
        if item.get("name") and item.get("version")
    ]
    packages.sort(key=lambda item: item["name"].lower())
    return packages


def install_package(user_id: str, name: str) -> dict:
    spec = _package_spec(name)
    root, venv_path = _require_venv(user_id)
    python = _interpreter(venv_path)
    _ensure_pip(python)
    try:
        completed = subprocess.run(
            [str(python), "-m", "pip", "install", spec],
            cwd=root,
            capture_output=True,
            timeout=PIP_TIMEOUT_SECONDS,
            env=_run_env(root, venv_path),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "stdout": _clip(exc.stdout),
            "stderr": _clip(exc.stderr),
            "exitCode": None,
            "timedOut": True,
        }
    return {
        "stdout": _clip(completed.stdout),
        "stderr": _clip(completed.stderr),
        "exitCode": completed.returncode,
        "timedOut": False,
    }


def ensure_workspace(user_id: str) -> tuple[Path, str]:
    saved = _load_state(user_id)
    if saved and Path(saved["root"]).is_dir():
        try:
            root = _allowed_dir(saved["root"])
        except LabBadRequest:
            root = None
        if root is not None:
            return root, _stored_venv(root, saved.get("venv") or "")
    root = lab_dir()
    root.mkdir(parents=True, exist_ok=True)
    _create_venv(root, ".venv")
    if not any(root.glob("*.py")):
        (root / "hello.py").write_text(STARTER, encoding="utf-8")
    chosen = str((root / ".venv").resolve())
    _save_state(user_id, root.resolve(), chosen)
    return root.resolve(), chosen


def _require_venv(user_id: str) -> tuple[Path, str]:
    root, venv_path = ensure_workspace(user_id)
    if not venv_path or not _interpreter(venv_path).is_file():
        raise LabBadRequest(_NEED_VENV)
    return root, venv_path


def _create_venv(root: Path, name: str) -> None:
    python = root / name / "bin" / "python"
    if python.is_file():
        return
    try:
        subprocess.run(
            [_resolve_lab_python(), "-m", "venv", str(root / name)],
            check=True,
            timeout=VENV_TIMEOUT_SECONDS,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise LabUnavailable(detail or "Could not create the Python environment") from exc
    except subprocess.TimeoutExpired as exc:
        raise LabUnavailable("Could not create the Python environment") from exc


def _resolve_lab_python(validate: bool = True) -> str:
    configured = os.environ.get("EDUCATION_LAB_PYTHON", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if validate and not path.is_file():
            raise LabUnavailable(
                "Lab Python is not available. Ask an administrator to set EDUCATION_LAB_PYTHON."
            )
        if validate and path.resolve() == Path(sys.executable).resolve():
            raise LabUnavailable(
                "Lab Python must not be the Education API interpreter. Set EDUCATION_LAB_PYTHON."
            )
        return str(path)
    base = getattr(sys, "_base_executable", "") or ""
    if base and Path(base).is_file():
        return str(Path(base).resolve())
    api_python = Path(sys.executable).resolve()
    if validate and (api_python.parent.parent / "pyvenv.cfg").is_file():
        raise LabUnavailable(
            "Lab Python is not configured. Set EDUCATION_LAB_PYTHON to a system interpreter."
        )
    return str(api_python)


def _lab_python_version() -> str:
    global _lab_python_version_cache
    if _lab_python_version_cache is not None:
        return _lab_python_version_cache
    python = _resolve_lab_python(validate=False)
    if not Path(python).is_file():
        _lab_python_version_cache = ""
        return ""
    try:
        completed = subprocess.run(
            [python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            timeout=5,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        _lab_python_version_cache = ""
        return ""
    version = completed.stdout.strip() if completed.returncode == 0 else ""
    _lab_python_version_cache = version
    return version


def _allowed_dir(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise LabBadRequest("Folder not found")
    if any(path == root or root in path.parents for root in _allowed_roots()):
        return path
    raise LabBadRequest("Choose a folder inside your home directory")


def _allowed_roots() -> list[Path]:
    roots = [Path.home().resolve(), lab_dir().resolve()]
    extra = os.environ.get("EDUCATION_LAB_EXTRA_ROOTS", "")
    for item in extra.split(os.pathsep):
        if item.strip():
            roots.append(Path(item).expanduser().resolve())
    return roots


def _parent(root: Path) -> str | None:
    parent = root.parent
    if parent == root:
        return None
    if any(parent == allowed or allowed in parent.parents for allowed in _allowed_roots()):
        return str(parent)
    return None


def _is_venv(path: Path) -> bool:
    return (path / "pyvenv.cfg").is_file()


def _ready_venv(path: Path) -> bool:
    return _is_venv(path) and (path / "bin" / "python").is_file()


def _venv_names(root: Path) -> list[str]:
    names: list[str] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return names
    for child in children:
        if child.is_dir() and _is_venv(child):
            names.append(child.name)
    names.sort(key=str.lower)
    return names


def _venv_label(root: Path, venv_path: str) -> str:
    if not venv_path:
        return ""
    path = Path(venv_path)
    if path == root:
        return path.name
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _stored_venv(root: Path, stored: str) -> str:
    if not stored.strip():
        return ""
    path = Path(stored)
    path = path.resolve() if path.is_absolute() else (root / stored).resolve()
    if not _ready_venv(path):
        return ""
    try:
        _allowed_dir(str(path))
    except LabBadRequest:
        return ""
    return str(path)


def _interpreter(venv_path: str) -> Path:
    return Path(venv_path) / "bin" / "python"


def _ensure_pip(python: Path) -> None:
    probe = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True)
    if probe.returncode == 0:
        return
    try:
        subprocess.run(
            [str(python), "-m", "ensurepip", "--upgrade"],
            check=True,
            timeout=PIP_TIMEOUT_SECONDS,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LabUnavailable("Could not add pip to the Python environment") from exc


def _package_spec(name: str) -> str:
    spec = name.strip()
    if not _PACKAGE.fullmatch(spec):
        raise LabBadRequest("Use a package name such as requests or requests==2.32.0")
    return spec


def _python(root: Path, venv_name: str = ".venv") -> Path:
    return root / venv_name / "bin" / "python"


def _file_path(user_id: str, name: str) -> Path:
    safe = _py_name(name)
    root, _venv_path = ensure_workspace(user_id)
    path = (root / safe).resolve()
    if path.parent != root:
        raise LabBadRequest("Use a simple file name")
    return path


def _venv_dir_name(name: str) -> str:
    folder = name.strip()
    if not folder or folder in {".", ".."} or "/" in folder or "\\" in folder:
        raise LabBadRequest("Use a simple environment folder name")
    if not re.fullmatch(r"[\w.-]+", folder):
        raise LabBadRequest("Use a simple environment folder name")
    return folder


def _py_name(name: str) -> str:
    if not name.endswith(".py") or "/" in name or "\\" in name or name.startswith("."):
        raise LabBadRequest("Use a simple .py file name")
    stem = name[: -len(".py")]
    if not stem or not all(char.isalnum() or char in "-_" for char in stem):
        raise LabBadRequest("Use a simple .py file name")
    return name


def _state_path(user_id: str) -> Path:
    configured = os.environ.get("EDUCATION_LAB_STATE", "").strip()
    folder = Path(configured).expanduser() if configured else Path.home() / ".education-lab"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)[:80] or "user"
    return folder / f"{safe}.json"


def _load_state(user_id: str) -> dict | None:
    path = _state_path(user_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("root"):
        return None
    return {"root": str(data["root"]), "venv": str(data.get("venv") or "")}


def _save_state(user_id: str, root: Path, venv_path: str) -> None:
    _state_path(user_id).write_text(
        json.dumps({"root": str(root), "venv": venv_path}),
        encoding="utf-8",
    )


def _run_env(root: Path, venv_path: str) -> dict[str, str]:
    bin_dir = str(Path(venv_path) / "bin")
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "VIRTUAL_ENV": venv_path,
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "NO_COLOR": "1",
    }


def _limit_resources() -> None:
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
    except (ValueError, OSError):
        pass


def _clip(data: bytes | None) -> str:
    if not data:
        return ""
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        text += "\n...output truncated\n"
    return text
