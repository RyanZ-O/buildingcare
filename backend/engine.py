"""Transparent qualitative diagnosis and intervention scenarios."""

from datetime import datetime, timezone
from uuid import uuid4

from .knowledge import ASSUMPTION, KnowledgeProvider, dedupe, propagate


def now():
    return datetime.now(timezone.utc).isoformat()


RULE_SOURCE = "Project teaching rule; qualitative hypothesis, not an engineering measurement"

CAUSES = {
    "hvac": [
        {"id": "hvac_filter_restriction", "label": "Restricted filter or air path", "asset": "hvac",
         "keywords": ["filter", "airflow", "ventilation", "风量", "堵"],
         "reason": "A restricted air path is a candidate explanation for reported low airflow. "
                   "Room complaints alone do not establish the equipment fault.",
         "checks": ["Record whether airflow is low in all served rooms or one room.",
                    "Ask the maintenance team to inspect the filter and air path according to the equipment manual."]},
        {"id": "hvac_fan_fault", "label": "Fan or control fault", "asset": "hvac",
         "keywords": ["fan", "control", "motor", "风机", "没有风"],
         "reason": "A fan or control fault can reduce ventilation to connected spaces. "
                   "Confirm equipment status and control commands before choosing a cause.",
         "checks": ["Record the fan operating status and any controller alarm.",
                    "Compare the reported symptom with other rooms on the same verified service branch."]},
        {"id": "shared_power_fault", "label": "Electrical supply interruption to HVAC", "asset": "electrical",
         "keywords": ["breaker", "power", "circuit", "supply", "electrical", "电", "跳闸"],
         "reason": "Loss of electrical supply is another possible explanation for an inactive HVAC unit. "
                   "The demonstration assumes a supply connection that has not been verified from the model.",
         "checks": ["Check for other reported electrical interruptions in the same area.",
                    "Have authorised maintenance staff verify the actual supply connection and equipment power status."]},
    ],
    "electrical": [
        {"id": "electrical_overload", "label": "Protective trip associated with overload", "asset": "electrical",
         "keywords": ["overload", "breaker", "trip", "过载", "跳闸"],
         "reason": "A protective trip associated with excessive load is a candidate for reported supply loss. "
                   "A complaint does not establish why the protective device operated.",
         "checks": ["Record affected rooms, equipment and the time of interruption.",
                    "Ask authorised maintenance staff to review circuit identification and the protective-device indication."]},
        {"id": "electrical_short_circuit", "label": "Protective trip associated with a circuit fault", "asset": "electrical",
         "keywords": ["short circuit", "short-circuit", "insulation", "fault", "短路"],
         "reason": "A circuit fault is an alternative explanation for protective-device operation. "
                   "Distinguishing it from overload requires qualified inspection.",
         "checks": ["Record reported alarm or trip information without treating it as a confirmed fault type.",
                    "Have authorised maintenance staff investigate according to the electrical maintenance procedure."]},
        {"id": "electrical_supply_fault", "label": "Upstream supply or connection issue", "asset": "electrical",
         "keywords": ["power", "supply", "connection", "outage", "供电", "停电"],
         "reason": "An upstream supply or connection issue can affect several loads at once. "
                   "The actual circuit scope must be checked against as-built information.",
         "checks": ["Compare simultaneous reports across rooms and equipment.",
                    "Verify the extent of supply interruption and actual upstream topology."]},
    ],
}


