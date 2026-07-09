from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    field_name: str
    kind: str
    question_patterns: tuple[str, ...] = ()
    answer_keywords: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    default_text: str = "Not mentioned"


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("Participant Name", "text", ("what is your name", "what should i call you", "who are you", "introduce yourself")),
    FieldSpec("Current Tools", "text", ("what tools do you use", "what tools are you using", "what is your current workflow", "what software do you use", "what do you use today"), ("capcut", "premiere", "final cut", "davinci", "descript", "notion", "canva", "google docs", "sheets", "docs")),
    FieldSpec("Monthly Tool Spend", "text", ("how much do you spend", "what do you pay", "what are you paying", "what is your monthly tool spend", "how much are your tools", "what subscriptions do you pay for", "what tools do you currently pay for", "currently pay for each month", "pay for each month", "what do you spend on tools"), ("spend", "pay", "subscription", "monthly", "tool", "software", "dollars", "$")),
    FieldSpec("Platform", "select", ("where do you post", "what platform do you post on", "what platforms do you use", "which platform", "where are you posting", "what do you post on"), options=("TikTok", "Instagram Reels", "YouTube Shorts", "LinkedIn", "Multiple")),
    FieldSpec("Posts Per Week", "number", ("how many posts per week", "how often do you post", "how many times a week", "what is your posting frequency", "how much do you post"), ("post", "week", "times", "frequency")),
    FieldSpec("Goal Of Video", "multi_select", ("what is your goal", "what are you hoping", "what do you want from the video", "why are you making videos", "what is the goal of the video"), options=("Views", "Engagement", "Followers", "Brand Awareness", "Sales", "Client Approval")),
    FieldSpec("Current Review Process", "text", ("what is your review process", "how do you review", "how do you check", "what happens before posting", "what is your approval process"), ("review", "approve", "approval", "check", "feedback")),
    FieldSpec("Biggest Uncertainty", "text", ("what are you unsure about", "what is your biggest uncertainty", "what worries you", "what are you uncertain about", "what do you not know"), ("uncertain", "uncertainty", "unsure", "worried", "confused", "lost")),
    FieldSpec("Most Valuable Output", "text", ("what was most valuable", "what was most useful", "what was most helpful", "what did you like most", "what helped you most"), ("valuable", "useful", "helpful", "good", "great")),
    FieldSpec("Least Valuable Output", "text", ("what was least valuable", "what was least useful", "what did you not use", "what was the least helpful", "what felt like a waste"), ("least", "waste", "did not use", "didn't use", "unused")),
    FieldSpec("What Changed?", "text", ("what changed", "what was different", "what improved", "after using the tool", "before and after"), ("changed", "better", "worse", "different", "improved")),
    FieldSpec("Would Use On Next Video?", "select", ("would you use this again", "would you use this on your next video", "would you post with this", "next video", "would you keep using this"), options=("Definitely", "Probably", "Maybe", "Unlikely", "No")),
    FieldSpec("Did The Tool Change The Output?", "select", ("did the tool change the output", "did it change the video", "what changed in the video", "did it make changes", "did it only give confidence"), options=("Yes - Major Changes", "Yes - Minor Changes", "No Changes", "Gave Confidence Only")),
    FieldSpec("Did They Understand The Tool Quickly?", "select", ("did you understand the tool", "did it make sense", "was it clear", "what did you think of the tool", "did you get it"), options=("Yes", "Mostly", "Somewhat", "Confused", "Very Confused")),
    FieldSpec("Where Did They Get Confused?", "text", ("where did you get confused", "what was unclear", "what did you not understand", "what was confusing", "what did not make sense"), ("confusing", "unclear", "confused", "lost", "not sure")),
    FieldSpec("Did They Complete Onboarding?", "checkbox", ("did you finish onboarding", "did you complete onboarding", "did you finish setup", "did you complete setup", "did you finish the walkthrough"), ("onboarding", "setup", "walkthrough", "signed up", "sign up")),
    FieldSpec("Did They Create A Video?", "checkbox", ("did you create a video", "were you able to make a video", "did you make a video", "did you publish a video"), ("create", "made", "posted", "uploaded", "video")),
    FieldSpec("Did They Use A Prompt?", "checkbox", ("did you use a prompt", "did you use the prompt", "did you use a script", "did you use a template", "did you use ai prompts"), ("prompt", "prompts", "script", "template", "ai prompt")),
    FieldSpec("Expected Price", "text", ("how much would you pay", "what would you pay", "what price would you pay", "expected price", "what would you expect to pay"), ("would pay", "pay", "price", "cost", "subscription")),
    FieldSpec("Max Price", "text", ("what is the maximum price", "what is the most you would pay", "what is your price ceiling", "how much at most", "max price"), ("maximum", "max", "ceiling", "at most", "no more than", "up to")),
    FieldSpec("Referral Offered?", "checkbox", ("would you refer", "would you introduce", "could you connect", "would you put us in touch", "referral"), ("referral", "refer", "introduce", "connect you", "put you in touch")),
    FieldSpec("Follow-Up Booked?", "checkbox", ("can we follow up", "can we book", "should we schedule", "when should we check in", "follow up"), ("follow up", "follow-up", "book", "schedule", "next step", "check in")),
    FieldSpec("Follow-Up Actions", "text", ("what are the next steps", "what should we follow up on", "what actions should we take", "what is the follow up", "follow up actions"), ("next step", "follow up", "schedule", "connect", "send", "check")),
    FieldSpec("User Type", "select", ("what best describes you", "are you a creator", "are you an agency", "are you a brand", "what kind of user are you"), options=("Creator", "Agency", "Brand", "Editor", "Marketing Team")),
    FieldSpec("Video Used", "text", ("what video did you use", "which video did you use", "what content did you use", "what was the video"), ("video", "content", "recording", "clip")),
)
