# -*- coding: utf-8 -*-
"""仿真入口：python sim/main.py --scenario <name> [--steps N] [--list]"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "sim"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eosim.engine import SimulationEngine
from eosim.scenarios import SCENARIOS


def main():
    parser = argparse.ArgumentParser(description="具身本体论仿真")
    parser.add_argument("--scenario", default="slip_loop", help="场景名（--list 查看）")
    parser.add_argument("--steps", type=int, default=None, help="覆盖场景时长（秒/步）")
    parser.add_argument("--out", default=os.path.join(ROOT, "sim", "outputs"), help="产物目录")
    parser.add_argument("--list", action="store_true", help="列出场景")
    args = parser.parse_args()

    if args.list:
        print("可用场景：")
        for name, cls in SCENARIOS.items():
            print(f"  {name:18s} {cls.description}")
        return

    cls = SCENARIOS.get(args.scenario)
    if cls is None:
        print(f"未知场景 {args.scenario}，用 --list 查看")
        sys.exit(1)

    engine = SimulationEngine(
        scenario=cls(),
        data_path=os.path.join(ROOT, "examples", "fleet.json"),
        outputs=args.out,
    )
    engine.run(steps=args.steps)


if __name__ == "__main__":
    main()
