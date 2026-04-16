from __future__ import annotations

from roadgraph_builder.cli.doctor import run_doctor


def test_doctor_exits_zero():
    assert run_doctor() == 0
