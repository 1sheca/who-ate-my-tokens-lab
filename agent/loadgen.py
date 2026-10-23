"""Asks the agent a steady stream of questions.

INTERVAL_SECONDS sets the average gap between questions (default about 1 second).
With a real, rate-limited model (for example a free API tier), use 15 or more.
"""
import os
import random
import time

import requests

TARGET = os.environ.get("TARGET", "http://localhost:8080")
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "0.85"))
QUESTIONS = [
    "How do I reset my password?",
    "Where is my order 4821?",
    "Can I get a refund for order 1177?",
    "What is the total price with the student discount?",
    "How do I export my data?",
    "Why was my order delayed?",
    "What does the premium plan include?",
    "Calculate the discount on a yearly plan",
]

time.sleep(3)
while True:
    try:
        requests.get(TARGET + "/ask", params={"q": random.choice(QUESTIONS)}, timeout=60)
    except requests.RequestException:
        time.sleep(2)
    time.sleep(random.uniform(INTERVAL * 0.6, INTERVAL * 1.4))
