from arango import ArangoClient, ArangoError
from bs4 import BeautifulSoup
from circus import get_arbiter
from circus.arbiter import Arbiter
from contextlib import suppress, contextmanager
from distutils.version import LooseVersion
from pathlib import Path
from pySmartDL import SmartDL
from sys import platform
from typing import Optional, List
import appdirs
import os
import psutil
import re
import requests
import stat
import tarfile
import time


ARANGODB_DEMON_PROCESS_NAME = "arangod"
ARANGODB_DOWNLOAD_ROOT_URL = "https://download.arangodb.com/"
CONCEPTNET_ROCKS_START_ARGUMENT = "start-arangodb"
DEFAULT_INSTALL_PATH = Path("~/.arangodb").expanduser()
DEFAULT_DATA_PATH = DEFAULT_INSTALL_PATH / "data"
DEFAULT_PORT = 8529
DEFAULT_CONNECTION_URI = f"http://localhost:{DEFAULT_PORT}"
SYSTEM_DATABASE = "_system"
DEFAULT_USERNAME = "root"
DEFAULT_PASSWORD = ""
DEFAULT_ROOT_PASSWORD = ""
START_SLEEP_DELAY = 0.1
STOP_SLEEP_DELAY = 0.1


def list_versions(clear_cache: bool = False) -> List[str]:
    graph_garden_cache_path = Path(appdirs.user_cache_dir("graph-garden"))
    arangodb_versions_path = graph_garden_cache_path / "arangodb_versions.txt"

    if not clear_cache:
        if arangodb_versions_path.is_file():
            with open(arangodb_versions_path) as f:
                result = [line.strip() for line in f.readlines()]
            return result

    req = requests.get(ARANGODB_DOWNLOAD_ROOT_URL)
    soup = BeautifulSoup(req.content, 'html.parser')
    links = [link.get("href") for link in soup.find_all("a")]
    arangodb_major_version_index_pattern = r".*/arangodb(\d+)/index\.html"
    arangodb_major_versions_links = [link for link in links if re.match(arangodb_major_version_index_pattern, link)]
    arangodb_major_versions_links = [link for link in arangodb_major_versions_links if re.match(arangodb_major_version_index_pattern, link).group(1) >= "34"]
    arangodb_major_versions_linux_links = [link.replace("index.html", "Community/Linux/index.html") for link in arangodb_major_versions_links]
    result = []
    for url in arangodb_major_versions_linux_links:
        req = requests.get(url)
        soup = BeautifulSoup(req.content, 'html.parser')
        links = [link.get("href") for link in soup.find_all("a")]
        arangodb_archive_pattern = r"^arangodb\d+-linux-(\d+\.\d+\.\d+(-\d+)?)\.tar\.gz$"
        archive_links = [link for link in links if re.match(arangodb_archive_pattern, link)]
        for archive_link in archive_links:
            match = re.match(arangodb_archive_pattern, archive_link)
            result.append(match.group(1))
    result = sorted(result, key=lambda x: LooseVersion(x))
    graph_garden_cache_path.mkdir(parents=True, exist_ok=True)
    with open(arangodb_versions_path, "w") as f:
        for version in result:
            f.write(f"{version}\n")
    return result


def get_exe_path(path: Path = DEFAULT_INSTALL_PATH, program_name: str = "arangodb") -> Path:
    return path / "bin" / program_name if path.name != "arangodb" else path


def install(path: Path = DEFAULT_INSTALL_PATH, version: Optional[str] = None) -> None:
    if platform != "linux":
        raise RuntimeError("Only GNU/Linux is supported!")

    path = path.expanduser()

    if path.exists():
        if path.is_dir():
            with suppress(StopIteration):
                next(path.iterdir())
                raise FileExistsError(f"Directory exists and is not empty: {path}")
        else:
            raise FileExistsError(f"File exists: {path}")

    path.mkdir(parents=True, exist_ok=True)

    if version is None:
        version = list_versions()[-1]
    version = LooseVersion(version)
    top_dir_name = f"arangodb{version.version[0]}{version.version[1]}"
    file_name = f"arangodb{version.version[0]}-linux-{version}.tar.gz"
    url = f"{ARANGODB_DOWNLOAD_ROOT_URL}{top_dir_name}/Community/Linux/{file_name}"
    downloader = SmartDL(url, str(path))
    downloader.start()
    archive_path_str = downloader.get_dest()
    tar = tarfile.open(archive_path_str, "r:gz")
    tar.extractall(path)
    tar.close()
    Path(archive_path_str).unlink()
    arangodb_dir_path = next(path.glob("arangodb3*"))
    for p in arangodb_dir_path.iterdir():
        p.rename(path / p.name)
    arangodb_dir_path.rmdir()
    for p in (path / "bin").iterdir():
        p.chmod(p.stat().st_mode | stat.S_IEXEC)


