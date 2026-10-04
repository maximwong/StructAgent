"""Test-only installed plugin; never enabled by the normal application directory."""

from tests.plugin_fixture import contribution


def create_plugin(context):
    return contribution(context)
