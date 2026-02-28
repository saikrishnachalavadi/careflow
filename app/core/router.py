# """
# CareFlow Input Router — LangGraph StateGraph
#
# This is the central nervous system of CareFlow.
# It takes user input and routes it through:
#   1. Guardrails check (medical scope + abuse strikes)
#   2. Emergency keyword detection
#   3. User intent override (direct handoff requests)
#   4. AI-powered classification (Gemini) → route to correct flow
#
# Routes to:
#   - emergency_flow
#   - medical_flow
#   - mental_health_flow
#   - direct_handoff (doctor/pharmacy/lab)
#   - blocked (abuse/out-of-scope)
# """
#
# import os
# from typing import Literal, Optional
# from typing_extensions import TypedDict
#
# from langgraph.graph import StateGraph, END
# from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain_core.messages import SystemMessage, HumanMessage
#
# from app.config import settings
# from app.core.severity import is_emergency, EMERGENCY_KEYWORDS
# from app.core.guardrails import check_medical_scope, check_abuse_strikes
#
#
# # ─── State Schema ───────────────────────────────────────────────
# class CareFlowState(TypedDict):
#     """State that flows through the entire routing graph."""
#     # Input
#     user_id: str
#     message: str
#     session_id: Optional[str]
#
#     # User context (loaded from DB later)
#     abuse_strikes: int
#
#     # Routing decisions
#     route: str  # emergency | medical | mental_health | doctor_handoff | pharmacy_handoff | lab_handoff | blocked
#     block_reason: Optional[str]
#
#     # AI classification result
#     classification: Optional[str]
#     confidence: Optional[str]
#
#     # Output
#     response_message: Optional[str]
#
#
# # ─── Intent Override Keywords ────────────────────────────────────
# DIRECT_INTENT_MAP = {
#     "doctor_handoff": [
#         "i want a doctor", "find me a doctor", "book a doctor",
#         "need a doctor", "talk to a doctor", "see a doctor",
#         "consult a doctor", "doctor please"
#     ],
#     "pharmacy_handoff": [
#         "i need medicine", "find a pharmacy", "buy medicine",
#         "need medication", "pharmacy near me", "otc medicine"
#     ],
#     "lab_handoff": [
#         "book a lab test", "i need a blood test", "lab test",
#         "need lab work", "diagnostic test", "find a lab"
#     ],
#     "emergency": [
#         "call ambulance", "need ambulance", "call 112",
#         "emergency", "i need help now", "someone is dying"
#     ],
# }
#
#
# # ─── Node Functions ──────────────────────────────────────────────
#
# def check_guardrails(state: CareFlowState) -> CareFlowState:
#     """
#     Node 1: Check if user is allowed to interact.
#     - Abuse strike check (3-strike system)
#     - Medical scope check
#     """
#     # Check if user is suspended
#     is_allowed, strike_msg = check_abuse_strikes(state["abuse_strikes"])
#     if not is_allowed:
#         return {
#             **state,
#             "route": "blocked",
#             "block_reason": strike_msg,
#             "response_message": strike_msg,
#         }
#
#     # Check if message is within medical scope
#     is_medical, scope_msg = check_medical_scope(state["message"])
#     if not is_medical:
#         new_strikes = state["abuse_strikes"] + 1
#         _, warning = check_abuse_strikes(new_strikes)
#         return {
#             **state,
#             "route": "blocked",
#             "block_reason": scope_msg,
#             "abuse_strikes": new_strikes,
#             "response_message": f"{scope_msg} {warning}".strip(),
#         }
#
#     return {**state, "route": "passed_guardrails"}
#
#
# def check_intent_override(state: CareFlowState) -> CareFlowState:
#     """
#     Node 2: Check for direct user intent.
#     If user explicitly asks for doctor/pharmacy/lab/ambulance → skip AI, go direct.
#     """
#     message_lower = state["message"].lower()
#
#     for intent, phrases in DIRECT_INTENT_MAP.items():
#         if any(phrase in message_lower for phrase in phrases):
#             return {
#                 **state,
#                 "route": intent,
#                 "response_message": f"Direct handoff: {intent}",
#             }
#
#     return {**state, "route": "needs_classification"}
#
#
# def check_emergency_keywords(state: CareFlowState) -> CareFlowState:
#     """
#     Node 3: Fast emergency keyword scan.
#     Catches stroke, chest pain, etc. BEFORE AI classification for speed.
#     """
#     if is_emergency(state["message"]):
#         return {
#             **state,
#             "route": "emergency",
#             "response_message": "Emergency keywords detected. Initiating emergency protocol.",
#         }
#
#     return {**state, "route": "needs_ai_classification"}
#
#
# def classify_with_ai(state: CareFlowState) -> CareFlowState:
#     """
#     Node 4: Use Gemini to classify the input into the correct flow.
#     This runs only when keywords and intent override didn't match.
#     """
#     llm = ChatGoogleGenerativeAI(
#         model="gemini-2.5-flash",
#         google_api_key=settings.google_api_key,
#     )
#
#     classification_prompt = SystemMessage(content="""You are CareFlow's input classifier.
# Classify the user message into exactly ONE category. Respond with ONLY the category name, nothing else.
#
# Categories:
# - EMERGENCY: Life-threatening symptoms (stroke signs, chest pain, severe bleeding, difficulty breathing, loss of consciousness)
# - MEDICAL: Physical health symptoms (headache, fever, cough, rash, stomach pain, injury, etc.)
# - MENTAL_HEALTH: Emotional distress, anxiety, depression, suicidal thoughts, panic, mood issues, stress
# - UNCLEAR: Cannot determine or not health-related
#
# Respond with exactly one word: EMERGENCY, MEDICAL, MENTAL_HEALTH, or UNCLEAR""")
#
#     user_msg = HumanMessage(content=state["message"])
#
#     response = llm.invoke([classification_prompt, user_msg])
#     classification = response.content.strip().upper()
#
#     # Map AI classification to route
#     route_map = {
#         "EMERGENCY": "emergency",
#         "MEDICAL": "medical",
#         "MENTAL_HEALTH": "mental_health",
#         "UNCLEAR": "medical",  # Default to medical flow for safety
#     }
#
#     route = route_map.get(classification, "medical")
#
#     return {
#         **state,
#         "route": route,
#         "classification": classification,
#         "response_message": f"Classified as: {classification}",
#     }
#
#
# # ─── Routing (Conditional Edge) Functions ────────────────────────
#
# def after_guardrails(state: CareFlowState) -> str:
#     """Route after guardrails check."""
#     if state["route"] == "blocked":
#         return "blocked"
#     return "check_intent"
#
#
# def after_intent(state: CareFlowState) -> str:
#     """Route after intent override check."""
#     if state["route"] in ("doctor_handoff", "pharmacy_handoff", "lab_handoff", "emergency"):
#         return "direct_handoff"
#     return "check_emergency"
#
#
# def after_emergency_check(state: CareFlowState) -> str:
#     """Route after emergency keyword check."""
#     if state["route"] == "emergency":
#         return "emergency_detected"
#     return "classify"
#
#
# def after_classification(state: CareFlowState) -> str:
#     """Route after AI classification."""
#     route = state["route"]
#     if route == "emergency":
#         return "emergency_detected"
#     elif route == "mental_health":
#         return "mental_health_detected"
#     else:
#         return "medical_detected"
#
#
# # ─── Build the Graph ─────────────────────────────────────────────
#
# def build_router_graph() -> StateGraph:
#     """
#     Build and compile the CareFlow input routing graph.
#
#     Flow:
#     START → guardrails → intent_override → emergency_keywords → ai_classify → END
#
#     Each node can short-circuit to a terminal state (blocked, direct_handoff, emergency).
#     """
#     graph = StateGraph(CareFlowState)
#
#     # Add nodes
#     graph.add_node("guardrails", check_guardrails)
#     graph.add_node("intent_override", check_intent_override)
#     graph.add_node("emergency_keywords", check_emergency_keywords)
#     graph.add_node("ai_classify", classify_with_ai)
#
#     # Set entry point
#     graph.set_entry_point("guardrails")
#
#     # Conditional edges
#     graph.add_conditional_edges(
#         "guardrails",
#         after_guardrails,
#         {
#             "blocked": END,
#             "check_intent": "intent_override",
#         }
#     )
#
#     graph.add_conditional_edges(
#         "intent_override",
#         after_intent,
#         {
#             "direct_handoff": END,
#             "check_emergency": "emergency_keywords",
#         }
#     )
#
#     graph.add_conditional_edges(
#         "emergency_keywords",
#         after_emergency_check,
#         {
#             "emergency_detected": END,
#             "classify": "ai_classify",
#         }
#     )
#
#     graph.add_conditional_edges(
#         "ai_classify",
#         after_classification,
#         {
#             "emergency_detected": END,
#             "mental_health_detected": END,
#             "medical_detected": END,
#         }
#     )
#
#     return graph.compile()
#
#
# # ─── Compiled Router (importable singleton) ──────────────────────
# router_graph = build_router_graph()
#
#
# # ─── Convenience Function ────────────────────────────────────────
#
# async def route_input(
#     user_id: str,
#     message: str,
#     session_id: str = None,
#     abuse_strikes: int = 0,
# ) -> CareFlowState:
#     """
#     Main entry point to route user input through CareFlow.
#
#     Usage:
#         result = await route_input("user123", "I have a headache")
#         print(result["route"])  # "medical"
#
#     Returns the final state with routing decision.
#     """
#     initial_state: CareFlowState = {
#         "user_id": user_id,
#         "message": message,
#         "session_id": session_id,
#         "abuse_strikes": abuse_strikes,
#         "route": "",
#         "block_reason": None,
#         "classification": None,
#         "confidence": None,
#         "response_message": None,
#     }
#
#     # LangGraph's invoke is synchronous — run it
#     result = router_graph.invoke(initial_state)
#     return result
"""
CareFlow Input Router — LangGraph StateGraph

This is the central nervous system of CareFlow.
It takes user input and routes it through:
  1. Guardrails check (medical scope + abuse strikes)
  2. Emergency keyword detection
  3. User intent override (direct handoff requests)
  4. AI-powered classification (Gemini) → route to correct flow

Routes to:
  - emergency   → emergency confirmation + services
  - medical     → triage + severity scoring + handoff (includes mental health)
  - doctor_handoff / pharmacy_handoff / lab_handoff → direct skip
  - blocked     → abuse / out-of-scope
"""

