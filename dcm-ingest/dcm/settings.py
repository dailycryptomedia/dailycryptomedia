"""Konfigurasi terpusat.

Semua nilai yang berbeda antar lingkungan (kunci API, lokasi basis data,
agresivitas polling) dibaca dari variabel lingkungan. Berkas YAML di config/
hanya berisi hal yang sama di semua lingkungan.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


class Settings(BaseSettings):
    """Konfigurasi runtime, dibaca dari .env atau variabel lingkungan."""

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="DCM_", extra="ignore"
    )

    # --- Basis data -------------------------------------------------------
    database_url: str = "sqlite:///dcm.db"

    # --- Anthropic --------------------------------------------------------
    anthropic_api_key: str = Field(default="", description="Kunci API Anthropic")
    # Sonnet dipakai sebagai bawaan: kualitas judul jauh lebih baik dan judul
    # adalah hal pertama yang dilihat pembaca. Untuk volume sangat besar,
    # ganti ke claude-haiku-4-5-20251001 dan bandingkan hasilnya dulu.
    translate_model: str = "claude-sonnet-5"
    translate_batch_size: int = 8
    translate_max_retries: int = 3

    # --- Pengambilan ------------------------------------------------------
    fetch_concurrency: int = 4
    poll_interval_minutes: int = 10

    # --- Penyaringan ------------------------------------------------------
    # Item di bawah ambang ini tidak ditampilkan di situs publik. Menyaring
    # rilis pers dan berita yang terlalu jauh dari minat pembaca Indonesia.
    min_publish_score: int = 20
    dedupe_similarity_threshold: float = 0.82
    max_article_age_days: int = 14

    # --- API --------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_yaml(name: str) -> dict[str, Any]:
    """Membaca berkas YAML dari config/, hasilnya di-cache."""
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Berkas konfigurasi tidak ditemukan: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def sources_config() -> dict[str, Any]:
    return load_yaml("sources.yaml")


def glossary_config() -> dict[str, Any]:
    return load_yaml("glossary.yaml")
