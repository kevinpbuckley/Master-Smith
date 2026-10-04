"""The MetaHuman templates (mastersmith/metahuman) read without Blender: the A-pose off the body skeleton, the UV
tiles, and the pose check that says what the conform solver will get wrong (2026-10-04)."""
import os

from mastersmith.metahuman import template as mh


def test_templates_are_in_the_repo():
    for f in ("SKM_Body.fbx", "SKM_Face.fbx", "SM_MH_Head.fbx", "SKM_Body.skeleton.json", "SKM_Face.skeleton.json",
              "template.json", "MH_Template.glb", "template_front.png", "template_side.png"):
        assert os.path.exists(os.path.join(mh.TEMPLATES, f)), f


def test_the_apose_is_read_off_the_body_skeleton():
    a = mh.apose(mh.skeleton("SKM_Body"))
    assert a["bone_count"] == 342
    assert 18 <= a["arm_angle_deg"] <= 32            # the MetaHuman A-pose: arms about a quarter turn down from the shoulder
    assert 0.20 <= a["foot_spread_m"] <= 0.32
    assert 0.24 <= a["shoulder_width_m"] <= 0.34
    assert a["hand_height_m"] < a["hip_height_m"] + 0.1


def test_template_measurements_and_uv_tiles():
    t = mh.load()
    assert 1.65 <= t["template_height_m"] <= 1.80
    assert 1.25 <= t["body_neck_seam_z_m"] <= 1.35
    body = t["meshes"]["body"]
    assert body["uv_tiles"]["M_GrayTexture_Body"]["udim"] == 1002       # the body is baked on tile 1002: shift u by -1 in Blender
    assert t["meshes"]["face"]["uv_tiles"]["M_GrayTexture_Head"]["udim"] == 1001
    assert mh.skeleton("SKM_Face")["bone_count"] == 875


def test_check_pose_accepts_the_template_and_names_the_faults():
    t = mh.load()
    good = {"height_m": 1.75, "arm_angle_deg_l": 25, "arm_angle_deg_r": 24, "armpit_gap_m": 0.06, "leg_gap_m": 0.12,
            "head_present": True, "finger_tips": 5}
    assert mh.check_pose(good, t)["ok"]
    # the template itself, measured by mh_conform on 2026-10-04, passes with a note on its hands
    itself = {"height_m": 1.75, "arm_angle_deg_l": 35.3, "arm_angle_deg_r": 35.1, "armpit_gap_m": 0.048, "leg_gap_m": 0.12,
              "head_present": True, "finger_tips": 3, "hair_suspected": False}
    r = mh.check_pose(itself, t)
    assert r["ok"] and r["problems"] == [] and any("3 finger tips" in n for n in r["notes"])
    bad = {"height_m": 0.6, "arm_angle_deg_l": 4, "arm_angle_deg_r": 80, "armpit_gap_m": 0.0, "leg_gap_m": 0.01,
           "head_present": False, "finger_tips": 2, "hair_suspected": True}
    r = mh.check_pose(bad, t)
    text = " ".join(r["problems"])
    assert not r["ok"]
    for word in ("height", "armpit", "T-pose", "legs", "head", "finger", "hair"):
        assert word in text, word


def test_summary_is_one_line():
    s = mh.summary()
    assert "A-pose" in s and "1002" in s and "\n" not in s