import re
from typing import Optional
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings
from app.core.severity import is_emergency
from app.core.guardrails import check_medical_scope, check_abuse_strikes


# ─── State Schema ───────────────────────────────────────────────
class CareFlowState(TypedDict):
    """State that flows through the entire routing graph."""
    # Input
    user_id: str
    message: str
    session_id: Optional[str]

    # User context (loaded from DB later)
    abuse_strikes: int

    # Routing decisions
    route: str  # emergency | medical | doctor_handoff | pharmacy_handoff | lab_handoff | blocked
    block_reason: Optional[str]

    # AI classification result
    classification: Optional[str]
    doctor_specialty: Optional[str]  # e.g. pediatrician, general_physician, dermatologist (when route is medical/doctor_handoff)

    # Output
    response_message: Optional[str]


# ─── Greeting (no classification, no strike) ─────────────────────
GREETING_PHRASES = {
    "hello", "hi", "hey", "hola", "good morning", "good afternoon",
    "good evening", "good night", "good day", "how are you",
    "how do you do", "thanks", "thank you", "bye", "goodbye",
    "good bye", "see you", "hey there", "hi there",
}


def _normalize_for_greeting(msg: str) -> str:
    return re.sub(r"[^\w\s]", "", msg.lower()).strip()


def check_greeting(state: CareFlowState) -> CareFlowState:
    """
    Node 0: If the message is only a greeting/small talk, respond warmly.
    No medical scope check, no AI classification, no strike.
    """
    normalized = _normalize_for_greeting(state["message"])
    if not normalized:
        return {
            **state,
            "route": "greeting",
            "response_message": "Hi! How can I help you today?",
        }
    if normalized in GREETING_PHRASES or any(normalized == g for g in GREETING_PHRASES):
        return {
            **state,
            "route": "greeting",
            "response_message": "Hi! How can I help you today?",
        }
    # Very short message that looks like a greeting (e.g. "hello!")
    if len(normalized) <= 25 and any(g in normalized for g in ("hello", "hi", "hey", "thanks", "bye")):
        return {
            **state,
            "route": "greeting",
            "response_message": "Hi! How can I help you today?",
        }
    return {**state, "route": "not_greeting"}


