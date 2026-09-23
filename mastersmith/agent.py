"""The director: a cheap chat model that turns conversation into a Spec, quotes the price, and runs the
pipeline when the customer says go. It never writes Blender code and never sees images - the pipeline
does the work, the model does the talking. That is what keeps OpenRouter spend to a few cents a job."""
import json
import os

from . import config, pricing, skills
from .llm import LLM
from .pipeline import build
from .spec import CATEGORIES, ENGINES, STYLES, Spec
from .wallet import InsufficientCredits

SYSTEM = """You are Master Smith, a 3D asset director. A customer describes a game asset; you turn it into a build brief,
quote the credits, and run the build when they confirm. You are concise and concrete.

How a job goes:
1. From the customer's words call set_brief with your best complete brief. Fill sensible defaults yourself
   (category, real size in metres, triangle budget, engine) - ask at most ONE short question, and only when the
   answer would change the model itself (e.g. "which tank?", "realistic or stylized?"). Write `description`
   as a photo caption: what it is, its materials and colours, distinctive parts, era. Write colours as a camera
   sees them, never as trade terms ('blued steel' is dark blue-black oxidised steel, not blue). Fixed-wing aircraft are
   category "aircraft" and rotorcraft "helicopter" (not "vehicle"). Name real machines by name
   and put that name in search_query so a real photograph is found; leave search_query empty for invented things.
   When the customer attached pictures, put them in reference_images (they are edited into the build picture).
   When the customer wants an existing model changed, keep the whole description and put only what changes in
   edit_instructions; the previous picture is edited so the rest of the design stays as it was. When only colours,
   finishes or materials change ("the stock should be gunmetal, not cream"), set retexture=true and name the parts in
   retexture_parts: the mesh is repainted, nothing moves, and it costs about half a rebuild.
2. set_brief returns a credit estimate and the balance. Tell the customer the plan in two or three lines and the
   credits it will hold, then wait for them to say go (or change something).
3. When they confirm call build. If it returns a queued job_id, tell the customer the job is building and that the
   page shows progress; when they ask how it is going call job_status. When build returns a finished result, report
   it: files, triangle counts, glass, rig, the reviewer's score and issues, credits charged. If the reviewer said
   rebuild, say what you would change and ask before spending again.
4. For changes after a build, call set_brief again with the changed fields and then build when confirmed. Changes that
   keep the shape (size, triangle budget, glass, rig, engine) re-finish the same mesh; colour, finish or material
   changes with retexture=true repaint it; only a change of shape or parts buys a new mesh. Say which it will be.
5. When the customer attaches a 3D model file (.glb, .gltf, .fbx, .obj or a delivered .blend), call import_model with
   its path, a PascalCase name, the category and whatever else they told you: the model is oriented, scaled, given
   glass, LODs, collision, maps and previews without buying a new mesh, and later changes work on it like on a build.
   Attached pictures go in reference_images of set_brief.

Skills you can read for guidance on a category: {categories}. Use read_skill when unsure how a category is handled.
Categories: {cats}. Styles: {styles}. Engines: {engines}.
Never invent file paths or results; only report what tools return. {pricing}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "set_brief",
        "description": "Set or update the build brief. Returns the brief as understood, the credit estimate and the balance.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Asset name in PascalCase, e.g. SniperRifle"},
            "description": {"type": "string", "description": "Photo-caption description: object, materials, colours, parts, era"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "style": {"type": "string", "enum": list(STYLES)},
            "engine": {"type": "string", "enum": list(ENGINES)},
            "tri_budget": {"type": "integer", "description": "LOD0 triangle budget; 0 for the category default"},
            "size_m": {"type": "number", "description": "Real longest dimension in metres (height for characters)"},
            "reference_image": {"type": "string", "description": "Path or URL of the customer's main picture, if any"},
            "reference_images": {"type": "array", "items": {"type": "string"}, "description": "Every picture the customer supplied (up to 4)"},
            "search_query": {"type": "string", "description": "For a REAL, named thing (an M1 Abrams, a Willys MB, a Glock 17, a Ford F-150): its exact name, so a photograph is looked up on the web and the mesh is built from it. Empty for fictional or generic objects."},
            "research": {"type": "boolean", "description": "Force web research on or off (default: on when search_query is set and no pictures were supplied)"},
            "multiview": {"type": "boolean", "description": "Seed from several views (default true for weapons/vehicles)"},
            "premium": {"type": "boolean", "description": "Dearer picture model for hard briefs"},
            "glass": {"type": "boolean", "description": "Give windows/lenses a glass material slot (default for vehicles, weapons, buildings)"},
            "rig": {"type": "boolean", "description": "Rig it: characters get a UE5-named humanoid skeleton with walk/run clips; vehicles get wheel bones; weapons get Muzzle/Grip/Sight socket bones"},
            "notes": {"type": "string"},
            "edit_instructions": {"type": "string", "description": "When changing an EXISTING model: one or two sentences naming only "
                                  "what changes in its appearance. The previous picture is edited, everything unmentioned stays."},
            "retexture": {"type": "boolean", "description": "True when ONLY colours, finishes or materials of the existing model change: "
                          "the mesh is repainted and its shape kept. False when parts, shape or proportions change."},
            "retexture_parts": {"type": "array", "items": {"type": "object", "properties": {
                                    "phrase": {"type": "string", "description": "the part as a descriptive phrase a segmenter can find on a render ('the upper metal slide of the pistol'), never a bare word"},
                                    "color": {"type": "string", "description": "#rrggbb flat colour wanted, or empty for a pattern/texture"},
                                    "current_hex": {"type": "string", "description": "#rrggbb of how the part looks now"},
                                    "metal": {"type": "boolean"}, "finish": {"type": "string", "enum": ["matte", "satin", "glossy"]}},
                                    "required": ["phrase"]},
                                "description": "With retexture: the parts that change; empty for the whole object"},
            "protect_parts": {"type": "array", "items": {"type": "object", "properties": {"phrase": {"type": "string"}, "hex": {"type": "string"}},
                              "required": ["phrase"]}, "description": "With retexture: neighbouring parts that must not change, each a "
                              "descriptive phrase with its colour ('the translucent amber magazine') and its #rrggbb"}},
            "required": ["name", "description", "category"]}}},
    {"type": "function", "function": {
        "name": "import_model",
        "description": "Bring in a 3D model file the customer attached and finish it for their engine (no new mesh is bought). "
                       "Becomes the current model: later set_brief + build calls re-finish or repaint it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "The attached file's path exactly as given"},
            "name": {"type": "string", "description": "Asset name in PascalCase"},
            "description": {"type": "string", "description": "What the model is, as a photo caption (materials, colours, parts)"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "engine": {"type": "string", "enum": list(ENGINES)},
            "size_m": {"type": "number", "description": "Real longest dimension in metres to scale it to; omit to keep the file's own size"},
            "tri_budget": {"type": "integer", "description": "LOD0 triangle budget; 0 for the category default"},
            "glass": {"type": "boolean"}, "rig": {"type": "boolean"}, "notes": {"type": "string"}},
            "required": ["path", "name", "category"]}}},
    {"type": "function", "function": {
        "name": "build", "description": "Run the build for the current brief. Only after the customer confirmed.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "job_status", "description": "Status, log tail and results of a queued or finished build.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}}},
    {"type": "function", "function": {
        "name": "read_skill", "description": "Read the guidance for an asset category.",
        "parameters": {"type": "object", "properties": {"category": {"type": "string"}}, "required": ["category"]}}},
    {"type": "function", "function": {
        "name": "balance", "description": "The customer's credit balance.", "parameters": {"type": "object", "properties": {}}}},
]

MAX_TOOL_ROUNDS = 4


class Director:
    def __init__(self, user, wallet, log=print, model=None, pricing_note="Credits: 1 credit = 1 cent of provider cost on the customer's own fal and OpenRouter keys; the estimate is a worst case."):
        self.user, self.wallet, self.log = user, wallet, log
        self.last_tools = []
        self.model = model or config.DIRECTOR_MODEL
        self.llm = LLM(log=log)
        self.spec = None
        self.last_result = None
        self.last_job_id = None
        self.submit = None          # service hook: spec dict -> {"job_id", ...}; when set, build is queued not run
        self.job_status = None      # service hook: job_id -> status dict
        self.import_model = None    # service hook: (path, spec dict) -> {"job_id", ...}
        self.messages = [{"role": "system", "content": SYSTEM.format(
            categories=", ".join(skills.all_categories()), cats=", ".join(CATEGORIES),
            styles=", ".join(STYLES), engines=", ".join(ENGINES), pricing=pricing_note)}]

    # ------------------------------------------------------------ tools
    def _set_brief(self, a):
        base = self.spec.to_dict() if self.spec else {}
        base.update({k: v for k, v in a.items() if v not in (None, "")})
        # the words in the brief decide the category (a helicopter filed as a prop loses its canopy and cockpit)
        from .brief import fix_category
        base["category"] = fix_category(base.get("category"), base.get("description"), base.get("name"), base.get("search_query"))
        self.spec = Spec.from_dict(base)
        est = pricing.estimate(self.spec)
        bal = self.wallet.balance(self.user)
        return {"brief": self.spec.to_dict(), "estimate_credits": est["credits"], "estimate_usd": est["usd"],
                "steps": [s for s, _ in est["steps"]], "balance": bal,
                "affordable": bal >= est["credits"]}

    def _build(self, _a):
        if not self.spec:
            return {"error": "no brief yet; call set_brief first"}
        if self.submit:
            out = self.submit(self.spec.to_dict())
            if out.get("job_id"):
                self.last_job_id = out["job_id"]
            return out
        try:
            self.last_result = build(self.spec, self.user, self.wallet, log=self.log)
        except InsufficientCredits as exc:
            return {"error": "insufficient credits", "needed": exc.needed, "balance": exc.balance}
        return self._summary(self.last_result)

    @staticmethod
    def _summary(r):
        summary = {"status": r["status"], "job_dir": r["dir"], "bill": {k: r["bill"][k] for k in
                   ("usd_cost", "credits_charged", "balance")}}
        if r.get("error"):
            summary["error"] = r["error"]
        if r.get("delivery"):
            d = r["delivery"]
            summary["delivery"] = {"dir": r["delivery_dir"], "files": d["files"], "lods": d["lods"],
                                   "dimensions_m": d.get("dimensions_m"), "maps": [m["role"] for m in d["maps"]],
                                   "roughness_mean": d.get("roughness_mean"), "notes": d["notes"][-4:]}
        if r.get("review"):
            summary["review"] = r["review"]
        if r.get("gate"):
            summary["gate"] = r["gate"]
        if r.get("package"):
            summary["package"] = r["package"]
        return summary

    def _import_model(self, a):
        path = (a.get("path") or "").strip()
        if not path:
            return {"error": "no path given"}
        d = {k: v for k, v in a.items() if k != "path" and v not in (None, "")}
        d.setdefault("description", "imported model")
        d["size_m"] = float(d.get("size_m") or 0) or -1            # negative keeps the file's own size
        self.spec = Spec.from_dict(d)
        if not self.import_model:
            from .pipeline import rework
            self.last_result = rework(path, self.spec, self.user, self.wallet, log=self.log)
            return self._summary(self.last_result)
        out = self.import_model(path, self.spec.to_dict())
        if out.get("job_id"):
            self.last_job_id = out["job_id"]
        return out

    def _job_status(self, a):
        jid = a.get("job_id") or self.last_job_id
        if not jid:
            return {"error": "no job yet"}
        if self.job_status:
            st = self.job_status(jid)
            st = dict(st)
            st.pop("files", None)
            st["log"] = (st.get("log") or [])[-12:]
            return st
        return {"job_id": jid, "status": "done" if self.last_result else "unknown"}

    def _read_skill(self, a):
        s = skills.load(a.get("category", "prop"))
        return {"category": s["category"], "guidance": s["body"][:2500]}

    def _balance(self, _a):
        return {"balance": self.wallet.balance(self.user)}

    # ------------------------------------------------------------ chat
    def turn(self, text):
        """One customer message in, the assistant's reply out (tools run in between)."""
        self.messages.append({"role": "user", "content": text})
        self.last_tools = []
        for _ in range(MAX_TOOL_ROUNDS):
            msg = self.llm.chat(self.messages, model=self.model, tools=TOOLS)
            self.messages.append({"role": "assistant", "content": msg.get("content") or "",
                                  **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {})})
            if not msg.get("tool_calls"):
                return msg.get("content") or ""
            for call in msg["tool_calls"]:
                name = call["function"]["name"]
                try:
                    a = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    a = {}
                fn = {"set_brief": self._set_brief, "build": self._build, "read_skill": self._read_skill,
                      "balance": self._balance, "job_status": self._job_status, "import_model": self._import_model}.get(name)
                out = fn(a) if fn else {"error": "unknown tool %s" % name}
                self.last_tools.append({"name": name, "args": a, "result": json.dumps(out, default=str)[:400]})
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "name": name,
                                      "content": json.dumps(out, default=str)})
        return "(I ran out of tool rounds this turn; tell me what to do next.)"

    def chat_cost_usd(self):
        return self.llm.spent()
