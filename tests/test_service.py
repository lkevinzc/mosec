import random
import re
import subprocess
import time
from threading import Thread

import requests  # type: ignore
import pytest

import mosec

TEST_PORT = "8090"
URL = f"http://localhost:{TEST_PORT}"


@pytest.fixture(scope="module")
def http_client():
    client = requests.Session()
    yield client
    client.close()


@pytest.fixture(scope="session")
def mosec_service(request):
    service = subprocess.Popen(
        ["python", f"tests/{request.param}.py", "--port", TEST_PORT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)  # wait for service to start
    assert not service.poll(), service.stdout.read().decode("utf-8")
    yield service
    service.terminate()


@pytest.mark.parametrize(
    "mosec_service, http_client",
    [
        pytest.param("square_service", "", id="normal"),
        pytest.param(
            "square_service_shm",
            "",
            marks=pytest.mark.arrow,
            id="shm_arrow",
        ),
    ],
    indirect=["mosec_service", "http_client"],
)
def test_square_service(mosec_service, http_client):
    resp = http_client.get(URL)
    assert resp.status_code == 200
    assert f"mosec/{mosec.__version__}" == resp.headers["server"]

    resp = http_client.get(f"{URL}/metrics")
    assert resp.status_code == 200

    resp = http_client.post(f"{URL}/inference", json={"msg": 2})
    assert resp.status_code == 422

    resp = http_client.post(f"{URL}/inference", data=b"bad-binary-request")
    assert resp.status_code == 400

    validate_square_service(http_client, URL, 2)


@pytest.mark.parametrize(
    "mosec_service, http_client",
    [
        pytest.param("square_service", "", id="normal"),
        pytest.param(
            "square_service_shm",
            "",
            marks=pytest.mark.arrow,
            id="shm_arrow",
        ),
    ],
    indirect=["mosec_service", "http_client"],
)
def test_square_service_mp(mosec_service, http_client):
    threads = []
    for _ in range(20):
        t = Thread(
            target=validate_square_service,
            args=(http_client, URL, random.randint(-500, 500)),
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    assert_batch_larger_than_one(http_client, URL)
    assert_empty_queue(http_client, URL)


def validate_square_service(http_client, url, x):
    resp = http_client.post(f"{url}/inference", json={"x": x})
    assert resp.json()["x"] == x ** 2


def assert_batch_larger_than_one(http_client, url):
    metrics = http_client.get(f"{url}/metrics").content.decode()
    bs = re.findall(r"batch_size_bucket.+", metrics)
    get_bs_int = lambda x: int(x.split(" ")[-1])  # noqa
    assert get_bs_int(bs[-1]) > get_bs_int(bs[0])


def assert_empty_queue(http_client, url):
    metrics = http_client.get(f"{url}/metrics").content.decode()
    remain = re.findall(r"mosec_service_remaining_task \d+", metrics)[0]
    assert int(remain.split(" ")[-1]) == 0