# ─── Intent Override Keywords ────────────────────────────────────
DIRECT_INTENT_MAP = {
    "doctor_handoff": [
        "doctor", "doctors", "i want a doctor", "i want doctor", "find me a doctor", "book a doctor",
        "need a doctor", "need doctor", "talk to a doctor", "see a doctor",
        "consult a doctor", "doctor please", "find doctor", "get doctor", "find me doctor",
    ],
    "pharmacy_handoff": [
        "i need medicine", "find a pharmacy", "buy medicine",
        "need medication", "pharmacy near me", "otc medicine",
        "medicine", "medicines", "pharmacy", "pharmacies",
        "need medicine", "want medicine", "get medicine", "buy medication",
        "find pharmacy", "nearby pharmacy", "medication",
    ],
    "lab_handoff": [
        "book a lab test", "i need a blood test", "lab test",
        "need lab work", "diagnostic test", "find a lab",
        "blood test", "blood work", "get a blood test", "want blood test",
        "need blood test", "blood test done", "diagnostic lab", "pathology",
        "test", "tests", "scan", "scans", "diagnosis", "diagnostic",
    ],
    "emergency": [
        "call ambulance", "need ambulance", "call 112",
        "emergency", "i need help now", "someone is dying",
    ],
}


# ─── Node Functions ──────────────────────────────────────────────

