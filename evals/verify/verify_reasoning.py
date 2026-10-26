#!/usr/bin/env python3
"""Recompute every reasoning answer from scratch and check evals/reasoning.jsonl against it.

Each item has a compute function below (brute force wherever possible) that derives the expected
answer from the problem's parameters. The script also checks the schema from evals/SCHEMA.md,
that each prompt still contains the parameters the computation uses, that each prompt ends with an
ANSWER format line, and that the canonical answer passes the item's own `match` rule.

Run: /opt/homebrew/bin/python3.13 evals/verify/verify_reasoning.py   (stdlib only)
"""
import contextlib
import datetime as dt
import io
import itertools
import json
import re
import sys
from collections import Counter
from fractions import Fraction
from math import gcd
from pathlib import Path
from zoneinfo import ZoneInfo

EVALS = Path(__file__).resolve().parents[1]
JSONL = EVALS / "reasoning.jsonl"


def run_program(src):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(src, "<item>", "exec"), {"__name__": "__item__"})
    return buf.getvalue().strip()


# ---------------------------------------------------------------- programs shown in prompts

P003 = '''s = "conductor"
for i in range(1, 6):
    s = s[i:] + s[:i][::-1]
    s = "".join(chr((ord(c) - 97 + i) % 26 + 97) if j % 2 == 0 else c for j, c in enumerate(s))
print(s)
'''

P009 = '''from collections import deque

arrivals = deque([(0, "a", 5), (1, "b", 3), (2, "c", 6), (6, "d", 2), (7, "e", 4)])
quantum = 2
clock = 0
ready = deque()
done = []

def admit():
    while arrivals and arrivals[0][0] <= clock:
        _, name, need = arrivals.popleft()
        ready.append([name, need])

admit()
while ready or arrivals:
    if not ready:
        clock = arrivals[0][0]
        admit()
    job = ready.popleft()
    run = min(quantum, job[1])
    clock += run
    job[1] -= run
    admit()
    if job[1]:
        ready.append(job)
    else:
        done.append(f"{job[0]}:{clock}")
print(",".join(done))
'''

P010 = '''x = 0
for i, ch in enumerate("orkes"):
    x = ((x << 5) ^ (x >> 3) ^ (ord(ch) * (i + 1))) & 0xFFFF
print(x)
'''

# ---------------------------------------------------------------- compute functions


def r001():
    return str(sum(1 for n in range(1, 1_000_000) if sum(map(int, str(n))) == 27))


SEATING_PEOPLE = ["Ana", "Ben", "Cai", "Dev", "Eli", "Fay", "Gus"]


def r002():
    sols = []
    for order in itertools.permutations(SEATING_PEOPLE):
        p = {name: i for i, name in enumerate(order)}
        if (abs(p["Ben"] - p["Dev"]) == 3 and abs(p["Eli"] - p["Gus"]) > 1 and p["Dev"] > p["Fay"]
                and p["Fay"] > p["Cai"] and p["Gus"] > p["Eli"] and abs(p["Ana"] - p["Eli"]) == 3
                and p["Fay"] - p["Ana"] == 1):
            sols.append(order)
    assert len(sols) == 1, f"seating not unique: {len(sols)}"
    return ", ".join(sols[0])


def r003():
    return run_program(P003)


def r004():
    ny, ldn = ZoneInfo("America/New_York"), ZoneInfo("Europe/London")
    out = []
    for day in (2, 9, 16, 23, 30):
        t = dt.datetime(2026, 3, day, 9, 30, tzinfo=ny)
        assert t.weekday() == 0
        out.append(t.astimezone(ldn).strftime("%H:%M"))
    return ", ".join(out)


def r005():
    return str(sum(1 for n in range(1, 1_000_001) if sum(n % d == 0 for d in (4, 6, 9)) == 2))


def r006():
    hits = sum(1 for r in itertools.product(range(1, 7), repeat=4) if max(r) == 2 * min(r))
    f = Fraction(hits, 6 ** 4)
    return f"{f.numerator}/{f.denominator}"


def r007():
    return str(sum(1 for y in range(2026, 2031) for m in range(1, 13) if dt.date(y, m, 13).weekday() == 4))


