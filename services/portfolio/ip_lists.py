import ipaddress
import re
from pathlib import Path


def parse_ip_list(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse IPs/CIDRs separated by commas, whitespace, or newlines.

    '#' starts a comment running to the end of its line (stripped before any
    splitting, so comments may contain commas). Fails fast on invalid entries
    so misconfiguration surfaces at startup.
    """
    comment_free = "\n".join(line.split("#", 1)[0] for line in (raw or "").splitlines())
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in re.split(r"[,\s]+", comment_free):
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise ValueError(f"Invalid IP or CIDR in access list: {entry!r}") from exc
    return networks


def load_ip_list(
    inline: str, file_path: Path | None
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Load an access list from an inline value merged with an optional file.

    A configured file that cannot be read is a startup error: silently
    ignoring it would disable the policy the operator believes is active.
    """
    raw = inline or ""
    if file_path is not None:
        raw += "\n" + file_path.read_text(encoding="utf-8")
    return parse_ip_list(raw)


def ip_in_networks(ip_str: str, networks: list) -> bool:
    try:
        address = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(address in network for network in networks)
