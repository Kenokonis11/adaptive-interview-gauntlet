"""Hiring Manager agent wrappers."""

from __future__ import annotations

from src.agents._runtime import (
    current_proxy,
    dump_for_prompt,
    mastery_for_skill,
    normalize_question,
    run_text,
    state_value,
)


INTERVIEW_MODE_PROMPT = """You are a Hiring Manager conducting a technical interview for the role of {target_role} at {target_company}.

Current question skill: {current_skill}
Skill proxy context (your source of truth for what to ask):
{proxy_context}

Candidate mastery for this skill: {current_mastery}
Attempt number: {attempt_number} of 3
Previously asked questions (do NOT repeat these): {previous_questions}
Current MCP failure summary (if attempt > 1): {failure_summary}

== RULES ==

If attempt_number == 1 (first attempt — no prior failure):
  - Present the question directly from the proxy context.
  - COPY the exact function signature and column/table schema from the proxy context into your question.
  - State the requirements as a numbered list so the candidate knows exactly what is tested.
  - Do NOT be vague. Do NOT say "write a function that does X" without specifying inputs, outputs, and column names.
  - Keep it under 150 words. End with: "Write your solution in the editor below."

If attempt_number == 2 (one failure already):
  - You have the MCP failure summary above. Use it.
  - Give ONE specific, concrete hint. Not a question. Not a nudge. An actionable fix.
  - Example of a BAD hint: "Think about what column to join on."
  - Example of a GOOD hint: "Your merge is failing because the join key should be 'user_id', not 'patient_id'. Change `on='patient_id'` to `on='user_id'` and keep `how='left'`."
  - Reference the actual error from the failure summary if one exists.
  - Keep it under 80 words.

Do NOT evaluate correctness yourself. Do NOT reveal hidden test case code.
Return plain text only — this is shown directly to the candidate.
"""


CONCEPTUAL_MODE_PROMPT = """You are a Learning Coach asking a conceptual question for the role of {target_role} at {target_company}.

Current topic: {current_skill}
Topic context (use this to formulate the question):
{proxy_context}

Candidate mastery for this topic: {current_mastery}
Attempt number: {attempt_number}
Previously asked questions (do NOT repeat): {previous_questions}

== RULES ==

If attempt_number == 1:
  - Ask the question clearly, framed in the job context from proxy_context.
  - Include the numbered list of specific concepts the candidate must address (from proxy_context).
  - Keep it under 120 words. End with: "Type your answer in the editor below."

If attempt_number == 2 (prior answer was insufficient):
  - Give a targeted hint about which specific concept was likely missing.
  - Be concrete: name the specific thing they should address, not just "think more about X."
  - Keep it under 60 words.

Return plain text only.
"""


TUTOR_MODE_PROMPT = """You are switching from Interviewer to Tutor. The candidate has failed twice and needs teaching, not another hint.

Failed question: {question_text}
Skill: {current_skill}
Expected concepts: {expected_concepts}
Failure detail: {failure_detail}

Your job — in this exact order:
1. In 2-3 sentences, diagnose what the candidate got wrong based on the failure detail.
2. Teach the concept from scratch using a concrete worked example with real code or SQL.
   Show the correct pattern. Be specific about syntax — this is a coding platform, not a lecture.
3. Give a SIMPLER version of the original question that tests one sub-concept at a time.
   The simpler question must also include an exact function signature or SQL structure.

Format your response as:
[EXPLANATION]
<diagnosis + worked example here>

[NEW QUESTION]
<exact simpler question here, including signature/schema>
"""

CONCEPTUAL_TUTOR_PROMPT = """You are switching to Tutor mode for a conceptual topic the candidate struggled with.

Failed question: {question_text}
Topic: {current_skill}
Expected concepts: {expected_concepts}

Your job:
1. In 2-3 sentences, diagnose what key concept the candidate likely missed or misunderstood.
2. Explain the concept clearly with a concrete real-world example.
3. Ask a simpler, more focused follow-up question that tests one sub-concept at a time.

Format your response as:
[EXPLANATION]
<diagnosis + explanation + example>

[NEW QUESTION]
<focused follow-up question>
"""


def run_manager(state_dict: dict) -> str:
    """Run the Hiring Manager in interview mode, hint mode, or tutor mode."""

    attempt_count = int(state_value(state_dict, "attempt_count", default=0) or 0)
    current_skill = state_value(state_dict, "current_skill", default="general")
    question = normalize_question(state_value(state_dict, "current_question", default={}))
    proxy = current_proxy(state_dict)
    proxy_type = proxy.get("proxy_type", "python_general")
    is_conceptual = proxy_type == "conceptual"

    mcp_result = state_value(state_dict, "mcp_result", default={}) or {}
    exit_code = getattr(mcp_result, "exit_code", None)
    if isinstance(mcp_result, dict):
        exit_code = mcp_result.get("exit_code", exit_code)

    # Tutor mode: two failures on executable skill
    if not is_conceptual and attempt_count >= 2 and exit_code not in (None, 0):
        prompt = TUTOR_MODE_PROMPT.format(
            question_text=question["text"],
            current_skill=current_skill,
            expected_concepts=dump_for_prompt(question["expected_concepts"]),
            failure_detail=dump_for_prompt(
                getattr(mcp_result, "traceback", None) if not isinstance(mcp_result, dict) else mcp_result.get("traceback")
            ),
        )
    # Tutor mode: two failures on conceptual skill
    elif is_conceptual and attempt_count >= 2:
        prompt = CONCEPTUAL_TUTOR_PROMPT.format(
            question_text=question["text"],
            current_skill=current_skill,
            expected_concepts=dump_for_prompt(question["expected_concepts"]),
        )
    # Conceptual question / hint
    elif is_conceptual:
        prompt = CONCEPTUAL_MODE_PROMPT.format(
            target_role=state_value(state_dict, "target_role", "role", default=""),
            target_company=state_value(state_dict, "target_company", default=""),
            current_skill=current_skill,
            proxy_context=dump_for_prompt(proxy.get("proxy_context", "")),
            current_mastery=mastery_for_skill(state_dict, current_skill),
            attempt_number=attempt_count + 1,
            previous_questions=dump_for_prompt(state_value(state_dict, "previous_questions", default=[])),
        )
    # Executable question / hint
    else:
        failure_summary = getattr(mcp_result, "stderr", None) if not isinstance(mcp_result, dict) else mcp_result.get("stderr")
        prompt = INTERVIEW_MODE_PROMPT.format(
            target_role=state_value(state_dict, "target_role", "role", default=""),
            target_company=state_value(state_dict, "target_company", default=""),
            current_skill=current_skill,
            proxy_context=dump_for_prompt(proxy.get("proxy_context", "")),
            current_mastery=mastery_for_skill(state_dict, current_skill),
            attempt_number=attempt_count + 1,
            previous_questions=dump_for_prompt(state_value(state_dict, "previous_questions", default=[])),
            failure_summary=failure_summary or "N/A",
        )

    return run_text(prompt, "Respond to the candidate now.")
