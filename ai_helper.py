from flask import json
import google.generativeai as genai
import os
import re

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


# ✅ SINGLE correct version
def _safe_gemini_call(prompt):
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)

    if not response or not response.text:
        return ""

    return response.text.strip()


def simplify_content(text):
    prompt = f"""
Simplify and explain the following content in a clear, student-friendly way.
Use bullet points, simple language, and examples where helpful.

Content:
{text[:3000]}

Provide a well-structured explanation.
"""
    return _safe_gemini_call(prompt)


def generate_quiz_from_ai(text):
    prompt = f"""
You are a university exam paper setter. Create exam-quality questions from this content.

{text[:3000]}

QUESTION TYPES TO GENERATE:
- MCQ: 3-4 questions, 2 marks each
- Short answer: 2-3 questions, 3 marks each
- Long answer: 1-2 questions, 5 marks each

ANSWER QUALITY RULES — THIS IS CRITICAL:

For MCQ:
- answer = exact text of the correct option only

For SHORT ANSWER (3 marks):
- Write a proper 3-sentence answer
- Each sentence should cover one distinct point
- Must be good enough to score full 3 marks in a university exam
- Example: "The SNS topic acts as a notification channel for CloudWatch alarms. When the alarm threshold is breached, CloudWatch publishes a message to the SNS topic. The topic then delivers this notification via email or SMS to all subscribed endpoints."

For LONG ANSWER (5 marks):
- Write a detailed paragraph-style answer with exactly 5 clear points
- Each point should be a complete sentence explaining a step or concept
- Must be thorough enough to score full 5 marks in a university exam
- Example: "First, the user navigates to the CloudWatch console and selects the Alarms section to begin. Next, clicking Create Alarm opens the metric selection screen where a specific AWS metric is chosen. The user then configures the statistic type such as Maximum or Average and sets the evaluation period in minutes. After that, a threshold condition is defined such as CPU utilization greater than 30 percent to determine when the alarm triggers. Finally, an SNS topic is linked to the alarm so that email or SMS notifications are sent automatically when the condition is met."

Return ONLY a valid JSON array, no markdown, no code blocks:
[
  {{
    "question": "Which AWS service sends notifications when a CloudWatch alarm is triggered?",
    "question_type": "mcq",
    "marks": 2,
    "options": ["SQS", "SNS", "SES", "Lambda"],
    "answer": "SNS"
  }},
  {{
    "question": "What is the purpose of configuring an SNS topic in a CloudWatch alarm?",
    "question_type": "short",
    "marks": 3,
    "options": null,
    "answer": "The SNS topic acts as a notification channel that receives the alarm trigger from CloudWatch. When the defined threshold condition is breached, CloudWatch publishes an alert message to the SNS topic. The topic then delivers this notification to all subscribed users via email or SMS ensuring timely awareness of the issue."
  }},
  {{
    "question": "Describe the complete process of creating a CloudWatch alarm with metric configuration and notification setup.",
    "question_type": "long",
    "marks": 5,
    "options": null,
    "answer": "The process begins by navigating to the CloudWatch console and clicking on Alarms followed by Create Alarm to start the setup wizard. Next, the user clicks Select Metric and browses the available AWS service categories such as EC2 to choose a specific metric like CPUUtilization. The statistic type such as Maximum or Average is then selected along with the evaluation period which defines how frequently the metric is checked. After that, a threshold condition is configured under the Conditions section such as triggering the alarm when CPU utilization is Greater Than 30 percent. Finally, an SNS topic is selected or created to handle notifications, a name is given to the alarm, and the configuration is confirmed by clicking Create Alarm."
  }}
]

Generate 7-10 questions. Return ONLY the JSON array.
"""
    return _safe_gemini_call(prompt)


# ✅ SINGLE correct version
def generate_match_game(text):
    prompt = f"""
Return ONLY valid JSON.
No markdown. No explanation.

Format:
[
  {{
    "concept": "EC2",
    "definition": "A virtual server provided by AWS"
  }}
]

Create a match-the-following game from this content:

{text[:10000]}
"""
    return _safe_gemini_call(prompt)


def generate_flashcards_from_content(simplified_content, topic_title, num_cards=12):
    prompt = f"""You are an expert educator. Create {num_cards} flashcards from the following simplified content about {topic_title}.

Content:
{simplified_content}

Generate flashcards that test understanding, not just memorization. Include a mix of difficulty levels.

Return ONLY a valid JSON array with NO markdown formatting, NO code blocks, NO backticks. Just the raw JSON array.

Format:
[
    {{"question": "What is the main purpose of...?", "answer": "The main purpose is...", "difficulty": "easy"}},
    {{"question": "Explain how...", "answer": "It works by...", "difficulty": "medium"}},
    {{"question": "Compare and contrast...", "answer": "The key differences are...", "difficulty": "hard"}}
]

Rules:
- Questions should be clear and specific
- Answers should be concise (2-3 sentences max)
- Use difficulty levels: easy, medium, hard
- Mix question types (what, how, why, explain, compare)
- Return ONLY the JSON array, nothing else"""

    try:
        content = _safe_gemini_call(prompt)
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'^```\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        content = content.strip()

        flashcards = json.loads(content)

        if not isinstance(flashcards, list):
            return None

        valid_flashcards = []
        for card in flashcards:
            if isinstance(card, dict) and 'question' in card and 'answer' in card:
                if 'difficulty' not in card:
                    card['difficulty'] = 'medium'
                valid_flashcards.append(card)

        return valid_flashcards if valid_flashcards else None

    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return None
    except Exception as e:
        print(f"Error generating flashcards: {e}")
        return None
    
def ai_grade_answer(question, correct_answer, user_answer, max_marks):
    prompt = f"""
You are a strict university exam grader.

Question: {question}
Model answer ({max_marks} marks): {correct_answer}
Student answer: {user_answer}

Grading rules:
- Compare the student's answer against the model answer
- Award 1 mark for each correct point or concept mentioned
- Partial credit allowed (0.5 marks) for vague but relevant points
- Maximum = {max_marks} marks
- Be strict — a one-line answer for a 5-mark question should NOT get full marks

Return ONLY a single number between 0 and {max_marks}. Nothing else. No explanation.
"""
    try:
        result = _safe_gemini_call(prompt).strip()
        score = float(re.search(r'[\d.]+', result).group())
        return round(min(score, max_marks))
    except:
        return 0