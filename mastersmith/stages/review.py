"""Stage 4: a vision model compares the finished renders with the reference picture and says what is
wrong in plain words. It advises; the customer decides whether to rebuild."""
from ..llm import extract_json

PROMPT = """You are reviewing a finished game asset against its reference picture.
Brief: {brief}
Image 1 is the reference picture. Images 2 and 3 are renders of the finished 3D model (three-quarter and side).
Judge silhouette, proportions, missing or fused parts, colours and materials (does metal read as metal, is anything
glossy like ceramic, is the texture blurry?). Be specific and short.
Answer with JSON only:
{{"score": 1-10, "silhouette_ok": true/false, "materials_ok": true/false,
 "issues": ["..."], "verdict": "ship" | "ship with notes" | "rebuild",
 "rebuild_advice": "if rebuild: what to change about the reference picture or brief, one sentence"}}"""


def review(job, reference_path, renders):
    text = job.llm.vision(PROMPT.format(brief=job.spec.description), [reference_path] + renders[:2], max_tokens=1500)
    j = extract_json(text) or {"score": 0, "issues": ["reviewer returned no JSON"], "verdict": "ship with notes"}
    job.log("  review: %s/10, %s" % (j.get("score"), j.get("verdict")))
    return j
