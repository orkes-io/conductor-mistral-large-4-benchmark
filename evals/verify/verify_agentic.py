"""Verify evals/agentic.jsonl against SCHEMA.md and the shared environment in workers/agentic_env.py.

For every scenario:
- schema checks (item fields, function-tool JSON schemas, environment covers every tool, scoring rules)
- replay `reference_trace` through run_tool: every step must hit a real case (not the default, not an error)
- an ideal final answer scores as a pass
- bad traces fail: each forbidden call, each missing required call, a wrong argument, too many turns, empty answer
- an oracle re-derives the correct actions from the environment data and the stated rules and checks
  they equal the scenario's required/forbidden calls
Run: python3.13 evals/verify/verify_agentic.py"""
import copy
import datetime as dt
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from agentic_env import match_args, normalize, run_tool, score_trace  # noqa: E402

ITEMS = [json.loads(line) for line in (ROOT / "evals" / "agentic.jsonl").read_text().splitlines() if line.strip()]
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}

IDEAL_FINAL = {
    "agentic-001": "Rolled back checkout deploy d-482 (v2.31.0 to v2.30.4, job rb-9917). Search's latest deploy d-455 is 3 days old, so I did not roll back or restart search.",
    "agentic-002": "Booked 'Q4 roadmap sync' in slot-3 (evt-5521), 14:30-15:30 UTC: 15:30 in Berlin, 09:30 in New York, 11:30 in Sao Paulo. The other slots fall outside someone's working hours.",
    "agentic-003": "Booked Southwest WN-3301 ($189, lands 16:50) and Union Station Inn (H-207, $184/night, 2 nights). I did not book a return flight.",
    "agentic-004": "Deleted vol-01a7c3e9 (snapshot snap-0e71a001) and vol-05eb0c74 (snapshot snap-0e71a005). Left vol-02b8d4f1 (attached), vol-03c9e5a2 and vol-06fc1d85 (not older than 30 days) and vol-04dafb63 (keep=true).",
    "agentic-005": "Approved AR-301 (mchen). Denied AR-302 (tbello, security training expired) and AR-303 (kpatel, admin role is never granted here).",
    "agentic-006": "I did not promote b-2291. All required checks passed, but billing-api has an open SEV2 incident (INC-7731).",
    "agentic-007": "Created PO-77181 for SKU-1001 (200 units from SUP-B) and PO-77182 for SKU-1004 (120 units from SUP-D). Skipped SKU-1002 and SKU-1005 (enough stock) and SKU-1003 (discontinued).",
    "agentic-008": "Re-ran extract_returns (S3 read timeout). Opened DATA-4417 for analytics-eng about the transform_sales schema error and did not re-run it. Left returns_rollup, load_warehouse and publish_dashboard alone.",
    "agentic-009": "Paged j.ortiz (secondary, since primary alex.kim is out of office) and posted in the incidents channel. Did not page alex.kim or m.wu.",
    "agentic-010": "Scheduled firmware 4.2.0 on TH-101 and TH-106. Skipped TH-102 (hw rev B), TH-103 (battery 35%), TH-104 (maintenance lock), TH-105 (firmware 3.9.8), and GW-01 and SN-201 (not thermostats).",
    "agentic-011": "Created PR-20931 for Q-1 from Northwind Systems (V-100), $68,400. Rejected Q-2 (SOC 2 expired), Q-3 (vendor not approved) and Q-4 (over budget).",
    "agentic-012": "T-5501 went to tier2-escalations and I paged TAM r.singh; T-5502 went to tier2; T-5503 went to tier1. No other pages.",
}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


