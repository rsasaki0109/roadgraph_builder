from __future__ import annotations

import pytest


@pytest.fixture
def sample_csv_path(tmp_path):
    p = tmp_path / "traj.csv"
    p.write_text(
        "timestamp,x,y\n"
        "0.0,0.0,0.0\n"
        "1.0,10.0,0.0\n"
        "2.0,100.0,0.0\n"
        "3.0,110.0,0.0\n",
        encoding="utf-8",
    )
    return p
