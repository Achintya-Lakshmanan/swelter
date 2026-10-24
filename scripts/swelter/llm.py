"""LLM planner: Claude decides each persona type's day *inside the schema*.

Structured outputs constrain every hour to enums (activity / place slot / reason code), so no free text can
reach the map. The verifier still checks each resident's resolved day; failures are re-prompted once with
the violations, then fall back to the rule planner (counted in the run's verifier stats).

Needs ANTHROPIC_API_KEY (or an `ant auth login` profile). Offline batch only — the demo replays stored runs.
"""
import json
import random
from concurrent.futures import ThreadPoolExecutor

import anthropic

from .hazards import HAZARDS, HOURS
from .plan import ACTIVITIES, ACTIVITY_LIST, SLOT_LIST, refuge_place, travel
from .rules import REASONS, RULES_TEXT, baseline_day
from .world import HOURS_OPEN, dist_m

MODEL = "claude-opus-5-5"


def _schema(type_ids):
    step = {
        "type": "object",
        "properties": {
            "activity": {"type": "string", "enum": ACTIVITY_LIST},
            "place": {"type": "string", "enum": SLOT_LIST},
            "why": {"type": "string", "enum": list(REASONS)},
        },
        "required": ["activity", "place", "why"],
        "additionalProperties": False,
    }
    plan = {
        "type": "object",
        "properties": {
            "type_id": {"type": "string", "enum": type_ids},
            "aware": {"type": "boolean"},
            "ac_use": {"type": "boolean"},
            "mask": {"type": "boolean"},
            "heat_on": {"type": "boolean"},
            "hours": {"type": "array", "items": step},
        },
        "required": ["type_id", "aware", "ac_use", "mask", "heat_on", "hours"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"plans": {"type": "array", "items": plan}},
            "required": ["plans"], "additionalProperties": False}


SYSTEM = f"""You simulate how Philadelphia residents spend one weekday during a hazard, for a city planning sandbox.
For each persona you get, return a plausible 17-hour day ({HOURS[0]}:00-{HOURS[-1]}:00), one step per hour, using ONLY
the listed activities, place slots and reason codes. Be realistic, not ideal: many people miss warnings, cannot reach
refuges, or must keep working. A place slot marked unavailable must not be used. Closed places must not be used
outside their hours. Trips longer than ~30 minutes need a 'commute' hour whose place is the destination.

Activities: {json.dumps({k: v[1] for k, v in ACTIVITIES.items()})}
Reason codes: {json.dumps(REASONS)}
{RULES_TEXT}"""


def _persona_card(world, r, scenario, slots):
    home = slots["home"]
    refuge, rhours = refuge_place(world, r, scenario)
    lines = [
        f"type_id: {r['type']}",
        f"role={r['role']} age={r['age']} lives_alone={r['alone']} car={r['car']} home_ac={r['ac']} "
        f"reliable_heat={r['heat']} asthma_copd={r['respiratory']} low_income={r['poverty']} "
        f"home_flood_prone={r['flood_zone']} neighborhood={r['tract_name']}",
        "usual weekday (a real ATUS diary of someone like them): "
        + ", ".join(f"{h}:{a}@{s}" for h, (a, s, _) in zip(HOURS, baseline_day(r, scenario["hazard"], random.Random(r["id"])))),
        "place slots (minutes from home, open hours):",
    ]
    for s in SLOT_LIST:
        p = slots.get(s)
        if p is None:
            lines.append(f"  {s}: unavailable")
            continue
        mins, mode = travel(r, home, p)
        hrs = (f"{rhours[0]}-{rhours[1]}" if s == "refuge" else
               "always" if s in ("home", "work", "campus", "park") else "%d-%d" % HOURS_OPEN.get(p["kind"], (0, 24)))
        lines.append(f"  {s}: {p['name'] or p['kind']} ({mins:.0f} min by {mode}, open {hrs})")
    return "\n".join(lines)


class LLMPlanner:
    name = "llm"

    def __init__(self, world, model=MODEL, effort="low", batch_size=6, workers=6):
        self.w = world
        self.client = anthropic.Anthropic()
        self.model, self.effort, self.batch_size, self.workers = model, effort, batch_size, workers
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def _call(self, scenario, cards, type_ids, intensity, feedback=""):
        hz = HAZARDS[scenario["hazard"]]
        iv = hz["interventions"][scenario["intervention"]]
        situation = (
            f"Hazard: {hz['label']} ({hz['levels'][scenario['level']]['label']}). Hourly {hz['unit']}: "
            + ", ".join(f"{h}:00={v:g}" for h, v in zip(HOURS, intensity))
            + f"\nIntervention: {iv['label']}. {iv.get('desc', '')}"
        )
        msg = situation + "\n\nPersonas:\n\n" + "\n\n".join(cards) + feedback
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": _schema(type_ids)}},
            messages=[{"role": "user", "content": msg}],
        )
        self.usage["calls"] += 1
        self.usage["input_tokens"] += resp.usage.input_tokens
        self.usage["output_tokens"] += resp.usage.output_tokens
        if resp.stop_reason == "refusal":
            return {}
        text = next(b.text for b in resp.content if b.type == "text")
        return {p["type_id"]: p for p in json.loads(text)["plans"]}

    def plan_types(self, scenario, reps, slots_by_id, intensity, verify):
        """reps: {type_id: representative resident}. Returns {type_id: plan or None}."""
        ids = list(reps)
        batches = [ids[i:i + self.batch_size] for i in range(0, len(ids), self.batch_size)]

        def run(batch):
            cards = [_persona_card(self.w, reps[t], scenario, slots_by_id[reps[t]["id"]]) for t in batch]
            try:
                got = self._call(scenario, cards, batch, intensity)
            except anthropic.APIError as e:
                print(f"    LLM batch failed: {e}")
                return {}
            # one corrective round for plans that fail verification
            for t in batch:
                p = got.get(t)
                if p is None:
                    continue
                bad = verify(reps[t], p)
                if bad:
                    fb = "\n\nYour previous plan for this persona was rejected by the plausibility verifier:\n- " + "\n- ".join(bad[:8])
                    try:
                        again = self._call(scenario, [cards[batch.index(t)]], [t], intensity, fb).get(t)
                    except anthropic.APIError:
                        again = None
                    got[t] = again if again and not verify(reps[t], again) else None
            return got

        out = {}
        with ThreadPoolExecutor(self.workers) as ex:
            for got in ex.map(run, batches):
                out.update(got)
        return out


def type_key(world, r, scenario):
    """Persona type for the LLM, plus whether the refuge is walkable (it changes the plausible day)."""
    refuge, _ = refuge_place(world, r, scenario)
    if refuge is None:
        return r["type"]
    home = world.by_id[r["home"]]
    d = dist_m(home["lat"], home["lon"], refuge["lat"], refuge["lon"])
    return r["type"] + ("|refuge_near" if d < 1000 else "|refuge_far")
