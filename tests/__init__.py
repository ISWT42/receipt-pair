"""The tests need no network and no model. This guard makes any attempt to open a connection fail loudly."""

import socket


def _no_network(*args, **kwargs):
    raise AssertionError("the tests must not use the network")


socket.socket.connect = _no_network
socket.socket.connect_ex = _no_network