def r008():
    start = dt.datetime(2026, 12, 24, 16, 30)
    assert start.weekday() == 3  # Thursday
    holidays = {dt.date(2026, 12, 25), dt.date(2027, 1, 1)}
    need = 20 * 60
    t = start
    while need:
        open_now = t.weekday() < 5 and t.date() not in holidays and 9 <= t.hour < 17
        t += dt.timedelta(minutes=1)
        if open_now:
            need -= 1
    return t.strftime("%Y-%m-%d %H:%M")


def r009():
    return run_program(P009)


def r010():
    return run_program(P010)


ROADS = [("A", "B", 4), ("A", "C", 1), ("A", "D", 7), ("B", "E", 3), ("B", "G", 10), ("C", "B", 2), ("C", "D", 5),
         ("C", "F", 9), ("D", "E", 1), ("D", "G", 6), ("E", "F", 2), ("E", "H", 12), ("F", "G", 1), ("F", "H", 8),
         ("G", "H", 3)]


def r011():
    adj = {}
    for a, b, w in ROADS:
        adj.setdefault(a, []).append((b, w))
    best = None

    def dfs(node, seen, cost):
        nonlocal best
        if node == "H":
            if "D" in seen and (best is None or cost < best):
                best = cost
            return
        for nxt, w in adj.get(node, []):
            if nxt not in seen:
                dfs(nxt, seen | {nxt}, cost + w)

    dfs("A", {"A"}, 0)
    return str(best)


DAG = ["S->A", "S->B", "S->C", "A->D", "A->E", "B->D", "B->E", "B->F", "C->E", "C->F", "D->G", "D->T", "E->G",
       "E->H", "F->H", "F->T", "G->T", "H->T", "A->B", "C->B"]


def r012():
    adj = {}
    for e in DAG:
        a, b = e.split("->")
        adj.setdefault(a, []).append(b)

    def count(n):
        return 1 if n == "T" else sum(count(m) for m in adj.get(n, []))

    return str(count("S"))


JOBS = {"J1": (4, 6), "J2": (2, 5), "J3": (5, 14), "J4": (3, 9), "J5": (6, 18), "J6": (2, 11), "J7": (4, 20),
        "J8": (3, 13)}


def r013():
    names = list(JOBS)
    best = 0
    for perm in itertools.permutations(names):
        t, on_time = 0, 0
        for j in perm:
            t += JOBS[j][0]
            on_time += t <= JOBS[j][1]
        best = max(best, on_time)
    return str(best)


UPGRADES = {"U1": (28, 40), "U2": (35, 52), "U3": (17, 22), "U4": (40, 61), "U5": (12, 14), "U6": (23, 33),
            "U7": (9, 10), "U8": (31, 45)}


def r014():
    names = list(UPGRADES)
    best = 0
    for k in range(len(names) + 1):
        for combo in itertools.combinations(names, k):
            s = set(combo)
            if "U4" in s and "U3" not in s:
                continue
            if "U2" in s and "U8" in s:
                continue
            cost = sum(UPGRADES[u][0] for u in s)
            if cost <= 100:
                best = max(best, sum(UPGRADES[u][1] for u in s))
    return str(best)


def r015():
    bag = ["r"] * 4 + ["b"] * 3 + ["g"] * 2
    combos = list(itertools.combinations(range(9), 4))
    hits = sum(1 for c in combos if {bag[i] for i in c} == {"r", "b", "g"})
    f = Fraction(hits, len(combos))
    return f"{f.numerator}/{f.denominator}"


OWNERS = ["Ivy", "Jon", "Kim", "Leo"]
COLORS = ["red", "green", "blue", "white"]
PETS = ["cat", "dog", "fish", "bird"]


def r016():
    sols = []
    for o in itertools.permutations(OWNERS):
        for c in itertools.permutations(COLORS):
            for p in itertools.permutations(PETS):
                pos = {v: i for perm in (o, c, p) for i, v in enumerate(perm)}
                if (abs(pos["Ivy"] - pos["Kim"]) == 1  # Ivy and Kim live next door to each other
                        and pos["blue"] - pos["Jon"] == 1  # Jon lives immediately to the left of the blue house
                        and pos["red"] > pos["Leo"]  # red house somewhere to the right of Leo's house
                        and pos["green"] != pos["Leo"]  # Leo does not live in the green house
                        and abs(pos["green"] - pos["Kim"]) >= 2  # Kim at least two houses from the green house
                        and abs(pos["dog"] - pos["Jon"]) >= 2  # dog at least two houses from Jon
                        and pos["Jon"] - pos["fish"] == 1  # fish immediately to the left of Jon's house
                        and abs(pos["bird"] - pos["Ivy"]) == 1):  # bird lives next door to Ivy
                    sols.append((o, p))
    assert len(sols) == 1, f"house puzzle not unique: {len(sols)}"
    o, p = sols[0]
    return ", ".join(list(o) + list(p))


