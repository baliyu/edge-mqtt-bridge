"""TLS for the connection to the broker: the client checks the broker's certificate against a certificate authority file you name."""
from __future__ import annotations

import ssl
from typing import Optional

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def make_context(ca_file: str) -> ssl.SSLContext:
    """A client context that trusts ONLY the given authority (not the system's list), checks the certificate's hostname, and
    refuses anything older than TLS 1.2."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname       # create_default_context sets these; fail loudly if that ever changes
    return ctx


def plaintext_warning(host: str, user: Optional[str], ca_file: Optional[str]) -> Optional[str]:
    """A warning for the one risky combination: a password sent without TLS to a broker that is not on this machine."""
    if ca_file or not user or host in LOCAL_HOSTS:
        return None
    return (f"WARNING: the password for {user!r} is being sent to {host} without TLS, so anyone on the network path can read it. "
            f"Use --mqtt-tls-ca with the broker's certificate authority.")
