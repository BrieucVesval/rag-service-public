import pytest
from pydantic import ValidationError

from rag.config import Settings


def test_defaults_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.chunk_size == 2000
    assert settings.chunk_overlap == 200
    assert settings.mistral_api_key is None


def test_env_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_CHUNK_SIZE", "1500")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.chunk_size == 1500
    assert settings.mistral_api_key is not None
    assert settings.mistral_api_key.get_secret_value() == "test-key"
    assert "test-key" not in repr(settings)


def test_overlap_must_be_smaller_than_chunk_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_CHUNK_SIZE", "100")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "100")

    with pytest.raises(ValidationError, match="chunk_overlap"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_eval_k_values_are_sorted_and_include_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_EVAL_K_VALUES", "[10, 1, 3]")
    monkeypatch.setenv("RAG_RETRIEVAL_TOP_K", "5")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.eval_k_values == [1, 3, 5, 10]


def test_eval_k_values_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_EVAL_K_VALUES", "[0, 5]")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