# ------------------------------------------------------------------ unit tests for agentic_env
def unit_tests():
    check(normalize("  Checkout ") == "checkout", "normalize trims and casefolds")
    check(normalize(3) == 3.0 and normalize([1, "A"]) == [1.0, "a"], "normalize numbers and lists")
    check(match_args({"quantity": 200}, {"quantity": "200"}), "numeric string matches number")
    check(match_args({"sku": "sku-1001"}, {"sku": " SKU-1001 ", "extra": 1}), "subset match with case/trim")
    check(not match_args({"sku": "SKU-1001"}, {"sku": "SKU-1002"}), "different value does not match")
    check(not match_args({"sku": "SKU-1001"}, {}), "missing key does not match")
    check(match_args({"emails": ["b", "a"]}, {"emails": ["A", "B"]}), "lists are unordered multisets")
    check(not match_args({"emails": ["a", "b"]}, {"emails": ["a"]}), "list length must match")
    check(match_args({"a": {"b": 1}}, {"a": {"b": 1.0, "c": 2}}), "nested dicts are subset matches")
    check(match_args({}, {"anything": True}), "empty match matches anything")
    check(match_args({"x": 1}, '{"x": 1}'), "JSON-string args are parsed")
    env = {"t": {"cases": [{"match": {"k": "v"}, "result": {"ok": 1}}], "default": {"ok": 0}},
           "w": {"side_effect": True, "cases": [], "default": {"done": True}}}
    check(run_tool(env, "t", {"k": "V"}) == {"result": {"ok": 1}, "side_effect": False, "known_tool": True}, "run_tool case")
    check(run_tool(env, "t", {"k": "z"})["result"] == {"ok": 0}, "run_tool default")
    check(run_tool(env, "w", {})["side_effect"] is True, "run_tool side_effect flag")
    check(run_tool(env, "nope", {}) == {"result": {"error": "unknown tool nope"}, "side_effect": False, "known_tool": False},
          "run_tool unknown tool")
    check("error" in run_tool(env, "t", "not json")["result"], "run_tool rejects non-object args")
    sc = {"required_calls": [{"tool": "t", "args": {"k": "v"}}], "forbidden_calls": [{"tool": "w", "args": {}}],
          "final_must_include": ["done", "re:id-\\d+"], "final_must_not_include": ["oops"], "max_turns": 3}
    ok = score_trace(sc, [{"tool": "t", "args": {"k": "v"}}], "Done with ID-42", 2)
    check(ok["pass"], f"score_trace pass case: {ok}")
    check(not score_trace(sc, [{"tool": "t", "args": {"k": "v"}}, {"tool": "w", "args": {"x": 1}}], "done id-1", 2)["pass"],
          "score_trace forbidden")
    check(not score_trace(sc, [], "done id-1", 2)["pass"], "score_trace missing required")
    check(not score_trace(sc, [{"tool": "t", "args": {"k": "v"}}], "done id-1 oops", 2)["pass"], "score_trace exclude")
    check(not score_trace(sc, [{"tool": "t", "args": {"k": "v"}}], "done id-1", 4)["pass"], "score_trace max turns")
    check(not score_trace(sc, [{"tool": "t", "args": {"k": "v"}}], "nothing", 1)["pass"], "score_trace include")


# ------------------------------------------------------------------ schema checks
def validate_value(prop, value, where):
    t = prop.get("type")
    py = TYPES.get(t)
    if py is None:
        return check(False, f"{where}: unsupported type {t}")
    if t == "integer" and isinstance(value, bool):
        return check(False, f"{where}: bool given for integer")
    if not check(isinstance(value, py), f"{where}: expected {t}, got {type(value).__name__}"):
        return False
    if "enum" in prop:
        check(value in prop["enum"], f"{where}: {value!r} not in enum {prop['enum']}")
    if t == "array" and "items" in prop:
        for k, v in enumerate(value):
            validate_value(prop["items"], v, f"{where}[{k}]")
    return True


