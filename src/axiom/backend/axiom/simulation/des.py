"""Discrete-event queue simulation backed by SimPy."""

from __future__ import annotations

import random

import simpy


def simulate_queue(
    arrival_rate: float = 8,
    service_rate: float = 10,
    servers: int = 1,
    horizon: float = 8,
    seed: int = 7,
) -> dict:
    if arrival_rate <= 0 or service_rate <= 0 or horizon <= 0 or servers < 1:
        raise ValueError("arrival rate, service rate, servers, and horizon must be positive")
    rng = random.Random(seed)
    waits: list[float] = []
    sojourns: list[float] = []
    served = 0
    busy = 0.0
    timeline: list[dict] = []
    env = simpy.Environment()
    desk = simpy.Resource(env, capacity=int(servers))

    def source():
        nonlocal served
        while True:
            yield env.timeout(rng.expovariate(arrival_rate))
            if env.now >= horizon:
                break
            env.process(customer(env.now))

    def customer(arrived: float):
        nonlocal served, busy
        with desk.request() as request:
            yield request
            started = env.now
            waits.append(started - arrived)
            duration = rng.expovariate(service_rate)
            busy += duration
            yield env.timeout(duration)
            sojourns.append(env.now - arrived)
            served += 1
            if len(timeline) < 80:
                timeline.append({"t": round(env.now, 4), "wait": waits[-1], "served": served})

    env.process(source())
    env.run(until=horizon)
    capacity_time = horizon * servers
    utilization = busy / capacity_time if capacity_time else 0
    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "arrival_rate": arrival_rate,
        "service_rate": service_rate,
        "servers": int(servers),
        "horizon": horizon,
        "seed": seed,
        "served": served,
        "avg_wait": avg(waits),
        "avg_sojourn": avg(sojourns),
        "utilization": min(utilization, 1.0),
        "max_wait": max(waits) if waits else 0.0,
        "timeline": timeline,
    }
