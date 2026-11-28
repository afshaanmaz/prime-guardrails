"""run.make_client: a hosted protected model whose API key comes from a command and is refreshed."""
import time

import run


def test_hosted_client_reads_and_refreshes_key(tmp_path):
    counter = tmp_path / "n"
    counter.write_text("0")
    cmd = f"n=$(cat {counter}); n=$((n+1)); echo $n > {counter}; echo key$n"
    c = run.make_client({"base_url": "http://localhost:1/v1", "api_key_cmd": cmd}, "generator", mock=False)
    assert isinstance(c, run.RefreshingKeyClient) and c.client.api_key == "key1"
    c.chat                                    # fresh: no refresh
    assert c.client.api_key == "key1"
    c.fetched = time.time() - c.ttl_s - 1     # pretend the token is old
    c.chat
    assert c.client.api_key == "key2"


def test_local_server_needs_no_key():
    c = run.make_client({"base_url": "http://localhost:1/v1"}, "generator", mock=False)
    assert not isinstance(c, run.RefreshingKeyClient) and c.api_key == "EMPTY"