def schema_checks(it):
    sid = it.get("id", "?")
    for f in ("id", "category", "title", "system", "prompt", "tools", "environment", "scoring", "reference_trace",
              "difficulty", "provenance"):
        check(f in it, f"{sid}: missing field {f}")
    check(re.fullmatch(r"agentic-\d{3}", sid) is not None, f"{sid}: bad id")
    check(it.get("category") == "agentic", f"{sid}: category must be agentic")
    check(len(it.get("title", "")) <= 60, f"{sid}: title longer than 60 chars")
    check(it.get("difficulty") in ("easy", "medium", "hard"), f"{sid}: bad difficulty")
    tools = it["tools"]
    check(3 <= len(tools) <= 6, f"{sid}: needs 3-6 tools, has {len(tools)}")
    names = []
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        names.append(name)
        check(t.get("type") == "function", f"{sid}/{name}: tool type must be function")
        check(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is not None, f"{sid}: bad tool name {name!r}")
        check(bool(fn.get("description")), f"{sid}/{name}: missing description")
        params = fn.get("parameters", {})
        check(params.get("type") == "object", f"{sid}/{name}: parameters.type must be object")
        props = params.get("properties", {})
        check(isinstance(props, dict) and props, f"{sid}/{name}: parameters.properties must be a non-empty object")
        check(set(params.get("required", [])) <= set(props), f"{sid}/{name}: required lists unknown properties")
        for pname, p in props.items():
            check(p.get("type") in TYPES, f"{sid}/{name}.{pname}: bad type {p.get('type')}")
            check(bool(p.get("description")), f"{sid}/{name}.{pname}: missing description")
            if p.get("type") == "array":
                check("items" in p, f"{sid}/{name}.{pname}: array without items")
            if "enum" in p:
                check(isinstance(p["enum"], list) and p["enum"], f"{sid}/{name}.{pname}: empty enum")
    check(len(names) == len(set(names)), f"{sid}: duplicate tool names")
    env = it["environment"]
    check(set(env) == set(names), f"{sid}: environment tools {sorted(env)} != tools {sorted(names)}")
    for tname, spec in env.items():
        check(isinstance(spec.get("cases"), list), f"{sid}/{tname}: cases must be a list")
        check("default" in spec, f"{sid}/{tname}: missing default")
        check(isinstance(spec.get("side_effect", False), bool), f"{sid}/{tname}: side_effect must be bool")
        for c in spec.get("cases", []):
            check(isinstance(c.get("match"), dict) and "result" in c, f"{sid}/{tname}: malformed case")
    sc = it["scoring"]
    check(sc.get("type") == "agentic_trace", f"{sid}: scoring.type must be agentic_trace")
    check(8 <= int(sc.get("max_turns", 0)) <= 10, f"{sid}: max_turns must be 8-10")
    check(sc.get("required_calls"), f"{sid}: needs required_calls")
    check(sc.get("forbidden_calls"), f"{sid}: needs forbidden_calls (restraint)")
    check(sc.get("final_must_include"), f"{sid}: needs final_must_include")
    for rule in sc.get("required_calls", []) + sc.get("forbidden_calls", []):
        check(rule.get("tool") in names, f"{sid}: scoring rule uses unknown tool {rule.get('tool')}")
    for rule in sc.get("forbidden_calls", []):
        check(env.get(rule.get("tool"), {}).get("side_effect") is True,
              f"{sid}: forbidden tool {rule.get('tool')} should be an action (side_effect true)")
    for chk in sc.get("final_must_include", []) + sc.get("final_must_not_include", []):
        if chk.startswith("re:"):
            try:
                re.compile(chk[3:])
            except re.error as e:
                check(False, f"{sid}: bad regex {chk!r}: {e}")
    ref = it["reference_trace"]
    check(2 <= len(ref) <= 6, f"{sid}: reference_trace must have 2-6 calls, has {len(ref)}")
    by_name = {t["function"]["name"]: t["function"]["parameters"] for t in tools}
    for k, c in enumerate(ref):
        params = by_name.get(c["tool"])
        if not check(params is not None, f"{sid}: reference call {k} uses unknown tool {c['tool']}"):
            continue
        check(c["tool"] in env, f"{sid}: reference call {k} tool {c['tool']} missing from environment")
        for req in params.get("required", []):
            check(req in c["args"], f"{sid}: reference call {k} ({c['tool']}) missing required arg {req}")
        for an, av in c["args"].items():
            p = params["properties"].get(an)
            if check(p is not None, f"{sid}: reference call {k} ({c['tool']}) has unknown arg {an}"):
                validate_value(p, av, f"{sid}: reference call {k} ({c['tool']}).{an}")


# ------------------------------------------------------------------ replay + good/bad traces
def replay(it):
    sid, env = it["id"], it["environment"]
    for k, c in enumerate(it["reference_trace"]):
        out = run_tool(env, c["tool"], c["args"])
        check(out["known_tool"], f"{sid}: reference call {k} hit unknown tool")
        res = out["result"]
        check(res != env[c["tool"]].get("default"), f"{sid}: reference call {k} ({c['tool']}) fell through to default")
        check(not (isinstance(res, dict) and "error" in res), f"{sid}: reference call {k} returned an error: {res}")


