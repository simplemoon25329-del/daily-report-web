"""Read the DeepSeek credential only from server-side configuration."""

import os

import streamlit as st


def get_deepseek_api_key():
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    try:
        secret = st.secrets.get("DEEPSEEK_API_KEY")
    except Exception:
        return ""
    return secret.strip() if isinstance(secret, str) else ""
