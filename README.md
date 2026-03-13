# Learnify – AI Based Learning Platform

Learnify is an AI-powered interactive learning platform designed to simplify complex academic concepts and improve student engagement through AI explanations, quizzes, flashcards, and gamified learning features.

The platform transforms traditional learning into an interactive, personalized, and technology-driven experience by combining artificial intelligence with modern web technologies.

---

# Project Overview

Learnify helps students understand difficult topics using:

- AI-powered simplified explanations  
- Smart quizzes generated from study material  
- Flashcards and mini learning games  
- Performance analytics and progress tracking  
- Gamification features like badges and streaks  

Students can upload study materials, generate quizzes automatically, track their learning progress, and improve their understanding of academic subjects.

---

# Key Features

## 1. User Authentication
- Secure registration and login system  
- Password hashing using Werkzeug security  

## 2. AI Content Simplification
- Converts complex study materials into simple, structured explanations  

## 3. AI Generated Quizzes
Automatically generates:
- MCQ questions  
- Short answer questions  
- Long answer questions  

## 4. Flashcards and Learning Games
- Interactive flashcards  
- Match-the-following games  
- Gamified learning  

## 5. Personalized Dashboard
Users can track:
- Learning streaks  
- Quiz performance  
- Accuracy statistics  
- Earned badges  

## 6. Learning Analytics
- Visual performance tracking  
- Weak area detection  
- Progress improvement monitoring  

---

# Tech Stack

## Frontend
- HTML  
- CSS  
- Bootstrap  
- JavaScript  

## Backend
- Python  
- Flask Framework  

## Database
- MySQL  

## AI Integration
- OpenAI / Gemini API for:
  - Content simplification  
  - Quiz generation  
  - Flashcard creation  

## Other Tools
- Chart.js (Analytics visualization)

---

# System Architecture

User Browser  
↓  
Flask Web Application  
↓  
MySQL Database  
↓  
AI API (Content Simplification + Quiz Generation)

---

# Installation Guide

## 1. Clone the repository

git clone https://github.com/megha0511-cell/learnify.git  
cd learnify

---

## 2. Create Virtual Environment

python -m venv venv

Activate environment:

Windows  
venv\Scripts\activate  

Linux/Mac  
source venv/bin/activate

---

## 3. Install Dependencies

pip install flask mysql-connector-python google-generativeai

---

## 4. Setup Environment Variables

Create a `.env` file and add your API key:

GOOGLE_API_KEY=your_api_key_here

---

## 5. Run the Application

python app.py

Open in browser:

http://127.0.0.1:5000

---

# Database Structure

Main database tables:

- users  
- topics  
- topic_files  
- file_simplified  
- file_quizzes  
- file_questions  
- file_quiz_attempts  
- flashcards  
- badges  
- user_badges  

These tables maintain relationships between users, study materials, quizzes, and performance tracking.

---

# Security Features

- Password hashing  
- Input validation  
- SQL injection prevention  
- Secure file upload  
- Session authentication  

---

# Future Enhancements

- Mobile application version  
- Voice-based learning assistant  
- Adaptive AI learning paths  
- Collaborative learning features  

---

# Author

Megha Mangesh Chavan  
Bachelor of Science in Computer Science  
Pillai College of Arts, Commerce & Science  
University of Mumbai

---

# License

This project is developed for educational and academic purposes.