def traces(it):
    sid, sc = it["id"], it["scoring"]
    ref = copy.deepcopy(it["reference_trace"])
    final = IDEAL_FINAL[sid]
    good = score_trace(sc, ref, final, len(ref) + 1)
    check(good["pass"], f"{sid}: ideal trace should pass: {good}")
    bad_count = 0

    def expect_fail(calls, text, turns, label):
        nonlocal bad_count
        r = score_trace(sc, calls, text, turns)
        check(not r["pass"], f"{sid}: bad trace should fail ({label})")
        bad_count += 1

    for rule in sc["forbidden_calls"]:
        base = next((dict(c["args"]) for c in ref if c["tool"] == rule["tool"]), {})
        base.update(rule.get("args", {}))
        expect_fail(ref + [{"tool": rule["tool"], "args": base}], final, len(ref) + 2, f"forbidden {rule}")
    for rule in sc["required_calls"]:
        kept = [c for c in ref if not (c["tool"] == rule["tool"] and match_args(rule.get("args", {}), c["args"]))]
        check(len(kept) < len(ref), f"{sid}: reference trace lacks required call {rule}")
        expect_fail(kept, final, len(kept) + 1, f"missing {rule}")
    rule = next(r for r in sc["required_calls"] if r.get("args"))
    wrong = []
    for c in ref:
        if c["tool"] == rule["tool"] and match_args(rule["args"], c["args"]):
            c = copy.deepcopy(c)
            key = next(iter(rule["args"]))
            v = c["args"][key]
            c["args"][key] = v + 1 if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{v}-x"
        wrong.append(c)
    expect_fail(wrong, final, len(ref) + 1, "wrong argument")
    expect_fail(ref, final, int(sc["max_turns"]) + 1, "too many turns")
    expect_fail(ref, "", len(ref) + 1, "empty final answer")
    check(bad_count >= 2, f"{sid}: fewer than two bad traces")


# ------------------------------------------------------------------ oracles: re-derive the right actions
def case_result(it, tool, **args):
    out = run_tool(it["environment"], tool, args)
    return out["result"]


def required_set(it, tool, key):
    return {normalize(r["args"][key]) for r in it["scoring"]["required_calls"] if r["tool"] == tool and key in r["args"]}


def forbidden_set(it, tool, key):
    return {normalize(r["args"][key]) for r in it["scoring"]["forbidden_calls"] if r["tool"] == tool and key in r["args"]}


