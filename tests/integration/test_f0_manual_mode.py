"""AC integration tests — MOVED to ac-service.

These tests were originally written for the monolithic backend.
After the AC microservice refactoring (Sep 2026), all AC business logic
(state machine, MELCloud, MQTT) moved to ~/projects/smart-home/ac-service/.

The actual tests now live at:
  ~/projects/smart-home/ac-service/tests/

This stub ensures pytest does not error on the old file paths.
"""
import pytest

@pytest.mark.skip(reason="AC tests moved to ac-service — see ~/projects/smart-home/ac-service/tests/")
class TestMovedToAcService:
    def test_placeholder(self):
        pass