def r017():
    t = dt.datetime(2026, 10, 30, 15, 0, tzinfo=ZoneInfo("Australia/Sydney"))
    assert t.weekday() == 4
    zones = ["America/Los_Angeles", "Europe/London", "Asia/Tokyo"]
    return ", ".join(t.astimezone(ZoneInfo(z)).strftime("%Y-%m-%d %H:%M") for z in zones)


def r018():
    a, b, c = Fraction(1, 6), Fraction(1, 9), Fraction(-1, 12)  # tanks per hour
    level = (a + b) * 2
    target = Fraction(3, 4)
    assert level < target
    hours = 2 + (target - level) / (b + c)
    minutes = hours * 60
    assert minutes.denominator == 1
    return str(minutes.numerator)


def r019():
    n = 0
    for s in itertools.product("ABC", repeat=8):
        if all(s[i] != s[i + 1] for i in range(7)) and min(Counter(s)[ch] for ch in "ABC") >= 2:
            n += 1
    return str(n)


def r020():
    n = 10_001
    while not (n % 7 == 3 and n % 11 == 4 and n % 13 == 5 and n % 3 == 2):
        n += 1
    return str(n)


COMPUTE = {f"reasoning-{i:03d}": fn for i, fn in enumerate(
    [r001, r002, r003, r004, r005, r006, r007, r008, r009, r010, r011, r012, r013, r014, r015, r016, r017, r018,
     r019, r020], start=1)}

# Parameters each prompt must still contain (catches drift between prompt text and computation).
MUST_CONTAIN = {
    "reasoning-001": ["999999", "27"],
    "reasoning-002": ["Exactly two people sit between Ben and Dev", "Eli and Gus do not sit next to each other",
                      "Dev sits somewhere to the right of Fay", "Fay sits somewhere to the right of Cai",
                      "Gus sits somewhere to the right of Eli", "Exactly two people sit between Ana and Eli",
                      "Ana sits immediately to the left of Fay", "numbered 1 to 7 from left to right"],
    "reasoning-003": [P003.strip()],
    "reasoning-004": ["09:30 New York", "March 2, March 9, March 16, March 23 and March 30, 2026", "London"],
    "reasoning-005": ["1,000,000", "4, 6 and 9", "exactly two"],
    "reasoning-006": ["Four fair six-sided dice", "exactly twice the smallest"],
    "reasoning-007": ["Friday the 13th", "January 1, 2026", "December 31, 2030"],
    "reasoning-008": ["December 24, 2026 at 16:30", "20 business hours", "09:00 to 17:00",
                      "December 25, 2026 and January 1, 2027"],
    "reasoning-009": [P009.strip()],
    "reasoning-010": [P010.strip()],
    "reasoning-011": [", ".join(f"{a}->{b} {w}" for a, b, w in ROADS), "passes through D"],
    "reasoning-012": [", ".join(DAG)],
    "reasoning-013": [f"{j}: {d} h, deadline {dl}" for j, (d, dl) in JOBS.items()],
    "reasoning-014": [f"{u}: costs {c}, benefit {b}" for u, (c, b) in UPGRADES.items()] +
                     ["budget of 100", "U4 can only be bought if U3 is also bought", "U2 and U8 cannot both"],
    "reasoning-015": ["4 red, 3 blue and 2 green", "Four marbles are drawn", "all three colors"],
    "reasoning-016": ["Ivy and Kim live next door to each other", "Jon lives immediately to the left of the blue house",
                      "The red house is somewhere to the right of Leo's house", "Leo does not live in the green house",
                      "Kim lives at least two houses away from the green house",
                      "The dog lives at least two houses away from Jon",
                      "The fish lives immediately to the left of Jon's house", "The bird lives next door to Ivy"],
    "reasoning-017": ["15:00 on Friday, October 30, 2026, Sydney", "Los Angeles, London, Tokyo"],
    "reasoning-018": ["6 hours", "9 hours", "12 hours", "for 2 hours", "3/4 full"],
    "reasoning-019": ["length 8", "A, B and C", "no two adjacent letters are equal", "at least twice"],
    "reasoning-020": ["greater than 10,000", "remainder 3 when divided by 7", "remainder 4 when divided by 11",
                      "remainder 5 when divided by 13", "remainder 2 when divided by 3"],
}