def utc(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def oracle(it):
    sid = it["id"]
    if sid == "agentic-001":
        now = utc("2026-10-26T14:00:00Z")
        fresh = {(svc, d["deploy_id"]) for svc in ("checkout", "search")
                 for d in case_result(it, "list_recent_deploys", service=svc)["deploys"]
                 if dt.timedelta(0) <= now - utc(d["deployed_at"]) <= dt.timedelta(hours=1)}
        req = {(r["args"]["service"], r["args"]["deploy_id"]) for r in it["scoring"]["required_calls"] if r["tool"] == "rollback_deploy"}
        check(fresh == req == {("checkout", "d-482")}, f"{sid}: oracle rollback {fresh} vs required {req}")
        check("search" in forbidden_set(it, "rollback_deploy", "service"), f"{sid}: search rollback should be forbidden")
    elif sid == "agentic-002":
        tz = {p["email"]: p["timezone"] for p in (case_result(it, "get_user_profile", email=e)
                                                  for e in it["reference_trace"][3]["args"]["emails"])}
        valid, invalid = set(), set()
        for sl in case_result(it, "find_common_free_slots", emails=list(tz), date="2026-11-03", duration_minutes=60)["slots"]:
            s, e = utc(sl["start_utc"]), utc(sl["end_utc"])
            ok = True
            for z in tz.values():
                ls, le = s.astimezone(ZoneInfo(z)), e.astimezone(ZoneInfo(z))
                ok &= ls.weekday() < 5 and ls.date() == le.date() and ls.time() >= dt.time(9) and le.time() <= dt.time(17)
            (valid if ok else invalid).add(sl["slot_id"])
        check(valid == required_set(it, "book_meeting", "slot_id") == {"slot-3"}, f"{sid}: oracle valid slots {valid}")
        check(invalid == forbidden_set(it, "book_meeting", "slot_id"), f"{sid}: oracle invalid slots {invalid}")
    elif sid == "agentic-003":
        pol = case_result(it, "get_travel_policy", city="Denver")
        fl = case_result(it, "search_flights", origin="ORD", destination="DEN", date="2026-11-11")["flights"]
        ok_f = [f for f in fl if f["cabin"] == pol["cabin"] and f["arrives_local"] <= "2026-11-11T18:00"]
        best_f = min(ok_f, key=lambda f: f["price_usd"])["flight_id"]
        ho = case_result(it, "search_hotels", city="Denver", check_in="2026-11-11", check_out="2026-11-13")["hotels"]
        ok_h = [h for h in ho if h["nightly_rate_usd"] <= pol["lodging_per_diem_usd"]
                and h["distance_to_venue_miles"] <= pol["max_hotel_distance_miles"]]
        best_h = min(ok_h, key=lambda h: h["nightly_rate_usd"])["hotel_id"]
        check({normalize(best_f)} == required_set(it, "book_flight", "flight_id"), f"{sid}: oracle flight {best_f}")
        check({normalize(best_h)} == required_set(it, "book_hotel", "hotel_id"), f"{sid}: oracle hotel {best_h}")
        others_f = {normalize(f["flight_id"]) for f in fl if f["flight_id"] != best_f}
        others_h = {normalize(h["hotel_id"]) for h in ho if h["hotel_id"] != best_h}
        check(others_f <= forbidden_set(it, "book_flight", "flight_id"), f"{sid}: every other outbound flight forbidden")
        check(others_h == forbidden_set(it, "book_hotel", "hotel_id"), f"{sid}: every other hotel forbidden")
    elif sid == "agentic-004":
        today = utc("2026-10-26T00:00:00Z")
        vols = case_result(it, "list_volumes", region="us-east-1")["volumes"]
        dele = {v["volume_id"] for v in vols if v["state"] == "available" and v["tags"].get("keep") != "true"
                and (today - utc(v["created_at"])) > dt.timedelta(days=30)}
        dele_n = {normalize(x) for x in dele}
        check(dele_n == required_set(it, "delete_volume", "volume_id") == required_set(it, "create_snapshot", "volume_id"),
              f"{sid}: oracle deletable {dele}")
        check({normalize(v["volume_id"]) for v in vols} - dele_n == forbidden_set(it, "delete_volume", "volume_id"),
              f"{sid}: every other volume must be forbidden")
    elif sid == "agentic-005":
        today = dt.date(2026, 10, 26)
        approve, deny = set(), set()
        for r in case_result(it, "list_pending_requests", resource="prod-db-orders")["requests"]:
            done = dt.date.fromisoformat(case_result(it, "get_training_record", user=r["user"])["completed_at"])
            ok = (r["change_ticket"]["status"] == "approved" and (today - done).days <= 365
                  and r["manager_approved"] and r["role"] != "admin")
            (approve if ok else deny).add(normalize(r["request_id"]))
        check(approve == required_set(it, "approve_request", "request_id"), f"{sid}: oracle approve {approve}")
        check(deny == required_set(it, "deny_request", "request_id") == forbidden_set(it, "approve_request", "request_id"),
              f"{sid}: oracle deny {deny}")
    elif sid == "agentic-006":
        build = case_result(it, "get_latest_build", service="billing-api", environment="staging")["build_id"]
        checks_ok = case_result(it, "get_check_results", build_id=build)["all_required_passed"]
        blocking = [i for i in case_result(it, "list_open_incidents", service="billing-api")["incidents"]
                    if i["severity"] in ("SEV1", "SEV2")]
        check(checks_ok and blocking, f"{sid}: scenario should be blocked by an incident, not by checks")
        check(any(r["tool"] == "promote_build" and not r.get("args") for r in it["scoring"]["forbidden_calls"]),
              f"{sid}: any promote must be forbidden")
    elif sid == "agentic-007":
        expected = set()
        for x in case_result(it, "get_inventory", warehouse_id="WH-AUS")["items"]:
            if x["discontinued"] or x["on_hand"] + x["on_order"] >= x["reorder_point"]:
                continue
            qs = [q for q in case_result(it, "get_supplier_quotes", sku=x["sku"])["quotes"] if q["approved"]]
            best = min(qs, key=lambda q: q["lead_time_days"])
            expected.add((x["sku"], best["supplier_id"], x["reorder_qty"]))
        req = {(r["args"]["sku"], r["args"]["supplier_id"], r["args"]["quantity"]) for r in it["scoring"]["required_calls"]}
        check(expected == req, f"{sid}: oracle POs {expected} vs required {req}")
    elif sid == "agentic-008":
        dag = case_result(it, "get_dag_run", dag_id="nightly_sales", run_id="2026-10-25")
        rerun, tickets = set(), set()
        for t in dag["tasks"]:
            if t["state"] != "failed":
                continue
            log = case_result(it, "get_task_logs", dag_id="nightly_sales", run_id="2026-10-25", task_id=t["task_id"])["log"]
            if re.search(r"timeout|throttl|connection reset", log, re.I):
                rerun.add(normalize(t["task_id"]))
            elif re.search(r"schema|validation", log, re.I):
                tickets.add(normalize(t["owner_team"]))
        check(rerun == required_set(it, "rerun_task", "task_id"), f"{sid}: oracle rerun {rerun}")
        check(tickets == required_set(it, "create_ticket", "team"), f"{sid}: oracle tickets {tickets}")
        not_rerun = {normalize(t["task_id"]) for t in dag["tasks"] if t["state"] != "success"} - rerun
        check(not_rerun == forbidden_set(it, "rerun_task", "task_id"), f"{sid}: every other unfinished task forbidden")
    elif sid == "agentic-009":
        team = case_result(it, "get_service_owner", service="identity-service")["owner_team"]
        oc = case_result(it, "get_oncall", team=team)
        who = oc["secondary"]["user"] if oc["primary"]["status"] == "out_of_office" else oc["primary"]["user"]
        check({normalize(who)} == required_set(it, "page_user", "user"), f"{sid}: oracle page {who}")
        check(normalize(oc["primary"]["user"]) in forbidden_set(it, "page_user", "user"), f"{sid}: OOO primary forbidden")
    elif sid == "agentic-010":
        info = case_result(it, "get_firmware_info", version="4.2.0")
        ver = lambda v: tuple(int(p) for p in v.split("."))  # noqa: E731
        devs = case_result(it, "list_devices", site_id="SITE-12")["devices"]
        ok = {normalize(d["device_id"]) for d in devs if d["type"] == info["device_type"]
              and d["hw_rev"] in info["compatible_hw_revs"] and d["battery_pct"] >= info["min_battery_pct"]
              and ver(d["firmware"]) >= ver(info["min_current_firmware"]) and not d["maintenance_lock"]}
        check(ok == required_set(it, "schedule_firmware_install", "device_id"), f"{sid}: oracle eligible {ok}")
        check({normalize(d["device_id"]) for d in devs} - ok == forbidden_set(it, "schedule_firmware_install", "device_id"),
              f"{sid}: every ineligible device forbidden")
    elif sid == "agentic-011":
        today = "2026-10-26"
        qs = case_result(it, "get_quotes", item="laptop", quantity=40)["quotes"]
        elig = [q for q in qs if q["total_usd"] <= 72000
                and case_result(it, "check_vendor_compliance", vendor_id=q["vendor_id"])["on_approved_list"]
                and case_result(it, "check_vendor_compliance", vendor_id=q["vendor_id"])["soc2_report_expires"] >= today]
        best = min(elig, key=lambda q: q["total_usd"])["quote_id"]
        check({normalize(best)} == required_set(it, "create_purchase_request", "quote_id"), f"{sid}: oracle quote {best}")
        check({normalize(q["quote_id"]) for q in qs} - {normalize(best)} == forbidden_set(it, "create_purchase_request", "quote_id"),
              f"{sid}: every other quote forbidden")
    elif sid == "agentic-012":
        assigns, pages = set(), set()
        for t in case_result(it, "get_tickets", ticket_ids=["T-5501", "T-5502", "T-5503"])["tickets"]:
            if t["priority"] == "P1" and t["customer_tier"] == "enterprise":
                assigns.add((t["ticket_id"], "tier2-escalations"))
                pages.add((case_result(it, "get_account_team", customer_id=t["customer_id"])["tam"], t["ticket_id"]))
            elif t["priority"] == "P1":
                assigns.add((t["ticket_id"], "tier2"))
            else:
                assigns.add((t["ticket_id"], "tier1"))
        req_a = {(r["args"]["ticket_id"], r["args"]["queue"]) for r in it["scoring"]["required_calls"] if r["tool"] == "assign_ticket"}
        req_p = {(r["args"]["tam_user"], r["args"]["ticket_id"]) for r in it["scoring"]["required_calls"] if r["tool"] == "page_tam"}
        check(assigns == req_a and pages == req_p, f"{sid}: oracle routing {assigns} {pages}")
    else:
        check(False, f"{sid}: no oracle")


def main():
    unit_tests()
    ids = [it.get("id") for it in ITEMS]
    check(ids == [f"agentic-{k:03d}" for k in range(1, 13)], f"ids must be agentic-001..012, got {ids}")
    check(set(IDEAL_FINAL) == set(ids), "IDEAL_FINAL must cover every scenario")
    for it in ITEMS:
        n_before = len(failures)
        schema_checks(it)
        replay(it)
        traces(it)
        oracle(it)
        status = "ok" if len(failures) == n_before else f"{len(failures) - n_before} problem(s)"
        print(f"{it['id']}  {status:12}  calls={len(it['reference_trace'])}  {it['title']}")
    if failures:
        print(f"\nFAILED: {len(failures)} problem(s)")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print(f"\nPASSED: {len(ITEMS)} scenarios verified")


if __name__ == "__main__":
    main()