def check_guardrails(state: CareFlowState) -> CareFlowState:
    """
    Node 1: Check if user is allowed to interact.
    - Abuse strike check (3-strike system)
    - Medical scope check
    """
    is_allowed, strike_msg = check_abuse_strikes(state["abuse_strikes"])
    if not is_allowed:
        return {
            **state,
            "route": "blocked",
            "block_reason": strike_msg,
            "response_message": strike_msg,
        }

    is_medical, scope_msg = check_medical_scope(state["message"])
    if not is_medical:
        new_strikes = state["abuse_strikes"] + 1
        _, warning = check_abuse_strikes(new_strikes)
        return {
            **state,
            "route": "blocked",
            "block_reason": scope_msg,
            "abuse_strikes": new_strikes,
            "response_message": f"{scope_msg} {warning}".strip(),
        }

    return {**state, "route": "passed_guardrails"}


def check_intent_override(state: CareFlowState) -> CareFlowState:
    """
    Node 2: Check for direct user intent.
    If user explicitly asks for doctor/pharmacy/lab/ambulance → skip AI, go direct.
    """
    message_lower = state["message"].lower()

    for intent, phrases in DIRECT_INTENT_MAP.items():
        if any(phrase in message_lower for phrase in phrases):
            return {
                **state,
                "route": intent,
                "response_message": f"Direct handoff: {intent}",
            }

    return {**state, "route": "needs_classification"}


def check_emergency_keywords(state: CareFlowState) -> CareFlowState:
    """
    Node 3: Fast emergency keyword scan.
    Catches stroke, chest pain, etc. BEFORE AI classification for speed.
    """
    if is_emergency(state["message"]):
        return {
            **state,
            "route": "emergency",
            "response_message": "Emergency keywords detected. Initiating emergency protocol.",
        }

    return {**state, "route": "needs_ai_classification"}


def classify_with_ai(state: CareFlowState) -> CareFlowState:
    """
    Node 4: Use Gemini to classify the input.
    Mental health is treated as medical — both go to doctor handoff.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.google_api_key,
    )

    classification_prompt = SystemMessage(content="""You are CareFlow's input classifier.
Classify the user message into exactly ONE category.
Then, if the category is MEDICAL, add a second line with the type of doctor most appropriate.

Categories (first line only):
- EMERGENCY: Life-threatening symptoms (stroke signs, chest pain, severe bleeding, difficulty breathing, loss of consciousness, suicidal intent)
- MEDICAL: Any health concern — physical OR mental (headache, fever, anxiety, depression, stress, panic attacks, insomnia, mood issues, injury, etc.)
- UNCLEAR: Cannot determine or not health-related