def get_arangodb_daemon_process(port: int = DEFAULT_PORT) -> Optional[psutil.Process]:
    try:
        result = next(proc for proc in psutil.process_iter() if proc.name() == ARANGODB_DEMON_PROCESS_NAME)
        if next(True for connection in result.connections() if connection.laddr.port == port):
            return result
    except StopIteration:
        return None


def is_running(
        connection_uri: str = DEFAULT_CONNECTION_URI,
        database: str = SYSTEM_DATABASE,
        username: str = DEFAULT_USERNAME,
        password: str = DEFAULT_PASSWORD,
) -> bool:
    if not bool(get_arangodb_daemon_process()):
        return False
    client = ArangoClient(hosts=connection_uri)
    db = client.db(name=database, username=username, password=password)
    try:
        db.version()
        return True
    except ArangoError:
        return False


def start(
        exe_path: Path = DEFAULT_INSTALL_PATH,
        data_path: Path = DEFAULT_DATA_PATH,
        connection_uri: str = DEFAULT_CONNECTION_URI,
        database: str = SYSTEM_DATABASE,
        username: str = DEFAULT_USERNAME,
        password: str = DEFAULT_PASSWORD,
        close_stdout_and_stderr: bool = False,
) -> Arbiter:
    if exe_path.name != "arangodb":
        exe_path = get_exe_path(exe_path)
    working_dir_path = exe_path.parent

    env_path = f"{os.environ['PATH']}:{working_dir_path}"

    arbiter = get_arbiter([{
        "cmd": f"{exe_path} --starter.mode single --starter.data-dir {data_path}",
        "working_dir": working_dir_path,
        "env": {"PATH": env_path},
        "close_child_stdout": close_stdout_and_stderr,
        "close_child_stderr": close_stdout_and_stderr,
    }], background=True)

    arbiter.start()

    while not is_running(connection_uri=connection_uri, database=database, username=username, password=password):
        time.sleep(START_SLEEP_DELAY)

    return arbiter


def stop():
    arangodb_daemon_process = get_arangodb_daemon_process()
    if arangodb_daemon_process is not None:
        arangodb_launch_script_process = arangodb_daemon_process.parent()
        arangodb_launch_script_parent_process = arangodb_launch_script_process.parent()
        if CONCEPTNET_ROCKS_START_ARGUMENT in arangodb_launch_script_parent_process.cmdline():
            arangodb_launch_script_parent_process.terminate()
        else:
            arangodb_launch_script_process.terminate()


def stop_arbiter(arbiter: Optional[Arbiter]):
    if arbiter is None:
        return

    arbiter.stop()
    # noinspection PyUnresolvedReferences
    while arbiter.is_alive():
        time.sleep(STOP_SLEEP_DELAY)


def start_if_not_running(
        connection_uri: str = DEFAULT_CONNECTION_URI,
        root_password: str = DEFAULT_ROOT_PASSWORD,
        arangodb_exe_path: Path = DEFAULT_INSTALL_PATH,
        data_path: Path = DEFAULT_DATA_PATH,
        close_stdout_and_stderr: bool = False,
):
    root_credentials = {
        "username": "root",
        "password": root_password,
    }
    if not is_running(connection_uri=connection_uri, database=SYSTEM_DATABASE, **root_credentials):
        return start(
            exe_path=arangodb_exe_path,
            data_path=data_path,
            connection_uri=connection_uri,
            database=SYSTEM_DATABASE,
            close_stdout_and_stderr=close_stdout_and_stderr,
            **root_credentials,
        )
    else:
        return None


@contextmanager
def instance(
        connection_uri: str = DEFAULT_CONNECTION_URI,
        root_password: str = DEFAULT_ROOT_PASSWORD,
        arangodb_exe_path: Path = DEFAULT_INSTALL_PATH,
        data_path: Path = DEFAULT_DATA_PATH,
        close_stdout_and_stderr: bool = False,
):
    arangodb_arbiter = start_if_not_running(
        connection_uri=connection_uri,
        root_password=root_password,
        arangodb_exe_path=arangodb_exe_path,
        data_path=data_path,
        close_stdout_and_stderr=close_stdout_and_stderr,
    )

    yield

    stop_arbiter(arangodb_arbiter)
