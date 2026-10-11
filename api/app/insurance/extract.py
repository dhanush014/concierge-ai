"""Read an insurance card image with the vision model.

Five fields, copied exactly as printed. A field the model can't read is null, never a
guess. Code backs the prompt up: "unknown"-style values, partial reads with gap markers
("RBH5...706360") and too-short member IDs ("LSA1") become null, so the form highlights
them instead of showing something that looks filled in.
"""

import base64
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent import llm
from app.models import CardFields

PROMPT = """\
You read health insurance cards. Copy these fields exactly as printed on the card:

  payer         the insurance company name (usually the largest name on the card)
  plan_name     the plan's name, e.g. "Silver HMO"
  member_name   the member's name as printed
  member_id     the member ID (may be labeled "Member ID", "ID", "ID#")
  group_number  the group number (may be labeled "Group", "Group No.", "Grp")

Rules:
- If a field is missing, cut off or you cannot read it with certainty, use null. Never \
guess, never fill in a likely value, never fix a value you think is a typo.
- All or nothing: if even one character of a field is hidden, cut off, smudged or \
unclear, the whole field is null. Never return part of a value, and never use "...", \
"?" or "_" for characters you can't read.
- Ignore watermarks such as "SAMPLE", phone numbers, copays and pharmacy codes (RxBIN, \
RxPCN): they are not these fields.

Return JSON only: {"payer": ..., "plan_name": ..., "member_name": ..., "member_id": ..., \
"group_number": ...}
"""

UNREADABLE = {"", "null", "none", "unknown", "n/a", "na", "unreadable", "illegible", "not visible", "-"}
# A value with a gap marker is a partial read: "RBH5...706360", "LSA1??", "9_771".
GAP = re.compile(r"\.\.\.|…|\?|_")
MIN_MEMBER_ID = 6  # shorter is a cut-off read ("LSA1"), not an ID


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if text.lower() in UNREADABLE or GAP.search(text):
        return None
    return text


def guard(fields: dict[str, str | None]) -> dict[str, str | None]:
    """Plain-code checks on top of the prompt, so a partial read can't look filled in."""
    member_id = fields.get("member_id")
    if member_id and len(member_id.replace(" ", "")) < MIN_MEMBER_ID:
        fields["member_id"] = None
    return fields


def parse(content: str) -> CardFields:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    data = json.loads(match.group(0) if match else content)
    return CardFields(**guard({field: clean(data.get(field)) for field in CardFields.model_fields}))


def read_card(image: bytes, content_type: str) -> CardFields:
    """Raises on model failure or unparseable output; the route turns that into a 502."""
    data_url = f"data:{content_type};base64,{base64.b64encode(image).decode()}"
    model = llm.chat_model("vision").bind(response_format={"type": "json_object"})
    reply = model.invoke([
        SystemMessage(PROMPT),
        HumanMessage(content=[
            {"type": "text", "text": "Read this insurance card."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]),
    ])
    return parse(str(reply.content))
