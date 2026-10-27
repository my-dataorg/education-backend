import subprocess

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services import lab


@pytest.fixture(autouse=True)
def lab_directory(tmp_path, monkeypatch):
    work = tmp_path / "lab"
    monkeypatch.setenv("EDUCATION_LAB_DIR", str(work))
    monkeypatch.setenv("EDUCATION_LAB_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("EDUCATION_LAB_EXTRA_ROOTS", str(tmp_path))
    monkeypatch.delenv("EDUCATION_LAB_PYTHON", raising=False)
    lab._lab_python_version_cache = None
    yield work
    main.app.dependency_overrides.clear()


def client_for(user_id: str) -> TestClient:
    main.app.dependency_overrides[main.require_education_subscription] = lambda: {
        "id": user_id,
        "email": f"{user_id}@example.com",
        "token": "test",
    }
    return TestClient(main.app)


def test_workspace_includes_lab_python():
    client = client_for("user-a")
    opened = client.get("/v1/lab")
    assert opened.status_code == 200
    body = opened.json()
    assert body["labPython"]
    assert body["labPythonVersion"]


def test_create_venv_uses_education_lab_python(monkeypatch, tmp_path):
    lab_python = tmp_path / "shared-python"
    lab_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lab_python.chmod(0o755)
    monkeypatch.setenv("EDUCATION_LAB_PYTHON", str(lab_python))
    lab._lab_python_version_cache = None
    called: list[list[str]] = []

    def record_run(cmd, **kwargs):
        called.append(list(cmd))
        raise subprocess.CalledProcessError(1, cmd, stderr=b"stub")

    monkeypatch.setattr(subprocess, "run", record_run)
    with pytest.raises(lab.LabUnavailable):
        lab._create_venv(tmp_path / "project", ".venv")
    assert called[0][0] == str(lab_python.resolve())


def test_run_saves_program_on_disk(lab_directory):
    client = client_for("user-a")
    opened = client.get("/v1/lab")
    assert opened.status_code == 200
    body = opened.json()
    assert body["root"] == str(lab_directory)
    assert body["python"] == str(lab_directory / ".venv" / "bin" / "python")
    assert "hello.py" in body["files"]
    assert (lab_directory / ".venv" / "bin" / "python").is_file()

    ran = client.post(
        "/v1/lab/run",
        json={"name": "hello.py", "source": "print(1 + 1)\n"},
    )
    assert ran.status_code == 200
    assert ran.json()["stdout"] == "2\n"
    assert ran.json()["exitCode"] == 0
    assert (lab_directory / "hello.py").read_text(encoding="utf-8") == "print(1 + 1)\n"
    assert (lab_directory / ".venv").is_dir()
    listed = client.get("/v1/lab/packages")
    assert listed.status_code == 200
    names = [item["name"].lower() for item in listed.json()["packages"]]
    assert "pip" in names


def test_running_program_shows_output(monkeypatch):
    monkeypatch.setattr(lab, "STARTUP_SECONDS", 0.4)
    client = client_for("user-a")
    ran = client.post(
        "/v1/lab/run",
        json={"name": "slow.py", "source": "print('started')\nimport time\ntime.sleep(30)\n"},
    )
    assert ran.status_code == 200
    assert ran.json()["running"] is True
    assert "started" in ran.json()["stdout"]
    again = client.get("/v1/lab/output")
    assert again.status_code == 200
    assert "started" in again.json()["stdout"]
    client.post("/v1/lab/stop")


def test_long_program_keeps_running_until_stopped(monkeypatch):
    monkeypatch.setattr(lab, "STARTUP_SECONDS", 0.3)
    client = client_for("user-a")
    ran = client.post(
        "/v1/lab/run",
        json={"name": "slow.py", "source": "import time\ntime.sleep(30)\n"},
    )
    assert ran.status_code == 200
    assert ran.json()["running"] is True
    assert ran.json()["timedOut"] is False
    stopped = client.post("/v1/lab/stop")
    assert stopped.status_code == 200
    assert stopped.json()["running"] is False
    assert (client.get("/v1/lab").json()["files"]).count("slow.py") == 1


def test_rejects_unsafe_package_names():
    client = client_for("user-a")
    flagged = client.post("/v1/lab/packages", json={"name": "requests --upgrade"})
    empty = client.post("/v1/lab/packages", json={"name": ""})
    assert flagged.status_code == 400
    assert empty.status_code == 400


def test_rejects_paths_outside_the_lab_folder():
    client = client_for("user-a")
    client.get("/v1/lab")
    escaped = client.post(
        "/v1/lab/run",
        json={"name": "../secret.py", "source": "print(1)\n"},
    )
    nested = client.post("/v1/lab/run", json={"name": "nested/main.py", "source": "print(1)\n"})
    assert escaped.status_code == 400
    assert nested.status_code == 400


def test_open_folder_keeps_existing_venv(tmp_path):
    project = tmp_path / "course"
    project.mkdir()
    (project / "main.py").write_text("print('course')\n", encoding="utf-8")
    venv = project / ".venv"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    client = client_for("user-a")
    listed = client.get("/v1/lab/browse", params={"path": str(project)})
    assert listed.status_code == 200
    assert listed.json()["venvs"] == [".venv"]
    assert listed.json()["files"] == ["main.py"]

    opened = client.post("/v1/lab/open", json={"path": str(project)})
    assert opened.status_code == 200
    body = opened.json()
    assert body["root"] == str(project)
    assert body["venv"] == ".venv"
    assert ".venv" in body["venvs"]
    assert body["files"] == ["main.py"]
    assert "hello.py" not in body["files"]
    assert client.get("/v1/lab").json()["root"] == str(project)


def test_open_folder_does_not_create_a_venv(tmp_path):
    project = tmp_path / "course"
    project.mkdir()
    (project / "main.py").write_text("print(1)\n", encoding="utf-8")
    other = tmp_path / "shared"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / "python").write_text("", encoding="utf-8")
    (other / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    client = client_for("user-a")
    opened = client.post("/v1/lab/open", json={"path": str(project)})
    assert opened.status_code == 200
    assert opened.json()["venv"] == ""
    assert opened.json()["python"] == ""
    assert opened.json()["venvs"] == []
    assert not (project / ".venv").exists()

    blocked = client.post("/v1/lab/run", json={"name": "main.py", "source": "print(1)\n"})
    assert blocked.status_code == 400

    created = client.post("/v1/lab/venv", json={"create": True})
    assert created.status_code == 200
    assert created.json()["venv"] == ".venv"
    assert (project / ".venv" / "bin" / "python").is_file()

    nested = tmp_path / "venvs"
    nested.mkdir()
    custom = client.post(
        "/v1/lab/venv",
        json={"create": True, "path": str(nested), "name": "course-env"},
    )
    assert custom.status_code == 200
    assert (nested / "course-env" / "bin" / "python").is_file()
    assert custom.json()["venv"] == str((nested / "course-env").resolve())

    client.post("/v1/lab/open", json={"path": str(project)})
    attached = client.post("/v1/lab/venv", json={"path": str(other)})
    assert attached.status_code == 200
    assert attached.json()["root"] == str(project)
    assert attached.json()["python"] == str(other / "bin" / "python")
    assert attached.json()["files"] == ["main.py"]


def test_open_folder_lists_other_environments(tmp_path):
    project = tmp_path / "course"
    project.mkdir()
    (project / "main.py").write_text("print(1)\n", encoding="utf-8")
    named = project / ".venv-lab"
    (named / "bin").mkdir(parents=True)
    (named / "bin" / "python").write_text("", encoding="utf-8")
    (named / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    client = client_for("user-a")
    opened = client.post("/v1/lab/open", json={"path": str(project)})
    assert opened.status_code == 200
    assert opened.json()["venv"] == ""
    assert opened.json()["venvs"] == [".venv-lab"]
    picked = client.post("/v1/lab/venv", json={"path": str(named)})
    assert picked.status_code == 200
    assert picked.json()["venv"] == ".venv-lab"


def test_open_folder_that_is_itself_an_environment(tmp_path):
    project = tmp_path / "course"
    project.mkdir()
    (project / "main.py").write_text("print(1)\n", encoding="utf-8")
    env = tmp_path / "mytestvenv"
    (env / "bin").mkdir(parents=True)
    (env / "bin" / "python").write_text("", encoding="utf-8")
    (env / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    client = client_for("user-a")
    client.post("/v1/lab/open", json={"path": str(project)})
    attached = client.post("/v1/lab/venv", json={"path": str(env)})
    assert attached.status_code == 200
    assert attached.json()["root"] == str(project)
    assert attached.json()["files"] == ["main.py"]
    assert attached.json()["python"] == str(env / "bin" / "python")

    opened = client.post("/v1/lab/open", json={"path": str(env)})
    assert opened.status_code == 200
    assert opened.json()["venv"] == "mytestvenv"
    assert opened.json()["python"] == str(env / "bin" / "python")


def test_rejects_folders_outside_home():
    client = client_for("user-a")
    opened = client.post("/v1/lab/open", json={"path": "/etc"})
    assert opened.status_code == 400
