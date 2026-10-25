"""Time the resident summary ("Why?") on Gemini: each model, N residents from a real scenario, p50/p95/max.

    uv run --env-file .env python tools/why_latency.py                 # 12 residents, heat_severe_none
    uv run --env-file .env python tools/why_latency.py --n 20 --scenario cold_extreme_none

Needs GEMINI_API_KEY (the same key as the Ask chat). Prints a one-line verdict against the inspector's 8 s fallback.
"""
import argparse
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import server  # noqa: E402
from backend import ask  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--scenario", default="heat_severe_none")
p.add_argument("--n", type=int, default=12)
args = p.parse_args()
if not ask.enabled():
    sys.exit("GEMINI_API_KEY is not set. Put it in .env and run with: uv run --env-file .env python tools/why_latency.py")

n_res = len(server.meta()["residents"])
residents = [round(i * (n_res - 1) / max(args.n - 1, 1)) for i in range(args.n)]
for model in server.WHY_MODELS:
    times, words, fails = [], [], 0
    for rid in residents:
        f = server.facts(args.scenario, rid)
        t0 = time.perf_counter()
        try:
            content, _ = ask.gemini([{"role": "user", "parts": [{"text": server.json.dumps({**f, "baseline_day": None})}]}],
                                    server.SYSTEM, models=[model])
            text = "".join(x.get("text", "") for x in content.get("parts", []))
            times.append(time.perf_counter() - t0)
            words.append(len(text.split()))
        except Exception as e:
            fails += 1
            print(f"  {model} resident {rid}: {e}")
    if not times:
        print(f"{model}: every call failed")
        continue
    q = statistics.quantiles(times, n=20) if len(times) > 1 else times * 19
    print(f"{model}: p50 {statistics.median(times):.2f} s · p95 {q[18]:.2f} s · max {max(times):.2f} s · "
          f"{statistics.mean(words):.0f} words · {fails} failed of {len(residents)}")
    print("  verdict:", "fine for a click (under 3 s typical)" if statistics.median(times) < 3
          else "noticeable; keep the cache and the offline fallback" if q[18] < server.WHY_TIMEOUT
          else f"too slow: p95 over the {server.WHY_TIMEOUT:g} s fallback, so users will often see the offline text")
