# CareFlow -- Complete System Architecture & Product Blueprint

## Overview

CareFlow is an AI-powered healthcare navigation and triage web platform.
It focuses on safe triage, structured routing, and fast handoff to
real-world healthcare providers.

Core Philosophy: - Handoff-first design - No diagnosis claims - Short
responses - Strict medical-only scope - Safety & guardrails built-in -
Cost-efficient AI usage

------------------------------------------------------------------------

# 1. Core System Layers

## 1. User Intent Override Layer

If user directly asks for: - Doctor - Medicine - Lab test - Ambulance

→ Immediate handoff (no AI reasoning)

------------------------------------------------------------------------

## 2. Duplicate Session Detection

If same symptoms within 6 hours: → Do not re-triage → Remind previous
guidance → Show doctor handoff

------------------------------------------------------------------------

## 3. Input Router (LangGraph)

Routes input into: - Emergency Flow - Medical Flow - Visual Triage
Flow - Mental Health Flow

------------------------------------------------------------------------

# 2. Emergency Flow

Triggers: - Stroke - Chest pain (severe) - Severe bleeding - Critical
triage score

Flow: 1. 3-step confirmation 2. Show Emergency Screen: - Call 112 -
Nearby emergency hospitals - Ambulance services

------------------------------------------------------------------------

# 3. Medical Flow

Includes: - Triage severity scoring - Psychological severity scoring -
Safety guardrails

Severity Model: Medical Levels: M0--M3 Psychological Levels: P0--P3

Decision Matrix: - High medical → Emergency - Moderate medical → Doctor
handoff - High psychological → Crisis helpline - Low risk → OTC (if
allowed)

------------------------------------------------------------------------

# 4. OTC Privilege System

Each user gets: - Total 3 OTC chances

Database Fields: - otc_attempts_used - otc_privilege_status (ACTIVE \|
LOCKED) - otc_unlock_requests

After 3 attempts: → OTC locked → Only manual approval resets

------------------------------------------------------------------------

# 5. Smart Hospital Capability Filtering

Tags: - EMERGENCY - MULTI_SPECIALTY - CLINIC - SPECIALTY_CENTER -
DIAGNOSTIC_CENTER

Routing logic adapts based on: - Emergency - Specialist need -
Night-time logic

------------------------------------------------------------------------

# 6. Night-Time Routing Logic

Between 10 PM -- 7 AM: - Hide small clinics - Show only 24x7 hospitals -
Show open labs only

------------------------------------------------------------------------

# 7. Location Confirmation Layer

Before showing providers: → Confirm detected city → Allow manual change

------------------------------------------------------------------------

# 8. Structured Symptom Forms

For common symptoms: - Fever - Chest pain - Headache - Rash

Use quick selectable forms to: - Reduce tokens - Improve accuracy -
Reduce hallucination risk

------------------------------------------------------------------------

# 9. Session Timeout & Rate Limiting

Rules: - Max 10 sessions per day - Max 8 messages per session - Session
auto-closes after handoff - 10-minute inactivity timeout

------------------------------------------------------------------------

# 10. Maps Ranking Engine

Google Maps used as data provider only.

CareFlow adds: - Medical keyword filtering - Rating filter - Open-now
filter - Custom ranking formula - Context-aware sorting

------------------------------------------------------------------------

# 11. Mental Health Flow

Parallel severity scoring: - P0--P3

If crisis detected: → Immediate helpline

If moderate distress: → Supportive stabilization → Therapist handoff

------------------------------------------------------------------------

# 12. Health Timeline

Stores: - Symptoms - OTC attempts - Doctor visits - Lab tests -
Emergency events - Mood logs

Provides: - Recovery tracking - Session history - Insight generation

------------------------------------------------------------------------

# 13. Abuse & Scope Control

3-strike system for non-medical questions: 1. Gentle warning 2. Strong
warning 3. Account suspension

Medical-only platform.

------------------------------------------------------------------------

# 14. Hosting Architecture

Frontend: Next.js (Vercel) Backend: FastAPI (Render) Database:
PostgreSQL (Supabase/Neon) AI: CrewAI + LangGraph Maps: Google Maps API

Estimated Monthly Cost: ₹4,000 -- ₹8,000 (early stage)

------------------------------------------------------------------------

# Final Philosophy

CareFlow is: - Not a diagnosis app - Not a prescription engine - A
healthcare navigation & triage system

Core Loop: User → Triage → Risk Scoring → Smart Routing → Handoff →
Timeline Update

------------------------------------------------------------------------

End of Document
