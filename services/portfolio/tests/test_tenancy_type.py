"""`TenantId` must stay a distinct type, not settle back into `int`.

The guard is worth a test because it is invisible at runtime: `NewType`
erases, so nothing fails if someone re-annotates a parameter as `int` or
swaps the definition for an alias. The protection would be gone and every
test would still pass. This checks the two properties it rests on — the
distinct static type, and the transparent runtime value.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from services.portfolio.tenancy import TenantId


REPO_ROOT = Path(__file__).resolve().parents[3]

# The mistake this type exists to prevent: another id, of the same runtime
# type, in the tenant argument. Reads another tenant's documents and returns
# them as a complete, plausible answer.
_TRANSPOSED_ID = """
from services.portfolio.documents.document_service import DocumentService
from services.portfolio.tenancy import TenantId


async def read_for_posting(service: DocumentService, posting_id: int):
    return await service.read("cv", tenant_id=posting_id)
"""

_RAW_LITERAL = """
from services.portfolio.documents.document_service import DocumentService


async def read_hardcoded(service: DocumentService):
    return await service.read("cv", tenant_id=1)
"""


def _type_check(source: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    module = tmp_path / "tenant_probe.py"
    module.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "ty", "check", str(module)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_tenant_id_is_an_int_at_runtime():
    """Erased, so SQLAlchemy binding, Pydantic and the RLS parameter need no
    conversion — the type costs nothing where the value is actually used."""
    tenant = TenantId(7)
    assert tenant == 7
    assert isinstance(tenant, int)
    assert f"{tenant}" == "7"


def test_tenant_id_is_not_a_plain_alias():
    """An alias (`TenantId = int`) would type-check everything silently."""
    assert TenantId is not int
    assert getattr(TenantId, "__supertype__", None) is int


@pytest.mark.parametrize(
    ("name", "source"),
    [("transposed id", _TRANSPOSED_ID), ("raw literal", _RAW_LITERAL)],
)
def test_passing_a_plain_int_as_a_tenant_is_a_type_error(name, source, tmp_path):
    result = _type_check(source, tmp_path)
    assert result.returncode != 0, f"{name} was accepted:\n{result.stdout}"
    assert "TenantId" in result.stdout, result.stdout


def test_a_real_tenant_id_type_checks(tmp_path):
    """The guard must reject the mistake without rejecting correct code."""
    source = """
from services.portfolio.documents.document_service import DocumentService
from services.portfolio.tenancy import TenantId


async def read_for_tenant(service: DocumentService, tenant_id: TenantId):
    return await service.read("cv", tenant_id=tenant_id)
"""
    result = _type_check(source, tmp_path)
    assert result.returncode == 0, result.stdout
