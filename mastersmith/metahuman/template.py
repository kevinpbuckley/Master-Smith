"""The MetaHuman templates as numbers (pure numpy, no Blender): the A-pose the conform solver expects, the body's
proportions, the UV tiles, and a check of a candidate mesh's pose measurements against them.

2026-10-04, from the video the owner sent ("Turn ANY Character into an Animated Metahuman", UE 5.8) and the editor's
own API (MetaHumanCharacterEditorSubsystem.ConformToTargetMeshes): the solver wants ONE combined static mesh in an
A-pose with the arms clear of the body, the legs apart, the fingers separated, no hair, no eyelashes, no accessories,
at the character's real height, Z up, transforms applied. What the mesh gets wrong, the solve gets wrong (four fingers
read as two on the acrobat; hair conformed into a lumpy skull)."""
import json
import math
import os

import numpy as np

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# the conform input, as a checklist the agent reads back to the owner (the video's prerequisites + the API's)
CONFORM_INPUT = [
    "one combined mesh: body and head joined, high-poly is fine (the solver takes any vertex count; the mesh is also the "
    "baking source, so keep its detail)",
    "A-pose: arms down and away from the body at about 25 degrees, a clear gap at the armpits, legs apart, fingers "
    "separated and the hands open",
    "bald, no eyelashes, no accessories: hair, ears that are not human, horns, armour and clothes are separate meshes "
    "attached to the built MetaHuman afterwards",
    "the character's real height in metres, feet on the floor, Z up, facing -Y in Blender (Unreal's +X after import), "
    "rotation and scale applied (1, 1, 1 / 0, 0, 0)",
    "exported as a GLB static mesh; Unreal imports it in centimetres",
]

# the UV layout a built MetaHuman uses; a bake in Blender needs the body tile moved onto 0-1 (u - 1)
UDIM = {"head": 1001, "body": 1002}


def load():
    """template.json as measured by blender/mh_template.py, plus the body skeleton's A-pose numbers."""
    t = json.load(open(os.path.join(TEMPLATES, "template.json"), encoding="utf-8"))
    t["apose"] = apose(skeleton("SKM_Body"))
    return t


def skeleton(name="SKM_Body"):
    """{"bones": [{"name", "parent", "pos_cm", "quat_xyzw"}], ...}: the reference pose in Unreal's frame (cm, +X
    forward, +Y right, +Z up), component space."""
    return json.load(open(os.path.join(TEMPLATES, name + ".skeleton.json"), encoding="utf-8"))


def bone_positions(skel):
    return {b["name"]: np.array(b["pos_cm"], float) for b in skel["bones"]}


def apose(skel):
    """What the MetaHuman A-pose is, read off the body skeleton: arm angle from vertical, foot spread, shoulder width,
    arm length, the heights that place the limbs (metres and degrees)."""
    B = bone_positions(skel)
    ua, la, hand = B["upperarm_l"], B["lowerarm_l"], B["hand_l"]
    v = hand - ua
    return {
        "arm_angle_deg": round(math.degrees(math.atan2(abs(v[1]), -v[2])), 1),
        "elbow_angle_deg": round(math.degrees(math.acos(np.clip(np.dot(la - ua, hand - la) /
                                                                 (np.linalg.norm(la - ua) * np.linalg.norm(hand - la)), -1, 1))), 1),
        "arm_length_m": round((np.linalg.norm(la - ua) + np.linalg.norm(hand - la)) / 100, 3),
        "shoulder_width_m": round(np.linalg.norm(B["upperarm_l"] - B["upperarm_r"]) / 100, 3),
        "foot_spread_m": round(np.linalg.norm(B["foot_l"] - B["foot_r"]) / 100, 3),
        "thigh_spread_m": round(np.linalg.norm(B["thigh_l"] - B["thigh_r"]) / 100, 3),
        "shoulder_height_m": round(ua[2] / 100, 3),
        "hand_height_m": round(hand[2] / 100, 3),
        "hip_height_m": round(B["pelvis"][2] / 100, 3),
        "head_bone_height_m": round(B["head"][2] / 100, 3),
        "bone_count": len(skel["bones"]),
    }


