from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_education_subscription
from app.services import lab

router = APIRouter(prefix="/v1/lab", tags=["lab"])


class LabWorkspaceOut(BaseModel):
    root: str
    python: str = ""
    labPython: str = ""
    labPythonVersion: str = ""
    venv: str = ""
    venvs: list[str]
    files: list[str]


class LabBrowseOut(BaseModel):
    path: str
    parent: str | None = None
    dirs: list[str]
    venvs: list[str]
    files: list[str]
    isVenv: bool = False


class LabOpenIn(BaseModel):
    path: str


class LabVenvIn(BaseModel):
    path: str = ""
    create: bool = False
    name: str = ".venv"


class LabFileOut(BaseModel):
    name: str
    source: str


class LabFileIn(BaseModel):
    source: str


class LabSavedOut(BaseModel):
    name: str


class LabRunIn(BaseModel):
    name: str
    source: str | None = None


class LabRunOut(BaseModel):
    stdout: str
    stderr: str
    exitCode: int | None = None
    timedOut: bool
    running: bool = False


def _user(_user: dict = Depends(require_education_subscription)) -> dict:
    return _user


@router.get("", response_model=LabWorkspaceOut)
def get_lab(user: dict = Depends(_user)):
    try:
        return lab.list_files(user["id"])
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/browse", response_model=LabBrowseOut)
def browse_lab(path: str = "", _user: dict = Depends(_user)):
    try:
        return lab.browse(path)
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/open", response_model=LabWorkspaceOut)
def open_lab(body: LabOpenIn, user: dict = Depends(_user)):
    try:
        return lab.open_folder(user["id"], body.path)
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/venv", response_model=LabWorkspaceOut)
def choose_lab_venv(body: LabVenvIn, user: dict = Depends(_user)):
    try:
        return lab.choose_venv(user["id"], body.path, body.create, body.name)
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/files/{name}", response_model=LabFileOut)
def get_lab_file(name: str, user: dict = Depends(_user)):
    try:
        return lab.read_file(user["id"], name)
    except lab.LabNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/files/{name}", response_model=LabSavedOut)
def put_lab_file(name: str, body: LabFileIn, user: dict = Depends(_user)):
    try:
        return lab.write_file(user["id"], name, body.source)
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class LabPackageIn(BaseModel):
    name: str


class LabPackageOut(BaseModel):
    name: str
    version: str


class LabPackageListOut(BaseModel):
    packages: list[LabPackageOut]


@router.get("/packages", response_model=LabPackageListOut)
def get_lab_packages(user: dict = Depends(_user)):
    try:
        return {"packages": lab.list_packages(user["id"])}
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/packages", response_model=LabRunOut)
def install_lab_package(body: LabPackageIn, user: dict = Depends(_user)):
    try:
        return lab.install_package(user["id"], body.name)
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/output", response_model=LabRunOut)
def lab_output(user: dict = Depends(_user)):
    return lab.program_output(user["id"])


@router.post("/stop", response_model=LabRunOut)
def stop_lab(user: dict = Depends(_user)):
    return lab.stop_program(user["id"])


@router.post("/run", response_model=LabRunOut)
def run_lab_file(body: LabRunIn, user: dict = Depends(_user)):
    try:
        return lab.run_file(user["id"], body.name, body.source)
    except lab.LabNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except lab.LabBadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except lab.LabUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
