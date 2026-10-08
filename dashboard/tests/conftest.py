"""Shared fixtures for all tests.

pytest.ini sets pythonpath = dashboard/src so all imports work directly.

This file intentionally defines no fixtures: the former AC/MQTT/MELCloud
fixtures referenced modules (error_tracker, controllers.state_machine,
controllers.ac_controller, subscription_manager, melcloud, mqtt_handler)
that no longer live in this service. The current test suite does not use
them. Add new shared fixtures here only when more than one test needs them.
"""
