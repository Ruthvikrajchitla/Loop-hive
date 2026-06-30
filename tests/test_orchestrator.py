"""
LoopHive — Orchestrator Integration Test

Runs the entire swarm pipeline end-to-end (mocked LLM outputs where necessary).
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock
from core.loop_engine import LoopStatus
from agents.orchestrator import OrchestratorAgent
from core.llm_router import llm_router


# Define mock LLM responses based on query contents
async def mock_llm_generate(messages, temperature=0.7, max_tokens=4096, json_mode=False, task_type="general"):
    user_prompt = messages[-1]["content"].lower()
    
    # 1. Niche Scout
    if "niche scout" in user_prompt or "niche candidate" in user_prompt or "trends" in user_prompt:
        return {
            "content": json.dumps({
                "candidates": [
                    {
                        "name": "Notion Productivity",
                        "keywords": ["notion planner", "productivity template"],
                        "monetization_potential": 9.0,
                        "competition": 3.0,
                        "content_strategy": "Build Notion planner templates and market on Gumroad.",
                        "score": 92.5
                    }
                ]
            }),
            "tokens_used": 100,
            "provider": "mock",
            "model": "mock-model"
        }
        
    # 2. Legal Researcher
    elif "legal risk" in user_prompt or "compliance rulebook" in user_prompt:
        return {
            "content": json.dumps({
                "niche": "Notion Productivity",
                "allowed_content_types": ["articles", "newsletters", "guides"],
                "banned_types": [],
                "disclosures": {
                    "ftc_affiliate": "This post contains affiliate links. If you purchase through these links, I may earn a commission.",
                    "ai_disclosure": "This content was created with the assistance of AI tools.",
                    "eu_ai_label": "[AI-GENERATED CONTENT]"
                },
                "rules": [
                    {
                        "category": "ftc",
                        "rule_text": "FTC affiliate warning required.",
                        "severity": "required",
                        "platform": "substack",
                        "disclosure_template": "This post contains affiliate links. If you purchase through these links, I may earn a commission."
                    },
                    {
                        "category": "eu_ai_act",
                        "rule_text": "Label AI-generated text.",
                        "severity": "required",
                        "platform": "substack",
                        "disclosure_template": "[AI-GENERATED CONTENT]"
                    },
                    {
                        "category": "platform_tos",
                        "rule_text": "No paywalling AI content on Medium.",
                        "severity": "required",
                        "platform": "medium",
                        "disclosure_template": None
                    }
                ]
            }),
            "tokens_used": 150,
            "provider": "mock",
            "model": "mock-model"
        }

    # 3. Content Writer Outline
    elif "structural outline" in user_prompt:
        return {
            "content": json.dumps({
                "title": "10 Notion Hacks That Saved Me 5 Hours/Week",
                "keywords": ["notion planner", "productivity template"],
                "outline_sections": [
                    {"heading": "Introduction", "description": "Intro to Notion productivity."},
                    {"heading": "Section 1", "description": "First productivity hack."}
                ]
            }),
            "tokens_used": 80,
            "provider": "mock",
            "model": "mock-model"
        }

    # 4. Content Writer Polishing
    elif "editing the following article" in user_prompt:
        # Generate a sufficiently long body (> 1000 characters)
        long_body = (
            "# 10 Notion Hacks That Saved Me 5 Hours/Week\n\n"
            "Organizing a digital workspace is one of the most effective ways to reclaim lost time. "
            "In this guide, we explore how Notion, a leading modular database tool, can be optimized for productivity. "
            "First, let's look at relational databases. By linking task databases to project databases, "
            "you create a single source of truth that avoids duplicate entries. "
            "Second, templates are vital. Instead of manually setting up weekly reviews, create a button "
            "that instantly populates the standard checklist, headings, and targets. "
            "Third, leverage database views. Keep a clean 'Focus Today' view filtered strictly for due dates, "
            "hiding everything else. This keeps cognitive load low and reduces screen distraction. "
            "Fourth, automate integrations. Using services like Make or Zapier, you can route email reminders "
            "directly into your inbox database. "
            "Fifth, use the Web Clipper. Save reference articles directly into a 'Reading List' database, "
            "categorizing them immediately. "
            "By implementing these core systems, freelancers and students report saving upwards of five hours "
            "per week. The key is consistent organization and avoiding complex aesthetics that add overhead. "
            "Keep databases flat and clean, prioritizing utility over styling."
        )
        return {
            "content": json.dumps({
                "meta_description": "Boost your productivity with these 10 Notion hacks.",
                "word_count": 250,
                "polished_body": long_body
            }),
            "tokens_used": 120,
            "provider": "mock",
            "model": "mock-model"
        }

    # 5. Content Critic
    elif "critique the following" in user_prompt:
        return {
            "content": json.dumps({
                "score": 85.0,
                "readability": "Easy",
                "seo_alignment": "Good",
                "formatting_ok": True,
                "depth_rating": 8.5,
                "critique": "Draft looks solid and has good formatting.",
                "improvements": ["None required."]
            }),
            "tokens_used": 90,
            "provider": "mock",
            "model": "mock-model"
        }

    # 6. Plagiarism Checker / Originality review
    elif "originality, boilerplate" in user_prompt or "originality review" in user_prompt:
        return {
            "content": json.dumps({
                "score": 92.0,
                "flagged_sections": [],
                "reasoning": "Text is highly original with no generic boilerplate phrases detected."
            }),
            "tokens_used": 80,
            "provider": "mock",
            "model": "mock-model"
        }

    # 7. Product Outline
    elif "design a digital product" in user_prompt:
        return {
            "content": json.dumps({
                "product_name": "Ultimate Notion Productivity Planner Template",
                "niche": "Notion Productivity",
                "target_price": 12.00,
                "outline": [
                    {"title": "Getting Started", "objectives": "Set up the planner."},
                    {"title": "Daily Planning", "objectives": "Log daily tasks."}
                ],
                "pain_points_solved": ["Disorganization", "Inefficient planning"]
            }),
            "tokens_used": 110,
            "provider": "mock",
            "model": "mock-model"
        }

    # 8. Product chapter drafting (per-chapter generation)
    elif "writing chapter" in user_prompt or "finished content of this digital product" in user_prompt or "write the complete content body" in user_prompt:
        # Generate a sufficiently long product content (> 1500 characters)
        long_product_body = (
            "# Ultimate Notion Productivity Planner\n\n"
            "This checklist serves as your complete guide to configuring a high-performance Notion planner. "
            "Follow these steps to eliminate workspace clutter and focus on execution. "
            "By taking charge of your digital environment, you reduce the time wasted looking for files and tasks.\n\n"
            "## Step 1: Establish Your Project Database\n"
            "Create a master database called 'Projects'. Add properties for 'Status' (Not Started, In Progress, Complete), "
            "'Timeline' (Start and End Dates), and 'Owner'. Every project must represent a larger goal. "
            "This ensures that individual tasks are always contributing to a broader context.\n\n"
            "## Step 2: Establish Your Tasks Database\n"
            "Create a database called 'Tasks'. Add a Relation property linking to 'Projects'. Add properties for "
            "'Due Date', 'Priority' (High, Medium, Low), and a checkbox 'Done'. This creates a clear hierarchy "
            "and allows you to see how each task supports your primary objectives.\n\n"
            "## Step 3: Configure Daily Views\n"
            "Set up a database view on your homepage. Filter the Tasks database: 'Due Date' is on or before 'Today', "
            "and 'Done' is unchecked. Sort by Priority descending. This is your focus list for the day, "
            "letting you ignore long-term tasks and avoid feeling overwhelmed by massive checklists.\n\n"
            "## Step 4: Implement Weekly Reviews\n"
            "Every Sunday, spend 15 minutes reviewing active projects. Archive completed items, assign dates to new tasks, "
            "and clear out backlog items. Consistently cleaning database structures prevents cognitive load "
            "and maintains database performance over time.\n\n"
            "## Step 5: Advanced Customizations\n"
            "Utilize Notion button properties to quick-log standard subtasks. Combine templates to auto-populate "
            "standard project briefs, reducing typing time. Leverage formulas to compute progress bars. "
            "Keep the overall layout flat, clean, and visually distraction-free for optimal productivity."
        )
        return {
            "content": long_product_body,
            "tokens_used": 200,
            "provider": "mock",
            "model": "mock-model"
        }

    # 9. Product Sales Page Copy
    elif "sales landing page" in user_prompt:
        return {
            "content": (
                "# Ultimate Notion Productivity Planner\n\n"
                "Are you tired of cluttered templates that slow down your computer and mind? "
                "The Ultimate Notion Productivity Planner is built for execution. "
                "It contains project and task databases pre-configured for focus. "
                "Purchase now for only $12.00 and save 5 hours every single week."
            ),
            "tokens_used": 100,
            "provider": "mock",
            "model": "mock-model"
        }

    # 10. Marketing Agent
    elif "organic marketing campaign" in user_prompt:
        return {
            "content": json.dumps({
                "campaign_name": "Notion Productivity Launch",
                "channels": [
                    {
                        "name": "x",
                        "copy": "Here is how to structure your Notion workspace for maximum efficiency. Thread below 👇",
                        "strategy": "Post as a Twitter thread."
                    },
                    {
                        "name": "reddit",
                        "copy": "Sharing my Notion setup that saves me 5 hours a week. Hope this helps someone!",
                        "strategy": "Post to r/Notion."
                    }
                ]
            }),
            "tokens_used": 140,
            "provider": "mock",
            "model": "mock-model"
        }

    # Default fallback content
    return {
        "content": "This is a generic mock response.",
        "tokens_used": 50,
        "provider": "mock",
        "model": "mock-model"
    }


@pytest.mark.asyncio
@patch("core.llm_router.LLMRouter.generate", new_callable=AsyncMock)
async def test_full_pipeline_orchestration(mock_generate):
    """Verify that the orchestrator runs the entire swarm pipeline successfully."""
    # Wire the mock generate behavior
    mock_generate.side_effect = mock_llm_generate

    # This test exercises the niche-discovery path, so disable the forced niche.
    from core.config import config
    config.forced_niche = ""
    # Keep ebook length thresholds tiny so the mocked chapters satisfy verify.
    config.ebook_min_sections = 1
    config.ebook_section_words = 50

    # Initialize the orchestrator
    orchestrator = OrchestratorAgent()
    
    # Run the full pipeline
    result = await orchestrator.act({"goal": "Run E2E pipeline for testing"})
    
    # Check that all stages completed and logged results
    assert result is not None
    assert "niche" in result
    assert result["niche"]["name"] == "Notion Productivity"
    assert result["rulebook_rules_count"] == 3
    assert result["article_written"] is True
    assert result["critic_score"] == 85.0
    assert result["originality_score"] >= 85.0
    assert result["compliance_passed"] is True
    assert result["product_created"] is True
    assert result["product_name"] == "Ultimate Notion Productivity Planner Template"
    assert result["marketing_channels"] == 2
    assert result["eval_decision"] == "continue"
    
    # Run the verification step
    verification = await orchestrator.verify(result, "Verify pipeline")
    assert verification.is_complete is True
    assert verification.score == 100.0
