import pytest
from fastapi.testclient import TestClient

from everrag.container import AppContainer
from everrag.main import create_app


@pytest.fixture(scope="session")
def container() -> AppContainer:
    return AppContainer()


@pytest.fixture(scope="session")
def client(container: AppContainer) -> TestClient:
    return TestClient(create_app(container))
