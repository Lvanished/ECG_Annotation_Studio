"""ECG annotation ontology: default tiers/labels, seeding and validation.

The default ontology is only a seed.  Tiers and labels live in the database and
can be extended at runtime (``POST /ontology/labels``, ``POST /tiers``); every
extension bumps the ontology patch version, which is stamped on annotations and
dataset snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import OntologyLabel, OntologyMeta, Tier

BASE_ONTOLOGY_VERSION = "1.0.0"

MORPHOLOGY_VALUES = [
    "positive", "negative", "biphasic", "notched", "fragmented",
    "double_peak", "R_prime", "S_prime", "flat", "uncertain",
]

COMMON_ATTRS: dict[str, dict] = {
    "note": {"type": "string"},
    "uncertain": {"type": "boolean"},
    "original_symbol": {"type": "string"},
}
WAVE_ATTRS = {**COMMON_ATTRS, "morphology": {"type": "enum", "values": MORPHOLOGY_VALUES}}
RHYTHM_ATTRS = {**COMMON_ATTRS, "original_aux": {"type": "string"}}
QUALITY_ATTRS = {**COMMON_ATTRS, "severity": {"type": "enum", "values": ["low", "moderate", "severe"]}}
INTERP_ATTRS = {**COMMON_ATTRS, "confidence": {"type": "enum", "values": ["low", "medium", "high"]}}
BEAT_ATTRS = {**COMMON_ATTRS, "morphology": {"type": "enum", "values": MORPHOLOGY_VALUES}}

# name, kind, scope, color, level, overlap_policy, description
DEFAULT_TIERS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Rhythm", "interval", "global", "#7c3aed", "L1", "forbid_same_lead", "Rhythm episodes (L1)"),
    ("Beat", "mixed", "global", "#0f766e", "L2", "forbid_same_lead", "Beat class points (at fiducial) or beat regions"),
    ("P Wave", "interval", "lead", "#0284c7", "L3", "forbid_same_lead", "P wave extent"),
    ("QRS Complex", "interval", "lead", "#dc2626", "L3", "forbid_same_lead", "QRS complex extent"),
    ("ST Segment", "interval", "lead", "#ca8a04", "L3", "forbid_same_lead", "ST segment (J point to T onset)"),
    ("T Wave", "interval", "lead", "#16a34a", "L3", "forbid_same_lead", "T wave extent"),
    ("Fiducial Points", "point", "lead", "#be185d", "L4", "allow", "Onset/peak/offset fiducial points"),
    ("Morphology", "interval", "lead", "#9333ea", "L5", "allow", "Morphology descriptors over a region"),
    ("Signal Quality", "interval", "lead", "#64748b", "L0", "forbid_same_lead", "Noise / artifact / quality regions"),
    ("PR Segment", "interval", "lead", "#0e7490", "L3", "forbid_same_lead", "PR segment (P offset to QRS onset)"),
    ("U Wave", "interval", "lead", "#65a30d", "L3", "forbid_same_lead", "U wave extent"),
    ("Interpretation", "interval", "global", "#475569", "L7", "allow", "Research interpretation findings (L7)"),
]

# code, name, level, parent, geometry, tiers, attributes_schema
_L = tuple[str, str, str, str | None, str, list[str], dict]
DEFAULT_LABELS: list[_L] = [
    # L0 signal metadata / quality
    ("good_quality", "Good signal quality", "L0", None, "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("noise", "Noise", "L0", None, "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("baseline_wander", "Baseline wander", "L0", "noise", "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("muscle_artifact", "Muscle artifact", "L0", "noise", "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("motion_artifact", "Motion artifact", "L0", "noise", "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("powerline_interference", "Powerline interference", "L0", "noise", "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("missing_data", "Missing data", "L0", None, "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("saturation", "Saturation / clipping", "L0", None, "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("lead_off", "Lead off", "L0", "missing_data", "interval", ["Signal Quality"], QUALITY_ATTRS),
    ("unreadable", "Unreadable", "L0", None, "interval", ["Signal Quality"], QUALITY_ATTRS),
    # L1 rhythm
    ("sinus_rhythm", "Sinus rhythm", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("sinus_arrhythmia", "Sinus arrhythmia", "L1", "sinus_rhythm", "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("tachycardia", "Tachycardia", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("sinus_tachycardia", "Sinus tachycardia", "L1", "tachycardia", "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("supraventricular_tachyarrhythmia", "Supraventricular tachyarrhythmia", "L1", "tachycardia", "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("ventricular_tachycardia", "Ventricular tachycardia", "L1", "tachycardia", "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("bradycardia", "Bradycardia", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("sinus_bradycardia", "Sinus bradycardia", "L1", "bradycardia", "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("atrial_fibrillation", "Atrial fibrillation", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("atrial_flutter", "Atrial flutter", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("ventricular_flutter", "Ventricular flutter", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("atrial_bigeminy", "Atrial bigeminy", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("ventricular_bigeminy", "Ventricular bigeminy", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("ventricular_trigeminy", "Ventricular trigeminy", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("nodal_rhythm", "Nodal (A-V junctional) rhythm", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("idioventricular_rhythm", "Idioventricular rhythm", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("preexcitation", "Pre-excitation (WPW)", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("second_degree_av_block", "2nd degree heart block", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("paced_rhythm", "Paced rhythm", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    ("unknown_rhythm", "Unknown rhythm", "L1", None, "interval", ["Rhythm"], RHYTHM_ATTRS),
    # L2 beat
    ("normal_beat", "Normal beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("LBBB_beat", "Left bundle branch block beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("RBBB_beat", "Right bundle branch block beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("PAC", "Premature atrial contraction", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("aberrant_PAC", "Aberrated atrial premature beat", "L2", "PAC", "any", ["Beat"], BEAT_ATTRS),
    ("nodal_premature_beat", "Nodal (junctional) premature beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("supraventricular_premature_beat", "Supraventricular premature beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("PVC", "Premature ventricular contraction", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("fusion_beat", "Fusion of ventricular and normal beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("paced_beat", "Paced beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("paced_fusion_beat", "Fusion of paced and normal beat", "L2", "paced_beat", "any", ["Beat"], BEAT_ATTRS),
    ("escape_beat", "Escape beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("atrial_escape_beat", "Atrial escape beat", "L2", "escape_beat", "any", ["Beat"], BEAT_ATTRS),
    ("nodal_escape_beat", "Nodal (junctional) escape beat", "L2", "escape_beat", "any", ["Beat"], BEAT_ATTRS),
    ("ventricular_escape_beat", "Ventricular escape beat", "L2", "escape_beat", "any", ["Beat"], BEAT_ATTRS),
    ("unknown_beat", "Unclassifiable beat", "L2", None, "any", ["Beat"], BEAT_ATTRS),
    ("beat_region", "Beat region (segmentation)", "L2", None, "interval", ["Beat"], BEAT_ATTRS),
    # L3 wave intervals
    ("P_wave", "P wave", "L3", None, "interval", ["P Wave"], WAVE_ATTRS),
    ("PR_segment", "PR segment", "L3", None, "interval", ["PR Segment"], WAVE_ATTRS),
    ("QRS_complex", "QRS complex", "L3", None, "interval", ["QRS Complex"], WAVE_ATTRS),
    ("ST_segment", "ST segment", "L3", None, "interval", ["ST Segment"], WAVE_ATTRS),
    ("T_wave", "T wave", "L3", None, "interval", ["T Wave"], WAVE_ATTRS),
    ("U_wave", "U wave", "L3", None, "interval", ["U Wave"], WAVE_ATTRS),
    # L4 fiducial points
    ("P_onset", "P onset", "L4", "P_wave", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("P_peak", "P peak", "L4", "P_wave", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("P_offset", "P offset", "L4", "P_wave", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("QRS_onset", "QRS onset", "L4", "QRS_complex", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("Q_peak", "Q peak", "L4", "QRS_complex", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("R_peak", "R peak", "L4", "QRS_complex", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("S_peak", "S peak", "L4", "QRS_complex", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("QRS_offset", "QRS offset", "L4", "QRS_complex", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("J_point", "J point", "L4", "QRS_complex", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("T_onset", "T onset", "L4", "T_wave", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("T_peak", "T peak", "L4", "T_wave", "point", ["Fiducial Points"], COMMON_ATTRS),
    ("T_offset", "T offset", "L4", "T_wave", "point", ["Fiducial Points"], COMMON_ATTRS),
    # L5 morphology (also usable as the ``morphology`` attribute on waves)
    *[(m if m != "uncertain" else "uncertain_morphology",
       m.replace("_", " ").capitalize() if m != "uncertain" else "Uncertain morphology",
       "L5", None, "interval", ["Morphology"], COMMON_ATTRS) for m in MORPHOLOGY_VALUES],
    # L6 multi-lead relationships (used as relation types, not placeable on tiers)
    ("shared_beat", "Shared beat identity across leads", "L6", None, "relation", [], {}),
    ("cross_lead_alignment", "Cross-lead boundary alignment", "L6", None, "relation", [], {}),
    ("lead_specific_boundary", "Lead-specific boundary of a global wave", "L6", None, "relation", [], {}),
    ("lead_specific_morphology", "Lead-specific morphology", "L6", None, "relation", [], {}),
    ("part_of", "Child annotation is part of parent", "L6", None, "relation", [], {}),
    ("global_measurement", "Global (multi-lead) measurement", "L6", None, "relation", [], {}),
    # L7 research interpretation
    ("conduction_abnormality", "Conduction abnormality", "L7", None, "interval", ["Interpretation"], INTERP_ATTRS),
    ("first_degree_av_block", "1st degree AV block", "L7", "conduction_abnormality", "interval", ["Interpretation"], INTERP_ATTRS),
    ("RBBB", "Right bundle branch block", "L7", "conduction_abnormality", "interval", ["Interpretation"], INTERP_ATTRS),
    ("LBBB", "Left bundle branch block", "L7", "conduction_abnormality", "interval", ["Interpretation"], INTERP_ATTRS),
    ("LAFB", "Left anterior fascicular block", "L7", "conduction_abnormality", "interval", ["Interpretation"], INTERP_ATTRS),
    ("repolarization_abnormality", "Repolarization abnormality", "L7", None, "interval", ["Interpretation"], INTERP_ATTRS),
    ("early_repolarization", "Early repolarization", "L7", "repolarization_abnormality", "interval", ["Interpretation"], INTERP_ATTRS),
    ("st_t_finding", "ST-T finding", "L7", None, "interval", ["Interpretation"], INTERP_ATTRS),
    ("st_elevation", "ST elevation", "L7", "st_t_finding", "interval", ["Interpretation"], INTERP_ATTRS),
    ("st_depression", "ST depression", "L7", "st_t_finding", "interval", ["Interpretation"], INTERP_ATTRS),
    ("t_wave_inversion", "T wave inversion", "L7", "st_t_finding", "interval", ["Interpretation"], INTERP_ATTRS),
    ("uncertain_finding", "Uncertain finding", "L7", None, "interval", ["Interpretation"], INTERP_ATTRS),
]

RELATION_LEVEL = "L6"


def seed_ontology(s: Session) -> None:
    """Idempotently insert default tiers/labels and the version row."""
    if s.get(OntologyMeta, "version") is None:
        s.add(OntologyMeta(key="version", value=BASE_ONTOLOGY_VERSION))
    existing_tiers = {t.name for t in s.scalars(select(Tier))}
    for order, (name, kind, scope, color, level, policy, desc) in enumerate(DEFAULT_TIERS):
        if name not in existing_tiers:
            s.add(Tier(name=name, kind=kind, scope=scope, color=color, level=level,
                       overlap_policy=policy, order=order, description=desc))
    existing_labels = {c for c in s.scalars(select(OntologyLabel.code))}
    s.flush()
    # parents must exist before children (FK) -> insert in declaration order
    for code, name, level, parent, geom, tiers, attrs in DEFAULT_LABELS:
        if code not in existing_labels:
            s.add(OntologyLabel(code=code, name=name, level=level, parent_code=parent, geometry=geom,
                                tiers=tiers, attributes_schema=attrs))
            s.flush()


def get_version(s: Session) -> str:
    row = s.get(OntologyMeta, "version")
    return row.value if row else BASE_ONTOLOGY_VERSION


def bump_version(s: Session) -> str:
    row = s.get(OntologyMeta, "version")
    if row is None:
        row = OntologyMeta(key="version", value=BASE_ONTOLOGY_VERSION)
        s.add(row)
    major, minor, patch = (int(x) for x in row.value.split("."))
    row.value = f"{major}.{minor}.{patch + 1}"
    return row.value


class OntologyError(ValueError):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


@dataclass
class OntologyCache:
    version: str
    tiers: dict[str, Tier] = field(default_factory=dict)
    labels: dict[str, OntologyLabel] = field(default_factory=dict)

    @classmethod
    def load(cls, s: Session) -> "OntologyCache":
        return cls(
            version=get_version(s),
            tiers={t.name: t for t in s.scalars(select(Tier))},
            labels={lb.code: lb for lb in s.scalars(select(OntologyLabel))},
        )

    def validate(self, tier: str, label: str, kind: str, attributes: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        t = self.tiers.get(tier)
        if t is None:
            return [f"Unknown tier '{tier}'"]
        if t.kind != "mixed" and t.kind != kind:
            errors.append(f"Tier '{tier}' accepts only {t.kind} annotations, got {kind}")
        lb = self.labels.get(label)
        schema: dict[str, dict] = dict(COMMON_ATTRS)
        if lb is None or not lb.active:
            if not t.allow_free_labels:
                errors.append(f"Label '{label}' is not in the ontology (tier '{tier}' does not allow free labels)")
        else:
            if lb.geometry == "relation":
                errors.append(f"Label '{label}' is a relationship type and cannot be placed on a tier")
            elif lb.geometry not in ("any", kind):
                errors.append(f"Label '{label}' requires {lb.geometry} geometry, got {kind}")
            if lb.tiers and tier not in lb.tiers:
                errors.append(f"Label '{label}' is not allowed on tier '{tier}' (allowed: {', '.join(lb.tiers)})")
            schema.update(lb.attributes_schema or {})
        errors.extend(validate_attributes(attributes, schema))
        return errors

    def check(self, tier: str, label: str, kind: str, attributes: dict[str, Any]) -> None:
        errors = self.validate(tier, label, kind, attributes)
        if errors:
            raise OntologyError(errors)


def validate_attributes(attributes: dict[str, Any], schema: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    if not isinstance(attributes, dict):
        return ["attributes must be an object"]
    for key, value in attributes.items():
        if key.startswith("x_"):
            continue  # custom extension attributes
        spec = schema.get(key)
        if spec is None:
            errors.append(f"Unknown attribute '{key}' (custom attributes must be prefixed 'x_')")
            continue
        typ = spec.get("type")
        if value is None:
            continue
        if typ == "enum" and value not in spec.get("values", []):
            errors.append(f"Attribute '{key}' must be one of {spec.get('values')}, got {value!r}")
        elif typ == "boolean" and not isinstance(value, bool):
            errors.append(f"Attribute '{key}' must be boolean")
        elif typ == "string" and not isinstance(value, str):
            errors.append(f"Attribute '{key}' must be a string")
        elif typ == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"Attribute '{key}' must be a number")
            elif ("min" in spec and value < spec["min"]) or ("max" in spec and value > spec["max"]):
                errors.append(f"Attribute '{key}' out of range")
    return errors