Doctor type (second line ONLY when first line is MEDICAL):
Use one or two words for the specialization. Examples: general_physician, pediatrician, dermatologist, cardiologist, gynecologist, orthopedic, psychiatrist, neurologist, dentist, ophthalmologist, ent, gastroenterologist, pulmonologist, nephrologist, urologist, rheumatologist, endocrinologist, clinic.
Use underscores for multi-word (e.g. general_physician). For unspecified or generic use: general_physician or clinic.

Format:
Line 1: EMERGENCY or MEDICAL or UNCLEAR
Line 2 (only if MEDICAL): the doctor specialization (e.g. pediatrician, neurologist, dentist)""")

    user_msg = HumanMessage(content=state["message"])
    response = llm.invoke([classification_prompt, user_msg])
    raw = (response.content or "").strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    classification = (lines[0].upper() if lines else "MEDICAL")
    doctor_specialty = None
    if len(lines) >= 2 and classification == "MEDICAL":
        spec = lines[1].strip().lower().replace(" ", "_")
        if spec:
            doctor_specialty = spec

    route_map = {
        "EMERGENCY": "emergency",
        "MEDICAL": "medical",
        "UNCLEAR": "unclear",
    }
    route = route_map.get(classification, "medical")

    return {
        **state,
        "route": route,
        "classification": classification,
        "doctor_specialty": doctor_specialty,
        "response_message": f"Classified as: {classification}",
    }


# ─── Conditional Edge Functions ──────────────────────────────────

def after_guardrails(state: CareFlowState) -> str:
    if state["route"] == "blocked":
        return "blocked"
    return "check_intent"


def after_intent(state: CareFlowState) -> str:
    if state["route"] in ("doctor_handoff", "pharmacy_handoff", "lab_handoff", "emergency"):
        return "direct_handoff"
    return "check_emergency"


def after_emergency_check(state: CareFlowState) -> str:
    if state["route"] == "emergency":
        return "emergency_detected"
    return "classify"


def after_classification(state: CareFlowState) -> str:
    if state["route"] == "emergency":
        return "emergency_detected"
    return "medical_detected"


def after_greeting(state: CareFlowState) -> str:
    if state["route"] == "greeting":
        return "greeting_done"
    return "guardrails"


# ─── Build the Graph ─────────────────────────────────────────────

def build_router_graph():
    """
    Flow:
    START → greeting → [if not greeting] guardrails → intent_override → emergency_keywords → ai_classify → END
    Greetings skip classification and do not count as medical-scope abuse.
    """
    graph = StateGraph(CareFlowState)

    graph.add_node("greeting", check_greeting)
    graph.add_node("guardrails", check_guardrails)
    graph.add_node("intent_override", check_intent_override)
    graph.add_node("emergency_keywords", check_emergency_keywords)
    graph.add_node("ai_classify", classify_with_ai)

    graph.set_entry_point("greeting")
    graph.add_conditional_edges("greeting", after_greeting, {
        "greeting_done": END,
        "guardrails": "guardrails",
    })

    graph.add_conditional_edges("guardrails", after_guardrails, {
        "blocked": END,
        "check_intent": "intent_override",
    })

    graph.add_conditional_edges("intent_override", after_intent, {
        "direct_handoff": END,
        "check_emergency": "emergency_keywords",
    })

    graph.add_conditional_edges("emergency_keywords", after_emergency_check, {
        "emergency_detected": END,
        "classify": "ai_classify",
    })

    graph.add_conditional_edges("ai_classify", after_classification, {
        "emergency_detected": END,
        "medical_detected": END,
    })

    return graph.compile()


# Compiled singleton — import this
router_graph = build_router_graph()


# ─── Convenience Function ────────────────────────────────────────

async def route_input(
    user_id: str,
    message: str,
    session_id: str = None,
    abuse_strikes: int = 0,
) -> CareFlowState:
    """
    Main entry point for routing user input.

    Returns the final state with:
      - route: where to send the user
      - classification: what AI detected (if AI was called)
      - response_message: human-readable status
    """
    initial_state: CareFlowState = {
        "user_id": user_id,
        "message": message,
        "session_id": session_id,
        "abuse_strikes": abuse_strikes,
        "route": "",
        "block_reason": None,
        "classification": None,
        "doctor_specialty": None,
        "response_message": None,
    }

    result = router_graph.invoke(initial_state)
    return result