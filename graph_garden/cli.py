from graph_garden import arangodb
from pathlib import Path
from typing import Optional
import sys
import typer


arangodb_app = typer.Typer()
app = typer.Typer()
app.add_typer(arangodb_app, name="arangodb")


@arangodb_app.command()
def list_versions(clear_cache: bool = False):
    for version in arangodb.list_versions(clear_cache=clear_cache):
        print(version)


@arangodb_app.command()
def install(path: Path = arangodb.DEFAULT_INSTALL_PATH, version: Optional[str] = None):
    arangodb.install(path=path, version=version)


@arangodb_app.command()
def start(
        exe_path: Path = arangodb.DEFAULT_INSTALL_PATH,
        data_path: Path = arangodb.DEFAULT_DATA_PATH,
        connection_uri: str = arangodb.DEFAULT_CONNECTION_URI,
        database: str = arangodb.SYSTEM_DATABASE,
        username: str = arangodb.DEFAULT_USERNAME,
        password: str = arangodb.DEFAULT_PASSWORD,
):
    arangodb.start(
        exe_path=exe_path,
        data_path=data_path,
        connection_uri=connection_uri,
        database=database,
        username=username,
        password=password,
    )


@arangodb_app.command()
def stop():
    arangodb.stop()


@arangodb_app.command()
def is_running(
        connection_uri: str = arangodb.DEFAULT_CONNECTION_URI,
        database: str = arangodb.SYSTEM_DATABASE,
        username: str = arangodb.DEFAULT_USERNAME,
        password: str = arangodb.DEFAULT_PASSWORD,
):
    status_code = (
        0
        if arangodb.is_running(
            connection_uri=connection_uri,
            database=database,
            username=username,
            password=password,
        ) else
        1
    )
    sys.exit(status_code)
