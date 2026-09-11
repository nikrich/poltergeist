from __future__ import annotations

import logging

from ghostbrain.api import runtime


def test_file_logging_quiets_chatty_libraries():
    handler = runtime.setup_file_logging()
    try:
        for name in ("httpx", "httpcore", "huggingface_hub", "transformers", "sentence_transformers", "filelock", "urllib3"):
            assert logging.getLogger(name).level == logging.WARNING, name
        assert set(runtime.QUIET_LOGGERS) >= {"httpx", "huggingface_hub"}
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def test_uvicorn_is_left_to_propagate_to_root():
    from ghostbrain.api.__main__ import _uvicorn_kwargs

    kwargs = _uvicorn_kwargs(app=object(), port=1234)
    assert kwargs["log_config"] is None
    assert kwargs["access_log"] is False
    assert kwargs["port"] == 1234
