"""Unit tests for input sanitization (Spec 18, Task 1.0)."""

from __future__ import annotations

from app.chat.sanitize import sanitize_user_input


class TestSanitizeUserInput:
    def test_passthrough_normal_text(self) -> None:
        """Normal ASCII text passes through unchanged."""
        assert sanitize_user_input("Hello, world!") == "Hello, world!"

    def test_preserves_newlines(self) -> None:
        r"""Newlines (\x0A) are preserved in multi-sentence queries."""
        text = "line one\nline two\nline three"
        assert sanitize_user_input(text) == text

    def test_strips_null_bytes(self) -> None:
        """Null bytes (\\x00) are removed."""
        assert sanitize_user_input("hello\x00world") == "helloworld"

    def test_strips_tabs(self) -> None:
        """Tab characters (\\x09) are removed."""
        assert sanitize_user_input("hello\tworld") == "helloworld"

    def test_strips_carriage_return(self) -> None:
        """Carriage return (\\x0D) is removed."""
        assert sanitize_user_input("hello\r\nworld") == "hello\nworld"

    def test_strips_del_character(self) -> None:
        """DEL character (\\x7F) is removed."""
        assert sanitize_user_input("hello\x7fworld") == "helloworld"

    def test_strips_multiple_control_chars(self) -> None:
        """Multiple control characters are all stripped in a single pass."""
        text = "\x01\x02hello\x03\x04 world\x1f"
        assert sanitize_user_input(text) == "hello world"

    def test_empty_string(self) -> None:
        """Empty input returns empty output."""
        assert sanitize_user_input("") == ""