def analyse(issue: dict, observations: str, knowledge: KnowledgeProvider):
    is_scoped = issue["roomId"] in knowledge.demo_rooms[:2]
    report_source = {"id": f"issue-{issue['id']}",
                     "text": f"Occupant report: {issue['title']} — {issue['description']}",
                     "source": f"Issue {issue['id']} (reported observation; not independently verified)"}
    observed = ({"id": f"observation-{uuid4().hex[:12]}", "text": observations,
                 "source": "Maintenance check note; human-entered and not machine verified"}
                if observations else None)
    text = f"{issue['title']} {issue['description']} {observations}".casefold()
    ordered = sorted(CAUSES[issue["system"]],
                     key=lambda c: -sum(word.casefold() in text for word in c["keywords"]))
    candidates = []
    for cause in ordered:
        asset_id = ((knowledge.hvac_id if cause["asset"] == "hvac" else knowledge.electrical_id)
                    if is_scoped else None)
        rule = {"id": f"rule-{cause['id']}", "text": cause["reason"], "source": RULE_SOURCE}
        evidence = [report_source, rule, *knowledge.evidence(cause["keywords"])]
        if observed:
            evidence.append(observed)
        if is_scoped:
            evidence.append(ASSUMPTION)
        candidates.append({"id": cause["id"], "label": cause["label"], "assetId": asset_id,
                           "reason": cause["reason"], "evidence": dedupe(evidence), "checks": cause["checks"]})
    limitations = [
        "These are candidate hypotheses, not confirmed root causes or calibrated probabilities.",
        "Ranking reflects matching words in reports/check notes; it does not establish causality.",
        "Photos are retained as evidence; this version does not infer defects from image pixels.",
        "This prototype uses labelled demonstration rules. Neo4j knowledge retrieval and inference are not yet connected.",
    ]
    if is_scoped:
        limitations.append(ASSUMPTION["text"])
    else:
        limitations.append("No verified or demonstration service topology is configured for this room. "
                           "Device candidates remain unassigned and impact estimates are limited to the reported room.")
    if not knowledge.graph:
        limitations.append("No demonstration graph context is available; candidates use labelled teaching rules only.")
    return {"id": uuid4().hex, "issueId": issue["id"], "createdAt": now(), "candidates": candidates,
            "observations": observations, "limitations": limitations,
            "sources": dedupe([e for c in candidates for e in c["evidence"]])}


def simulate(issue: dict, analysis: dict, cause_id: str, action: str, knowledge: KnowledgeProvider):
    candidate = next((c for c in analysis["candidates"] if c["id"] == cause_id), None)
    if candidate is None:
        raise ValueError("Selected cause does not belong to this analysis.")
    root = candidate["assetId"]
    state = "ventilation_loss" if cause_id.startswith("hvac_") else "power_loss"
    assumptions = ["Qualitative teaching scenario; no temperature, airflow, duration or probability is calculated.",
                   "The selected cause is a hypothesis supplied to the scenario, not a confirmed diagnosis."]
    if root:
        assumptions.append(ASSUMPTION["text"])
        if action == "system_shutdown" and knowledge.electrical_id:
            root = knowledge.electrical_id
            state = "power_loss"
            assumptions.append("System shutdown isolates the assumed electrical branch, including its HVAC load.")
        during = propagate(knowledge.topology, root, state, knowledge.entities)
    else:
        during = {"affectedRoomIds": [issue["roomId"]], "affectedAssetIds": [],
                  "paths": [], "explanation": ""}
        assumptions.append("No service topology is available for this room; wider impacts are unknown, not assumed absent.")
    if action == "observe":
        during["explanation"] = "If the selected fault persists, the configured conditional paths identify these potentially affected rooms and assets."
        after = {**during, "explanation": "No intervention is applied; the same hypothetical service loss remains. This is not a time forecast."}
    else:
        during["explanation"] = ("During the proposed intervention, these services are assumed unavailable "
                                 "within the selected equipment or branch isolation scope.")
        after = {"affectedRoomIds": [], "affectedAssetIds": [], "paths": [],
                 "explanation": "Projected service restoration assumes the selected cause is correct, the repair succeeds, "
                                "and maintenance staff verify recommissioning. This result does not mark the real issue resolved."}
        assumptions.append("Repair and recommissioning are assumed successful; actual restoration requires verification.")
        if action == "local_repair":
            assumptions.append("Local repair assumes equipment-level isolation; upstream service interruption is not required. Verify before work.")
    return {"id": uuid4().hex, "issueId": issue["id"], "analysisId": analysis["id"],
            "causeId": cause_id, "action": action, "createdAt": now(), "during": during, "after": after,
            "assumptions": assumptions,
            "sources": dedupe(candidate["evidence"] + ([ASSUMPTION] if candidate["assetId"] else []))}
