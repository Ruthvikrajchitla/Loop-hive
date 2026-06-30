"""
LoopHive — Disclosure Templates

Standard disclaimers for regulatory compliance.
"""

# FTC disclaimers
FTC_AFFILIATE_STANDARD = (
    "This post contains affiliate links. If you make a purchase through these links, "
    "I may earn a small commission at no additional cost to you."
)

FTC_AFFILIATE_SHORT = (
    "Disclaimer: As an associate, I earn from qualifying purchases made through links in this post."
)

# AI usage disclosures
AI_ASSISTANCE_STANDARD = (
    "Notice: This article was created with the assistance of AI writing tools. "
    "All facts, quotes, and research have been verified by a human editor."
)

AI_GENERATED_FULL = (
    "Notice: This publication is generated entirely by an autonomous agent swarm. "
    "All recommendations are compiled by computer models and reviewed for compliance."
)

# EU AI Act machine-readable labels (Article 50)
EU_AI_LABEL_MACHINE = "<!-- metadata: { \"ai_generated\": true, \"compliance\": \"EU_AI_Act_Art50\" } -->"
EU_AI_LABEL_VISUAL = "[AI-GENERATED CONTENT]"

# Combined templates by platform
PLATFORM_DISCLOSURES = {
    "medium": [
        AI_ASSISTANCE_STANDARD,
        FTC_AFFILIATE_STANDARD
    ],
    "substack": [
        AI_ASSISTANCE_STANDARD,
        FTC_AFFILIATE_STANDARD
    ],
    "blog": [
        EU_AI_LABEL_MACHINE,
        FTC_AFFILIATE_STANDARD
    ],
    "social": [
        "#Ad #AI"
    ]
}
