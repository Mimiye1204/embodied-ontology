# -*- coding: utf-8 -*-
"""场景注册表：新增场景 = 写一个 Scenario 子类 + 在此注册。"""
from .dispatch_fleet import DispatchFleetScenario
from .fault_sensor import FaultSensorScenario
from .slip_loop import SlipLoopScenario

SCENARIOS = {
    cls.name: cls
    for cls in [FaultSensorScenario, DispatchFleetScenario, SlipLoopScenario]
}