# ---------------------------------------------------------------- scorer (mirror of SCHEMA.md)

MATCH_TYPES = {"number", "exact_ci", "set", "sequence", "regex"}


def clean_final(s):
    return s.replace("**", "").replace("`", "").strip()


def ws(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def items_of(s):
    return [ws(x) for x in s.split(",") if x.strip()]


def as_number(s):
    return Fraction(re.sub(r"[,\s$%]", "", s))


def matches(final, sc):
    final = clean_final(final)
    m = sc["match"]
    if m == "number":
        try:
            return as_number(final) == as_number(sc["answer"])
        except (ValueError, ZeroDivisionError):
            return False
    if m == "exact_ci":
        return ws(final) in {ws(sc["answer"]), *(ws(a) for a in sc.get("accept", []))}
    if m == "set":
        return sorted(items_of(final)) == sorted(items_of(sc["answer"]))
    if m == "sequence":
        return items_of(final) == items_of(sc["answer"])
    if m == "regex":
        return re.search(sc["pattern"], final, re.I) is not None
    raise ValueError(m)


FORMAT_LINE = re.compile(r"End your reply with a final line of the form 'ANSWER: [^']+'\.$")
REQUIRED = {"id", "category", "title", "prompt", "scoring", "difficulty", "provenance"}


def main():
    lines = [l for l in JSONL.read_text().splitlines() if l.strip()]
    items = [json.loads(l) for l in lines]
    errors = []

    def check(cond, msg):
        if not cond:
            errors.append(msg)

    ids = [it.get("id") for it in items]
    check(ids == [f"reasoning-{i:03d}" for i in range(1, 21)], f"ids must be reasoning-001..020 in order, got {ids}")
    for it in items:
        iid = it.get("id")
        missing = REQUIRED - it.keys()
        check(not missing, f"{iid}: missing fields {missing}")
        check(set(it) <= REQUIRED | {"system", "tags"}, f"{iid}: unexpected fields {set(it) - REQUIRED - {'system', 'tags'}}")
        check(it.get("category") == "reasoning", f"{iid}: category")
        check(len(it.get("title", "")) <= 60, f"{iid}: title > 60 chars")
        check(it.get("difficulty") in {"easy", "medium", "hard"}, f"{iid}: difficulty")
        check(bool(it.get("provenance", "").strip()), f"{iid}: provenance empty")
        prompt = it.get("prompt", "")
        check(FORMAT_LINE.search(prompt.strip()) is not None, f"{iid}: prompt must end with the ANSWER format line")
        for s in MUST_CONTAIN.get(iid, []):
            check(s in prompt, f"{iid}: prompt is missing {s!r}")
        sc = it.get("scoring", {})
        check(sc.get("type") == "final_answer", f"{iid}: scoring.type")
        check(sc.get("match") in MATCH_TYPES, f"{iid}: scoring.match {sc.get('match')}")
        if sc.get("match") == "regex":
            check(bool(sc.get("pattern")), f"{iid}: regex match needs a pattern")
        expected = COMPUTE[iid]()
        check(sc.get("answer") == expected, f"{iid}: answer {sc.get('answer')!r} != computed {expected!r}")
        check(matches(expected, sc), f"{iid}: computed answer does not pass its own match rule")
        check(matches(f"**{expected}**", sc), f"{iid}: bolded answer does not pass its own match rule")
        for alt in sc.get("accept", []):
            check(matches(alt, sc), f"{iid}: accept {alt!r} does not pass")
        print(f"{iid}  {it.get('difficulty'):6}  {sc.get('match'):8}  {expected}")

    mix = Counter(it.get("difficulty") for it in items)
    print(f"\n{len(items)} items, difficulty {dict(mix)}")
    if errors:
        print("\nFAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