# the body skeleton's deform bones an accessory may be weighted to (the rest are helpers, twists and correctives)
BODY_BONES = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head",
              "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l", "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r",
              "thigh_l", "calf_l", "foot_l", "ball_l", "thigh_r", "calf_r", "foot_r", "ball_r"]


def check_pose(m, template=None):
    """A candidate mesh's measurements (from blender/mh_conform.py) against the A-pose: m has height_m, arm_angle_deg
    (both arms), armpit_gap_m, leg_gap_m, hands_below_hips (bool), head_present (bool), finger_tips (count seen, or
    None). -> {"ok", "problems": [...], "notes": [...]} - a problem is what the solver will get wrong."""
    t = template or load()
    a = t["apose"]
    # the silhouette reads an arm's run centres from the armpit down (hand included), so it measures the template at
    # 35 degrees where the skeleton's shoulder-to-wrist line is 24: compare like with like
    ref = (t.get("silhouette_apose") or {}).get("arm_angle_deg", a["arm_angle_deg"])
    problems, notes = [], []
    h = m.get("height_m") or 0
    if not 1.0 <= h <= 2.6:
        problems.append("height %.2f m: a MetaHuman body is 1.35-2.20 m (the sliders' range); set the brief's size" % h)
    for side in ("l", "r"):
        ang = m.get("arm_angle_deg_%s" % side)
        if ang is None:
            continue
        if ang < 12:
            problems.append("%s arm hangs at %.0f degrees: the armpit is closed, the solver fuses arm and torso (the template reads %.0f)"
                            % (side, ang, ref))
        elif ang > 65:
            problems.append("%s arm raised to %.0f degrees: that is a T-pose, not the MetaHuman A-pose (the template reads %.0f)" % (side, ang, ref))
        elif abs(ang - ref) > 15:
            notes.append("%s arm at %.0f degrees (template %.0f): the solver accepts it, the pose transfer is rougher" % (side, ang, ref))
    gap = m.get("armpit_gap_m")
    if gap is not None and gap < 0.03:
        problems.append("armpit gap %.0f mm: the arm touches the body (keep 3 cm or more)" % (gap * 1000))
    lg = m.get("leg_gap_m")
    if lg is not None and lg < 0.04:
        problems.append("legs %.0f mm apart at the knees: too close, the solver merges them (template feet %.2f m apart)" % (lg * 1000, a["foot_spread_m"]))
    if m.get("head_present") is False:
        problems.append("no head above the shoulders: the conform needs the combined mesh (or a head mesh in the head slot)")
    tips = m.get("finger_tips")
    if tips is not None and tips <= 2:
        problems.append("%d finger tips seen on a hand: the fingers are fused (the acrobat's four fingers read as two); open the hand or add key points" % tips)
    elif tips == 3:
        notes.append("3 finger tips seen on a hand (the template's own spread hand reads 3 in this silhouette): look at the hands in the seed's six views")
    if m.get("hair_suspected"):
        problems.append("the head reads taller than a skull (hair or a helmet on the seed): remove it, the solver conforms the skull around it")
    return {"ok": not problems, "problems": problems, "notes": notes}


def summary():
    """One paragraph for a status print."""
    t = load()
    a = t["apose"]
    return ("MetaHuman template: %.2f m tall, body to the neck seam at %.2f m (UDIM 1002), face UDIM 1001; A-pose arms %.0f "
            "degrees from vertical, elbows %.0f, feet %.2f m apart, shoulders %.2f m wide; body skeleton %d bones, face %d"
            % (t["template_height_m"], t["body_neck_seam_z_m"], a["arm_angle_deg"], a["elbow_angle_deg"], a["foot_spread_m"],
               a["shoulder_width_m"], a["bone_count"], skeleton("SKM_Face")["bone_count"]))
